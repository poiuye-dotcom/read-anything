"""B 站读取：视频信息 / 弹幕 / 评论 /（字幕，需要登录）。

关键就一件事：先拿一个 buvid3 cookie。没有它，B 站 API 会返回 412 或 HTML 错误页，
有了它，`view` / 弹幕 / 评论 三个接口都通，不需要登录。

    python3 bili.py read BV1ukno6YEay
    python3 bili.py read "https://www.bilibili.com/video/BV1ukno6YEay" --danmaku 200 --comments 30
    python3 bili.py search "嵌入式 就业"        # 搜索走 agent-reach（wbi 签名由它处理）
    python3 bili.py read BV1ukno6YEay --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zlib
from urllib.parse import urlencode

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
HEAD = {"User-Agent": UA, "Referer": "https://www.bilibili.com"}

_session = requests.Session()
_session.headers.update(HEAD)


def buvid() -> str:
    """取 buvid3。没有它，多数接口返回 412。"""
    r = _session.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=15)
    return r.json()["data"]["b_3"]


def ensure_cookie() -> None:
    if "buvid3" not in _session.cookies:
        _session.cookies.set("buvid3", buvid(), domain=".bilibili.com")


def api(path: str, **params):
    ensure_cookie()
    r = _session.get(f"https://api.bilibili.com{path}", params=params, timeout=20)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"API {path} 返回 code={data.get('code')}: {data.get('message')}")
    return data.get("data")


def parse_bvid(target: str) -> str:
    m = re.search(r"(BV[0-9A-Za-z]{10})", target)
    if not m:
        raise SystemExit("没找到 BV 号（支持 BV 号或完整视频链接）")
    return m.group(1)


def video_info(bvid: str) -> dict:
    return api("/x/web-interface/view", bvid=bvid)


def danmaku(cid: int, limit: int = 200) -> list[dict]:
    """弹幕：comment.bilibili.com/{cid}.xml。返回按时间排序的前 limit 条。"""
    ensure_cookie()
    r = _session.get(f"https://comment.bilibili.com/{cid}.xml", timeout=20)
    raw = r.content
    txt = None
    for wbits in (-zlib.MAX_WBITS, zlib.MAX_WBITS | 16):  # 可能是裸 deflate / gzip
        try:
            txt = zlib.decompress(raw, wbits).decode("utf-8", "ignore")
            break
        except Exception:
            continue
    if txt is None:
        txt = raw.decode("utf-8", "ignore")

    out = []
    for attr, text in re.findall(r'<d p="([^"]*)"[^>]*>(.*?)</d>', txt):
        parts = attr.split(",")
        out.append({
            "time": float(parts[0]) if parts and parts[0] else 0.0,
            "mode": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
            "text": text,
        })
    out.sort(key=lambda d: d["time"])
    return out[:limit]


def comments(aid: int, limit: int = 30) -> list[dict]:
    """评论：/x/v2/reply（老接口，带 buvid3 即可用）。"""
    out, page = [], 1
    while len(out) < limit and page <= 5:
        data = api("/x/v2/reply", type=1, oid=aid, sort=2, ps=20, pn=page)
        replies = (data or {}).get("replies") or []
        if not replies:
            break
        for r in replies:
            out.append({
                "user": (r.get("member") or {}).get("uname", ""),
                "like": r.get("like", 0),
                "text": (r.get("content") or {}).get("message", ""),
            })
        page += 1
    return out[:limit]


def subtitles(aid: int, cid: int) -> tuple[list[dict], str]:
    """字幕：需要登录。没登录时返回 ([], 原因)。"""
    try:
        data = api("/x/player/v2", aid=aid, cid=cid)
    except Exception as exc:
        return [], f"取不到播放器信息：{exc}"
    subs = ((data or {}).get("subtitle") or {}).get("subtitles") or []
    if not subs:
        return [], "没有字幕（或未登录，B站对未登录用户不下发字幕列表）"
    return [{"lan": s.get("lan"), "url": s.get("subtitle_url")} for s in subs], ""


def search(keyword: str, limit: int = 5) -> int:
    """搜索交给 agent-reach（它处理 wbi 签名）。"""
    try:
        proc = subprocess.run(
            ["agent-reach", "bilibili", "search", keyword, "--limit", str(limit)],
            capture_output=True, text=True, timeout=120,
        )
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:
        print(f"搜索依赖 agent-reach（未安装或失败）：{exc}", file=sys.stderr)
        return 1
    if not data.get("ok"):
        print(f"搜索失败：{(data.get('error') or {}).get('message')}", file=sys.stderr)
        return 1
    for it in data.get("items") or []:
        print(f"- {it.get('title', '')[:70]}\n  {it.get('url', '')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("read")
    r.add_argument("target", help="BV 号或视频链接")
    r.add_argument("--danmaku", type=int, default=50)
    r.add_argument("--comments", type=int, default=20)
    r.add_argument("--json", action="store_true")

    s = sub.add_parser("search")
    s.add_argument("keyword")
    s.add_argument("--limit", type=int, default=5)

    ns = ap.parse_args()
    if ns.cmd == "search":
        return search(ns.keyword, ns.limit)

    bvid = parse_bvid(ns.target)
    info = video_info(bvid)
    cid = info["pages"][0]["cid"]
    aid = info["aid"]

    dm = danmaku(cid, ns.danmaku)
    cm = comments(aid, ns.comments)
    subs, sub_note = subtitles(aid, cid)

    if ns.json:
        print(json.dumps({
            "bvid": bvid, "aid": aid, "cid": cid,
            "title": info["title"], "owner": info["owner"]["name"],
            "duration": info["duration"], "desc": info.get("desc", ""),
            "stat": info.get("stat", {}), "danmaku": dm,
            "comments": cm, "subtitles": subs, "subtitle_note": sub_note,
        }, ensure_ascii=False, indent=1))
        return 0

    print(f"【{info['title']}】")
    print(f"UP：{info['owner']['name']} ｜ 时长 {info['duration']}s ｜ "
          f"播放 {info['stat']['view']} ｜ 弹幕 {info['stat']['danmaku']} ｜ 评论 {info['stat']['reply']}")
    if info.get("desc"):
        print(f"简介：{info['desc'][:300]}")
    print(f"\n--- 弹幕（前 {len(dm)} 条，按时间）---")
    for d in dm:
        print(f"  {int(d['time'] // 60):02d}:{int(d['time'] % 60):02d}  {d['text'][:60]}")
    print(f"\n--- 热评（前 {len(cm)} 条）---")
    for c in cm:
        print(f"  [{c['like']:>4}] {c['user']}：{c['text'][:80]}")
    print(f"\n--- 字幕 ---\n  {sub_note or '可用：' + str(subs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
