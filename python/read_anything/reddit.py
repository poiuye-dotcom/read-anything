"""Reddit 读取：搜索走 Brave 的 HTML，正文走公开的 .rss（Atom），都不需要登录。

为什么不用 Agent Reach：它的 reddit 渠道在本机上是 403，
而 Reddit 的 .rss 是公开订阅源，反爬比网页宽松得多。

    python3 reddit.py search "embedded career 2026" --limit 5
    python3 reddit.py read "https://www.reddit.com/r/chipdesign/comments/1qag9tf/openings_for_entry_level_designers/"
    python3 reddit.py read 1qag9tf --sub chipdesign
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
HEAD = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

_s = requests.Session()
_s.headers.update(HEAD)


def _text(fragment: str) -> str:
    # .rss 里的评论是「转义过的 HTML」，所以先去标签、再反转义、再去一次标签
    t = re.sub(r"<[^>]+>", " ", fragment or "")
    t = html.unescape(t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def search(query: str, limit: int = 8, subreddit: str = "") -> int:
    """搜索：优先用 Reddit 自己的 search.rss（官方订阅源），Brave 作备用。

    两者都可能 429——本机的出口被限流是常态，等 10–15 分钟再试。
    """
    urls: list[str] = []

    # 1) Reddit 官方 search.rss
    try:
        r = _s.get(
            "https://www.reddit.com/search.rss",
            params={"q": query, "sort": "relevance", "t": "all", "limit": limit},
            timeout=25,
        )
        if r.status_code == 200:
            for href in re.findall(r'<link href="([^"]+)"', r.text):
                if "/comments/" in href:
                    urls.append(href.split("?")[0])
        else:
            print(f"  reddit search.rss → HTTP {r.status_code}", file=sys.stderr)
    except Exception as exc:
        print(f"  reddit search.rss → {exc}", file=sys.stderr)

    # 2) 备用：Brave 的 site: 查询
    if not urls:
        try:
            q = f"site:reddit.com {('r/' + subreddit + ' ') if subreddit else ''}{query}"
            r = _s.get("https://search.brave.com/search", params={"q": q}, timeout=25)
            for u in re.findall(r"https://www\.reddit\.com/r/[^\"&<\s]+?/comments/[^\"&<\s]+", r.text):
                urls.append(u.split("?")[0].rstrip("\\"))
        except Exception as exc:
            print(f"  brave → {exc}", file=sys.stderr)

    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)

    if not out:
        print("两个源都没给结果（多半是 429 限流）。", file=sys.stderr)
        print("对策：等 10–15 分钟；或直接 `reddit.py read <线程URL>`，单篇读取不受影响。",
              file=sys.stderr)
        return 1
    for u in out[:limit]:
        print(u)
    return 0


def read(target: str, limit: int = 15, sub: str = "") -> int:
    """.rss 是公开 Atom：第 1 条是原帖，后面是评论。"""
    if target.startswith("http"):
        url = target.split("?")[0].rstrip("/") + "/.rss"
    else:
        if not sub:
            raise SystemExit("给 post id 时需要 --sub（例如 --sub chipdesign）")
        url = f"https://www.reddit.com/r/{sub}/comments/{target}/.rss"

    r = _s.get(url, timeout=30)
    if r.status_code == 429:
        print("被限流（429），等 1–2 分钟再试", file=sys.stderr)
        return 1
    if r.status_code != 200:
        print(f"HTTP {r.status_code}", file=sys.stderr)
        return 1

    entries = re.findall(r"<entry>(.*?)</entry>", r.text, re.S)
    if not entries:
        print("没有内容", file=sys.stderr)
        return 1

    def field(e: str, tag: str) -> str:
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", e, re.S)
        return _text(m.group(1)) if m else ""

    post = entries[0]
    print(f"【{field(post, 'title')}】\n")
    body = field(post, "content")
    print(body[:1200] or "(无正文)")
    print(f"\n--- 评论（{min(len(entries) - 1, limit)} 条）---")
    for e in entries[1 : limit + 1]:
        who = re.search(r"<name>(.*?)</name>", e, re.S)
        author = who.group(1).replace("/u/", "").strip() if who else "?"
        txt = field(e, "content")
        print(f"\n[{author}]\n{txt[:500]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--sub", default="")

    r = sub.add_parser("read")
    r.add_argument("target", help="线程 URL 或 post id")
    r.add_argument("--limit", type=int, default=15)
    r.add_argument("--sub", default="")

    ns = ap.parse_args()
    if ns.cmd == "search":
        return search(ns.query, ns.limit, ns.sub)
    return read(ns.target, ns.limit, ns.sub)


if __name__ == "__main__":
    raise SystemExit(main())
