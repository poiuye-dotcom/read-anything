"""开一个有头 Chrome，让你本人登录小红书 / 知乎，然后保持登录态。

登录态存在专用 profile ~/.read-anything/chrome-profile，和你日常浏览器隔离。
登录成功后 Chrome 不会关闭（脚本退出只是断开 websocket），可以继续从里面取数据。

    python3 login.py xhs      # 小红书，扫码
    python3 login.py zhihu    # 知乎，扫码或账号密码
    python3 login.py xhs --check   # 只检查，不打开窗口
"""

from __future__ import annotations

import argparse
import sys
import time

from . import browser

SITES = {
    "xhs": {
        # 国际网络下小红书会跳到 rednote.com，cookie 也落在那；两个域名都要看
        "url": "https://www.rednote.com",
        "urls": ["https://www.rednote.com", "https://www.xiaohongshu.com"],
        "cookie": "web_session",
        "name": "小红书",
    },
    "zhihu": {
        "url": "https://www.zhihu.com",
        "urls": ["https://www.zhihu.com"],
        "cookie": "z_c0",
        "name": "知乎",
    },
    "x": {
        "url": "https://x.com",
        "urls": ["https://x.com"],
        "cookie": "auth_token",
        "name": "X / Twitter",
    },
    "handshake": {
        # 校内版在子域名上；未登录访问 /stu/postings 会被踢到 /login
        "url": "https://example.joinhandshake.com/",
        "check_url": "https://example.joinhandshake.com/stu/postings",
        "redirect_markers": ["/login", "/access", "signin"],
        "name": "Handshake",
    },
}


def cookies_for(ch, url: str) -> dict[str, str]:
    ch.call("Network.enable")
    res = ch.call("Network.getCookies", {"urls": [url, url + "/"]})
    return {c["name"]: c["value"] for c in res.get("cookies", [])}


def logged_in(ch, site: dict) -> bool:
    """两种判据：有 cookie 名的查 cookie；没有的看受保护页面会不会被踢走。"""
    if site.get("check_url"):
        ch.call("Page.navigate", {"url": site["check_url"]})
        landed = ""
        for _ in range(50):
            landed = ch.eval("location.href") or ""
            if ch.eval("document.readyState") == "complete":
                break
            time.sleep(0.3)
        time.sleep(0.8)
        landed = ch.eval("location.href") or landed
        if any(m in landed for m in site.get("redirect_markers", [])):
            return False
        # 登录后可能落在 /stu/postings、/job-search、/edu/... 各种路径，
        # 只要没被踢去登录页就算成功。
        return True

    for url in site.get("urls", [site["url"]]):
        if site["cookie"] in cookies_for(ch, url):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=list(SITES))
    ap.add_argument("--check", action="store_true", help="只检查登录态，不打开窗口")
    ap.add_argument("--timeout", type=int, default=300, help="等待登录的秒数")
    args = ap.parse_args()

    site = SITES[args.site]

    if args.check:
        ch = browser.attach_any()
        ok = logged_in(ch, site)
        print(f"{site['name']} 登录态：{'✅ 已登录' if ok else '❌ 未登录'}")
        return 0 if ok else 1

    ch = browser.launch(headless=False, url=site["url"])
    print(f"已打开 Chrome → {site['url']}")
    print(f"请在窗口里登录【{site['name']}】（扫码即可），脚本会每 3 秒检查一次。")

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if logged_in(ch, site):
            print(f"✅ 检测到 {site['name']} 登录成功（cookie: {site['cookie']}）")
            print("窗口先别关——接下来要从这个窗口里取数据。")
            return 0
        time.sleep(3)
        print("  等待登录…")

    print("⏱ 超时。登录窗口保留着，重新跑一次或手动登录后再 --check。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
