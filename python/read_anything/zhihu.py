"""知乎读取：搜索页 / 问题页回答。走 DOM，登录态来自 login.py。

    python3 zhihu.py search "芯片 就业" --limit 8
    python3 zhihu.py read "https://www.zhihu.com/question/2242839464" --answers 3
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse

from . import browser


def _open(url: str, settle: float = 3.0):
    ch = browser.attach_any()
    ch.call("Page.navigate", {"url": url})
    for _ in range(50):
        if ch.eval("document.readyState") == "complete":
            break
        time.sleep(0.4)
    time.sleep(settle)
    return ch


JS_SEARCH = r"""
(() => {
  const out = [];
  for (const card of document.querySelectorAll('.SearchResult-Card')) {
    const h = card.querySelector('h2, .ContentItem-title');
    const rich = card.querySelector('.RichText');
    const link = card.querySelector("a[href*='/question/']");
    const meta = card.innerText.split('\n').filter(s => /赞同|评论/.test(s)).join(' ');
    out.push({
      title: h ? h.innerText.trim() : '',
      excerpt: rich ? rich.innerText.replace(/\n+/g, ' ').trim().slice(0, 200) : '',
      meta: meta.slice(0, 80),
      url: link ? link.href.split('?')[0] : ''
    });
  }
  return out.filter(x => x.title);
})()
"""

JS_QUESTION = r"""
(() => {
  const title = (document.querySelector('.QuestionHeader-title') || {}).innerText || document.title;
  const answers = [...document.querySelectorAll('.RichText')]
    .map(e => e.innerText.trim())
    .filter(s => s.length > 80)
    .slice(0, 8);
  return { title: title.trim(), answers };
})()
"""


def search(keyword: str, limit: int) -> list[dict]:
    ch = _open("https://www.zhihu.com/search?type=content&q=" + urllib.parse.quote(keyword))
    rows = ch.eval(JS_SEARCH) or []
    ch.close()
    return rows[:limit]


def _answer_id(url: str, ch) -> str:
    m = re.search(r"/answer/(\d+)", url)
    if m:
        return m.group(1)
    # 问题页：取页面上第一个回答的 id
    href = ch.eval("(()=>{const a=document.querySelector(\"a[href*='/answer/']\");return a?a.href:''})()") or ""
    m = re.search(r"/answer/(\d+)", href)
    return m.group(1) if m else ""


def _comments(ch, answer_id: str, limit: int) -> list[dict]:
    """评论走页面内 fetch 调 api/v4 —— 同源、带登录态，不用点开折叠面板。"""
    out, offset = [], 0
    while len(out) < limit and offset < 200:
        res = ch.fetch_json(
            f"https://www.zhihu.com/api/v4/answers/{answer_id}/comments"
            f"?limit=20&offset={offset}&order=normal"
        )
        if res["status"] != 200 or not res["json"]:
            break
        batch = res["json"].get("data") or []
        if not batch:
            break
        for c in batch:
            member = (c.get("author") or {}).get("member") or {}
            body = re.sub(r"<[^>]+>", " ", c.get("content") or "")
            out.append({
                "user": member.get("name", ""),
                "text": re.sub(r"\s+", " ", body).strip(),
                "likes": c.get("vote_count") or 0,
            })
        offset += 20
    return out[:limit]


def read(url: str, n: int, comment_limit: int = 0) -> dict:
    ch = _open(url, settle=4.0)
    ch.eval("window.scrollBy(0, window.innerHeight)")
    time.sleep(1.5)
    data = ch.eval(JS_QUESTION) or {}
    data["answers"] = (data.get("answers") or [])[:n]
    if comment_limit:
        aid = _answer_id(url, ch)
        data["comments"] = _comments(ch, aid, comment_limit) if aid else []
    ch.close()
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("keyword")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--json", action="store_true")

    r = sub.add_parser("read")
    r.add_argument("url")
    r.add_argument("--answers", type=int, default=3)
    r.add_argument("--comments", type=int, default=0, help="抓第 1 个回答的评论条数")
    r.add_argument("--json", action="store_true")

    ns = ap.parse_args()

    if ns.cmd == "search":
        rows = search(ns.keyword, ns.limit)
        if ns.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        print(f"「{ns.keyword}」共 {len(rows)} 条\n")
        for i, x in enumerate(rows, 1):
            print(f"{i:2}. {x['title'][:64]}")
            if x["meta"]:
                print(f"    {x['meta']}")
            print(f"    {x['excerpt'][:110]}")
            print(f"    {x['url']}")
        return 0

    d = read(ns.url, ns.answers, ns.comments)
    if ns.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    print(f"【{d.get('title','')[:70]}】\n")
    for i, a in enumerate(d.get("answers") or [], 1):
        print(f"--- 回答 {i} ---")
        print(a[:900])
        print()
    if d.get("comments"):
        print(f"--- 评论 {len(d['comments'])} 条 ---")
        for c in d["comments"]:
            print(f" • [{c['likes']}] {c['user']}：{c['text'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
