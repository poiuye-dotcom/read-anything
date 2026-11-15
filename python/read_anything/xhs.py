"""小红书读取：搜索页 / 笔记详情。走 DOM，不碰 x-s 签名。

前提：先在 login.py 里登录过（登录态在 ~/.read-anything/{browser}-profile）。
注意：国际网络下小红书会跳到 rednote.com，cookie 也在那个域名下。

    python3 xhs.py search "芯片 就业" --limit 10
    python3 xhs.py read "https://www.rednote.com/search_result/<id>?xsec_token=..." --comments 20
    python3 xhs.py search "..." --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse

from . import browser

SEARCH_URL = "https://www.rednote.com/search_result?keyword={kw}&source=web_search_result_notes"


def _open(url: str, settle: float = 3.0):
    ch = browser.attach_any()
    ch.call("Page.navigate", {"url": url})
    for _ in range(40):
        if ch.eval("document.readyState") == "complete":
            break
        time.sleep(0.4)
    time.sleep(settle)
    return ch


def _scroll(ch, times: int, pause: float = 1.2) -> None:
    for _ in range(times):
        ch.eval("window.scrollBy(0, window.innerHeight * 0.9)")
        time.sleep(pause)


JS_CARDS = r"""
(() => {
  const out = [];
  for (const c of document.querySelectorAll('section.note-item')) {
    const pick = (sel) => { const e = c.querySelector(sel); return e ? e.innerText.trim() : ''; };
    const cover = c.querySelector('a.cover') || c.querySelector('a[href*="xsec_token"]');
    out.push({
      title: pick('.title'),
      author: pick('.name'),
      likes: pick('.count'),
      url: cover ? cover.href : ''
    });
  }
  return out;
})()
"""


def search(keyword: str, limit: int, scrolls: int) -> list[dict]:
    ch = _open(SEARCH_URL.format(kw=urllib.parse.quote(keyword)))
    seen: dict[str, dict] = {}
    for _ in range(scrolls + 1):
        for c in ch.eval(JS_CARDS) or []:
            if c["title"] and c["url"] and c["url"] not in seen:
                seen[c["url"]] = c
        if len(seen) >= limit:
            break
        _scroll(ch, 1)
    ch.close()
    return list(seen.values())[:limit]


JS_DETAIL = r"""
(() => {
  const t = (sel) => { const e = document.querySelector(sel); return e ? e.innerText.trim() : ''; };
  const comments = [...document.querySelectorAll('.comment-item')].map(e => ({
    user: (e.querySelector('.name') || {}).innerText || '',
    text: (e.querySelector('.content') || {}).innerText || '',
    like: (e.querySelector('.like .count') || {}).innerText || ''
  })).filter(c => c.text);
  return {
    title: t('#detail-title') || t('.note-content .title') || t('title'),
    desc:  t('#detail-desc')  || t('.note-content .desc') || t('.desc'),
    author: t('.author-wrapper .name') || t('.username'),
    likes: t('.like-wrapper .count') || t('.interact-container .count'),
    comments
  };
})()
"""


def _scroll_comments(ch, times: int, pause: float = 1.0) -> None:
    """评论区是懒加载的：滚 .note-scroller 才会继续加载。"""
    for _ in range(times):
        ch.eval("""(() => {
          const s = document.querySelector('.note-scroller') || document.querySelector('.note-container');
          if (s) s.scrollTop = s.scrollHeight;
          window.scrollTo(0, document.body.scrollHeight);
        })()""")
        time.sleep(pause)


def read(url: str, comment_limit: int, scrolls: int = 6) -> dict:
    ch = _open(url, settle=4.0)
    _scroll(ch, 1)
    if comment_limit:
        _scroll_comments(ch, scrolls)
    data = ch.eval(JS_DETAIL) or {}
    data["comments"] = (data.get("comments") or [])[:comment_limit]
    ch.close()
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("keyword")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--scrolls", type=int, default=3)
    s.add_argument("--json", action="store_true")

    r = sub.add_parser("read")
    r.add_argument("url")
    r.add_argument("--comments", type=int, default=20)
    r.add_argument("--scrolls", type=int, default=6, help="评论区滚动次数（加载更多）")
    r.add_argument("--json", action="store_true")

    ns = ap.parse_args()

    if ns.cmd == "search":
        rows = search(ns.keyword, ns.limit, ns.scrolls)
        if ns.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            print(f"「{ns.keyword}」共 {len(rows)} 条\n")
            for i, r in enumerate(rows, 1):
                print(f"{i:2}. {r['title'][:60]}")
                print(f"    {r['author']} ｜ ♥ {r['likes']}")
                print(f"    {r['url'][:100]}")
        return 0

    d = read(ns.url, ns.comments, ns.scrolls)
    if ns.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
        return 0
    print(f"【{d.get('title','')[:60]}】")
    print(f"{d.get('author','')} ｜ ♥ {d.get('likes','')}\n")
    print((d.get("desc") or "(没取到正文)")[:1500])
    if d.get("comments"):
        print(f"\n--- 评论 {len(d['comments'])} 条 ---")
        for c in d["comments"]:
            print(f" • [{c.get('like','')}] {c.get('user','')}：{c.get('text','')[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
