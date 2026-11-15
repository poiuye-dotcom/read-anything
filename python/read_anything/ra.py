"""read-anything 命令行。

    python3 ra.py list  xhs     "芯片 就业" --limit 10
    python3 ra.py list  zhihu   "IC 秋招"   --limit 10 --new
    python3 ra.py crawl zhihu   --queries "IC 秋招,芯片 就业" --limit 8
    python3 ra.py read  "https://www.rednote.com/search_result/..." --site xhs --comments 10
    python3 ra.py read-many --site xhs --urls urls.txt --workers 3
    python3 ra.py db stats
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests
import yaml
from lxml import etree

from . import browser
from .core import (
    LoginRequired,
    SanityError,
    Session,
    Store,
    extract_list,
    load_sites,
    sanity_check,
)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")


# --------------------------------------------------------------------------- 输出
def emit(rows: list[dict], as_json: bool, show: list[str]) -> None:
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        print("（空）")
        return
    for i, r in enumerate(rows, 1):
        title = (r.get("title") or "")[:64]
        extra = " ｜ ".join(f"{k}: {r[k]}" for k in show if r.get(k))
        print(f"{i:2}. {title}")
        if extra:
            print(f"    {extra[:110]}")
        if r.get("url"):
            print(f"    {r['url'][:100]}")


# --------------------------------------------------------------------------- 列表
def build_urls(site: dict, query: str) -> list[str]:
    tpl = site["search_url"].replace("{school}", site.get("school", "example"))
    q = urllib.parse.quote(query or "")
    if "{page}" in tpl:
        pag = site.get("paginate") or {}
        start = pag.get("start", 1)
        return [tpl.format(q=q, page=p) for p in range(start, start + pag.get("max", 1))]
    return [tpl.format(q=q)]


def list_dom(key: str, site: dict, query: str, limit: int) -> list[dict]:
    sess = Session(key, site)
    try:
        sess.check_login()
        rows: dict[str, dict] = {}
        for url in build_urls(site, query):
            sess.goto(url)
            for r in extract_list(sess, limit):
                rows.setdefault(r["url"], r)
            if len(rows) >= limit:
                break
        return list(rows.values())[:limit]
    finally:
        sess.close()


def list_rss(key: str, site: dict, query: str, limit: int) -> list[dict]:
    """Reddit 这类：公开 Atom，不需要浏览器。"""
    url = site["search_url"].format(q=urllib.parse.quote(query or ""))
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        raise SanityError(f"{key}: HTTP {r.status_code}（限流或封禁，等一下再试）")
    root = etree.fromstring(r.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows = []
    for e in root.findall("a:entry", ns)[:limit]:
        title = "".join(e.findtext("a:title", default="", namespaces=ns))
        link = e.find("a:link", ns)
        body = e.findtext("a:content", default="", namespaces=ns)
        rows.append({
            "title": re.sub(r"\s+", " ", title).strip(),
            "url": link.get("href") if link is not None else "",
            "text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body or ""))[:400],
            "site": key,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    return rows


def _dig(obj, path: str):
    for k in (path or "").split("."):
        if not k:
            continue
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
        if obj is None:
            return None
    return obj


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _fetch_api(key: str, site: dict, url: str):
    """取一次 JSON。浏览器路径要先进站拿 cookie。"""
    if (site.get("via") or "http") == "browser":
        sess = Session(key, site)
        try:
            if site.get("login"):
                sess.check_login()
            sess.goto(site.get("base_url") or "https://" + url.split("/")[2], settle=2.0)
            res = sess.connect().fetch_json(url)
            if res["status"] != 200 or not res["json"]:
                raise SanityError(f"{key}: HTTP {res['status']}")
            return res["json"]
        finally:
            sess.close()
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    if r.status_code != 200:
        raise SanityError(f"{key}: HTTP {r.status_code}")
    return r.json()


def list_api(key: str, site: dict, query: str, limit: int) -> list[dict]:
    """通用 JSON 接口适配器。

    关键：HTTP 200 但空列表是**软失败**，不能当成"这个站没有内容"。
    重试一次再认，否则会把瞬时抽风报成空结果。
    """
    url = site["search_url"].format(q=urllib.parse.quote(query or ""), limit=limit)
    data, items = None, []
    for attempt in range(3):
        data = _fetch_api(key, site, url)
        items = _dig(data, site.get("items_path", "")) or []
        if items:
            break
        time.sleep(1.5 * (attempt + 1))     # 1.5s, 3s

    out = []
    for it in items:
        if site.get("item_path"):
            it = _dig(it, site["item_path"])
            if not it:
                continue
        row = {}
        for name, jkey in (site.get("fields") or {}).items():
            val = it.get(jkey, "") if isinstance(it, dict) else ""
            row[name] = _clean(str(val)) if site.get("strip_html") else str(val)
        # url_template 优先：接口给的 url 往往是 API 地址，不是能点开的页面
        if site.get("url_template"):
            try:
                row["url"] = site["url_template"].format(**row)
            except KeyError:
                row["url"] = str(it.get("url") or "") if isinstance(it, dict) else ""
        else:
            row["url"] = str(it.get("url") or it.get("link") or "") if isinstance(it, dict) else ""
        row.update(site=key, fetched_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if row.get("title") or row.get("url"):
            out.append(row)
    return out[:limit]


def list_ytdlp(key: str, site: dict, query: str, limit: int) -> list[dict]:
    """YouTube 搜索：yt-dlp 的 ytsearch，不需要 API key。"""
    from yt_dlp import YoutubeDL

    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    rows = []
    for e in (info.get("entries") or [])[:limit]:
        rows.append({
            "title": e.get("title") or "",
            "url": e.get("url") or f"https://www.youtube.com/watch?v={e.get('id','')}",
            "author": e.get("uploader") or e.get("channel") or "",
            "duration": e.get("duration"),
            "site": key,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    return rows


def cmd_list(args) -> int:
    _, sites = load_sites()
    site = sites.get(args.site)
    if not site:
        raise SystemExit(f"未知站点 {args.site}；可选：{', '.join(load_sites()[1])}")

    kind = site.get("type")
    fn = {"rss": list_rss, "api": list_api, "ytdlp": list_ytdlp}.get(kind, list_dom)
    try:
        rows = fn(args.site, site, args.query, args.limit)
    except (SanityError, LoginRequired) as exc:
        return _report_blocked(args.site, site, args.query, str(exc), args.json)

    store = Store()
    fresh = store.mark(rows, args.site)
    if args.new:
        rows = [r for r in rows if fresh.get(r["url"], True)]

    emit(rows, args.json, ["author", "likes", "company", "text"])
    if rows and not args.json:
        print(f"\n（{len(rows)} 条，其中新增 {sum(1 for r in rows if fresh.get(r.get('url'), True))} 条）")
    return 0


def cmd_crawl(args) -> int:
    """多关键词连跑，带合理性校验：换词后首条不变就报错。"""
    _, sites = load_sites()
    site = sites[args.site]
    kind = site.get("type")
    fn = {"rss": list_rss, "api": list_api, "ytdlp": list_ytdlp}.get(kind, list_dom)
    baseline: dict[str, str] = {}
    store = Store()
    all_rows: dict[str, dict] = {}

    for q in [x.strip() for x in args.queries.split(",") if x.strip()]:
        try:
            rows = fn(args.site, site, q, args.limit)
            sanity_check(args.site, q, rows, baseline)
        except SanityError as exc:
            plan = fallback_plan(args.site, site, q, None, str(exc))
            print(f"⚠️  {q}: {exc}", file=sys.stderr)
            print(f"   ↳ 改用 web_search: {plan['fallback']['queries'][0]!r}", file=sys.stderr)
            continue
        except LoginRequired as exc:
            print(f"🔒 {exc}", file=sys.stderr)
            return 2
        fresh = store.mark(rows, args.site)
        for r in rows:
            r["query"] = q
            if not args.new or fresh.get(r["url"], True):
                all_rows.setdefault(r["url"], r)
        print(f"  {q:24} +{len(rows)} 条", file=sys.stderr)

    emit(list(all_rows.values()), args.json, ["query", "author", "likes"])
    return 0


# --------------------------------------------------------------------------- 详情
def cmd_read(args) -> int:
    _, sites = load_sites()
    site = sites.get(args.site or "")
    if not site:
        raise SystemExit("需要 --site（用哪个站的选择器）")
    sess = Session(args.site, site)
    try:
        sess.goto(args.url, settle=4.0)
        ch = sess.connect()
        detail = site.get("detail") or {}
        title = ch.eval(f"(() => {{const e=document.querySelector({json.dumps(detail.get('title',''))});return e?e.innerText.trim():''}})()")
        body = ch.eval(f"(() => {{const e=document.querySelector({json.dumps(detail.get('body',''))});return e?e.innerText.trim():''}})()")
        if not body:
            body = ch.eval("(document.querySelector('main')||document.body).innerText.slice(0,4000)")
        out = {"url": args.url, "site": args.site, "title": title, "body": body[:6000]}
        if args.comments:
            out["comments"] = _comments(sess, site, args.comments, args.url)
        print(json.dumps(out, ensure_ascii=False, indent=1) if args.json else
              f"【{title}】\n\n{body[:3000]}\n\n--- 评论 {len(out.get('comments', []))} 条 ---\n" +
              "\n".join(f" • {c.get('user','')}：{c.get('text','')[:110]}" for c in out.get("comments", [])))
        return 0
    finally:
        sess.close()


def _comments(sess: Session, site: dict, limit: int, url: str) -> list[dict]:
    spec = site.get("comments") or {}
    ch = sess.connect()

    if spec.get("api"):                      # 知乎：页面内 fetch，同源带登录态
        m = re.search(r"/answer/(\d+)", url)
        if not m:
            return []
        out, offset = [], 0
        while len(out) < limit and offset < 200:
            api = spec["api"].format(answer_id=m.group(1), limit=20, offset=offset)
            res = ch.fetch_json(api)
            if res["status"] != 200 or not res["json"]:
                break
            batch = (res["json"].get("data") or [])
            if not batch:
                break
            for c in batch:
                member = (c.get("author") or {}).get("member") or {}
                out.append({"user": member.get("name", ""),
                            "text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c.get("content") or "")).strip()})
            offset += 20
        return out[:limit]

    # 小红书：评论懒加载，滚容器
    target = spec.get("scroll_target", "body")
    for _ in range(6):
        ch.eval(f"(() => {{const s=document.querySelector({json.dumps(target)});"
                f"if(s) s.scrollTop=s.scrollHeight; window.scrollTo(0,document.body.scrollHeight);}})()")
        time.sleep(1.0)
    js = r"""
    (() => {
      const C=%s, F=%s;
      return [...document.querySelectorAll(C)].map(el => {
        const r={}; for (const k in F){const n=el.querySelector(F[k]); r[k]=n?n.innerText.trim():'';}
        return r;
      }).filter(x=>x.text);
    })()
    """ % (json.dumps(spec.get("container", "")), json.dumps(spec.get("fields") or {}))
    return (ch.eval(js) or [])[:limit]


def cmd_read_many(args) -> int:
    _, sites = load_sites()
    site = sites[args.site]
    urls = [u.strip() for u in open(args.urls) if u.strip()]
    results: list[dict] = []

    def one(url: str) -> dict:
        try:
            sess = Session(args.site, site)
            sess.goto(url, settle=4.0)
            ch = sess.connect()
            d = site.get("detail") or {}
            body = ch.eval(f"(() => {{const e=document.querySelector({json.dumps(d.get('body',''))});"
                           f"return e?e.innerText.trim():''}})()")
            sess.close()
            return {"url": url, "body": body[:2000]}
        except Exception as exc:                     # noqa: BLE001
            return {"url": url, "error": str(exc)[:120]}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(one, urls):
            results.append(r)
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


def fallback_plan(site_key: str, site: dict, query: str, rows: list[dict] | None, reason: str) -> dict:
    """被阻断时给三层替代路径。

    ① 找镜像 / 免登录入口 —— 同一份内容，换一条能通的路（先试这个，试一次就够）
    ② 换站                —— 同层级替代，问题一样能答
    ③ 换搜索引擎          —— 找转载/摘要（有损，但比没有强）
    """
    rows = rows or []
    title = next((r.get("title") for r in rows if r.get("title")), "") or ""
    name = site.get("name", site_key)
    m = re.match(r"https?://([^/]+)", site.get("search_url", ""))
    domain = m.group(1) if m else ""

    # 0 交回给搜索：找「内容」，不是找「这个站的门」
    hand_q: list[str] = []
    if title:
        hand_q.append(f'"{title.replace(chr(34), "")}"')
    if query:
        hand_q.append(query)
        hand_q.append(f"{query} 知乎")
        if domain:
            hand_q.append(f"{query} site:{domain}")

    # ① 镜像：站点自带提示优先，否则用通用模板
    mirror = list(site.get("mirror_hint") or [])
    if query:
        mirror.append(f"{name} 镜像站 可用")
        mirror.append(f"{name} 免登录 访问")
    if domain and "." in domain:
        mirror.append(f"{domain} mirror alternative")

    # ② 换站
    others = [x for x in ("zhihu", "xhs", "csdn", "tieba", "weibo", "youtube") if x != site_key][:2]
    switch = [f'ra.py list {x} "{query}" --limit 8' for x in others] if query else []

    # ③ 找转载
    copy_q: list[str] = []
    if title:
        t = title.replace('"', "")
        copy_q.append(f'"{t}"')
        copy_q.append(f"{t} 转载 OR 镜像 OR 全文")
    if query:
        copy_q.append(f"{query} site:{domain}" if domain else f"{query} 全文")
        copy_q.append(f"{query} 知乎")

    def uniq(xs):
        seen, out = set(), []
        for x in xs:
            if x and x not in seen:
                seen.add(x); out.append(x)
        return out

    return {
        "ok": False,
        "blocked_at": site_key,
        "site_name": name,
        "reason": reason,
        "fallback": {
            "note": "站内被阻断。控制权交回给调用方：先用你自己的搜索，再回来读。",
            # 第一步永远是「交回给 AI 的搜索」——这是它的强项，不是我的
            "0_handoff": {
                "to": "your_web_search",
                "why": "站内搜不了，不代表这个问题搜不到。搜索是调用方的强项。",
                "queries": uniq(hand_q)[:4],
                "then": f"ra.py read <搜到的URL> --site {site_key}",
                "then_note": "搜到链接不等于读到内容。把链接带回来，我读正文和评论。",
            },
            "1_find_mirror": {"queries": [q for q in uniq(mirror) if q not in set(hand_q)][:4]},
            "2_switch_site": {"commands": switch},
            "3_find_copy": {"queries": uniq(copy_q)[:4]},
        },
    }


def _report_blocked(site_key: str, site: dict, query: str, reason: str, as_json: bool) -> int:
    plan = fallback_plan(site_key, site, query, None, reason)
    if as_json:
        print(json.dumps(plan, ensure_ascii=False, indent=1))
        return 3

    fb = plan["fallback"]
    h = fb["0_handoff"]
    print(f"⚠️  {site.get('name', site_key)}: {reason}", file=sys.stderr)
    print("\n↩️  交回给你。站内搜不了，不代表这个问题搜不到。", file=sys.stderr)
    print("    用你自己的搜索跑：", file=sys.stderr)
    for q in h["queries"]:
        print(f'      web_search "{q}"', file=sys.stderr)
    print(f"    搜到链接再回来：{h['then']}", file=sys.stderr)
    print("    搜到 ≠ 读到。链接给我，正文和评论我读。", file=sys.stderr)
    print("\n    搜索也不给的话，再按 ①→③ 走：", file=sys.stderr)
    print("   ① 找镜像 / 免登录入口", file=sys.stderr)
    for q in fb["1_find_mirror"]["queries"]:
        print(f'      web_search "{q}"', file=sys.stderr)
    print("   ② 换站", file=sys.stderr)
    for c in fb["2_switch_site"]["commands"]:
        print(f"      {c}", file=sys.stderr)
    print("   ③ 找转载", file=sys.stderr)
    for q in fb["3_find_copy"]["queries"]:
        print(f'      web_search "{q}"', file=sys.stderr)
    return 3


def cmd_suggest(args) -> int:
    """把一句口语问题，改写成各站能搜到的查询词。"""
    q = args.question
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries.yaml"), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    scores = []
    for key, it in cfg["intents"].items():
        hit = sum(1 for kw in it.get("keywords", []) if kw.lower() in q.lower())
        if hit:
            scores.append((hit, key, it))
    if not scores:
        scores = [(0, "school", cfg["intents"]["school"])]
    scores.sort(reverse=True)
    _, key, it = scores[0]

    # 实体抽取：保留技术词/专有名词，只删口语虚词（意图词本身是内容，不能删）
    FILLER = ["会不会", "能不能", "要不要", "值不值", "该不该", "有没有", "是不是",
              "怎么", "如何", "哪个", "还是", "请问", "帮我", "看看", "了解",
              "大一", "大二", "大三", "大四", "新生",
              "想", "要", "找", "求", "学", "做", "去", "是", "的", "吗",
              "呢", "吧", "啊", "和", "与", "我", "你"]
    zh = q
    for kw in sorted(FILLER, key=len, reverse=True):
        zh = zh.replace(kw, " ")
    zh = re.sub(r"[，。,.、!?？\s]+", " ", zh).strip()
    tokens = [t for t in zh.split() if t]
    # 英文/技术词单独抽出来，避免被中文处理吃掉
    eng = re.findall(r"[A-Za-z][A-Za-z0-9+.#&/-]{0,}", q)
    seen, merged = set(), []
    for t in tokens + eng:
        if t.lower() not in seen:
            seen.add(t.lower())
            merged.append(t)
    topic = " ".join(merged).strip() or q

    # 站内别名：英文站用英文校名/公司名，中文站保留中文
    # 站内别名：中文实体在英文站要换成英文写法。
    # 需要学校/公司别名时在这里加一条即可，例如 "某公司": {"reddit": "SomeCorp"}。
    ALIAS = {
        "英特尔": {"reddit": "Intel"},
        "英伟达": {"reddit": "NVIDIA"},
        "台积电": {"reddit": "TSMC"},
        "高通": {"reddit": "Qualcomm"},
        "三星": {"reddit": "Samsung"},
    }

    def localize(site: str, text: str) -> str:
        for zh, mapping in ALIAS.items():
            if zh in text and site in mapping:
                text = text.replace(zh, mapping[site])
        if site in ("reddit", "youtube") and re.search(r"[\u4e00-\u9fff]", text):
            # 英文站：抽英文词；抽不到就返回空，交给上层跳过这个站
            eng = re.findall(r"[A-Za-z][A-Za-z0-9+.#\-]{1,}", text)
            return " ".join(eng) if eng else ""
        return text

    plan = {}
    for site, tpls in (it.get("templates") or {}).items():
        local = localize(site, topic)
        if not local:
            continue          # 英文站拿不到英文词，就别硬凑中文查询
        def uniq(qs: str) -> str:
            seen, out = set(), []
            for w in qs.split():
                if w not in seen:
                    seen.add(w); out.append(w)
            return " ".join(out)
        plan[site] = [uniq(t.replace("{t}", local)) for t in tpls]
    if args.json:
        print(json.dumps({"intent": key, "topic": topic, "plan": plan},
                         ensure_ascii=False, indent=1))
        return 0
    for site, qs in plan.items():
        print(f"[{site}]")
        for x in qs:
            print(f"  ra.py list {site} \"{x}\" --limit 8")
        print()
    return 0


def cmd_db(args) -> int:
    store = Store()
    rows = store.stats()
    if not rows:
        print("库里还没有记录")
        return 0
    print("site        条数")
    for site, n in rows:
        print(f"{site:10} {n:5}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    L = sub.add_parser("list")
    L.add_argument("site")
    L.add_argument("query", nargs="?", default="")
    L.add_argument("--limit", type=int, default=10)
    L.add_argument("--json", action="store_true")
    L.add_argument("--new", action="store_true", help="只输出没见过的新条目")
    L.set_defaults(fn=cmd_list)

    C = sub.add_parser("crawl")
    C.add_argument("site")
    C.add_argument("--queries", required=True, help="逗号分隔")
    C.add_argument("--limit", type=int, default=8)
    C.add_argument("--json", action="store_true")
    C.add_argument("--new", action="store_true")
    C.set_defaults(fn=cmd_crawl)

    R = sub.add_parser("read")
    R.add_argument("url")
    R.add_argument("--site", default="")
    R.add_argument("--comments", type=int, default=0)
    R.add_argument("--json", action="store_true")
    R.set_defaults(fn=cmd_read)

    M = sub.add_parser("read-many")
    M.add_argument("--site", required=True)
    M.add_argument("--urls", required=True)
    M.add_argument("--workers", type=int, default=3)
    M.set_defaults(fn=cmd_read_many)

    S = sub.add_parser("suggest", help="口语问题 → 各站查询词")
    S.add_argument("question")
    S.add_argument("--json", action="store_true")
    S.set_defaults(fn=cmd_suggest)

    D = sub.add_parser("db")
    D.add_argument("action", choices=["stats"])
    D.set_defaults(fn=cmd_db)

    ns = ap.parse_args()
    try:
        return ns.fn(ns)
    except LoginRequired as exc:
        print(f"🔒 {exc}", file=sys.stderr)
        return 2
    except SanityError as exc:
        print(f"⚠️  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
