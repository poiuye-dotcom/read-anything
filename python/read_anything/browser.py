"""Launch or attach to a Chrome instance that keeps its logins.

The point of a dedicated profile: you log into Handshake/LinkedIn once, in a
window this tool opened, and those cookies stay in ~/.read-anything/chrome-profile.
Your everyday Chrome is never touched and never has to be restarted.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time

from .cdp import CDPError, Chrome

# 每个浏览器用不同端口，避免「Edge 想启动，但 9222 被上一个 Chrome 占着」
PORT_BY_BROWSER = {"chrome": 9222, "edge": 9223, "chromium": 9224}
PORT = 9222

# 三个浏览器都是 Chromium 内核，CDP 完全一样，可以互换。
# 用环境变量选：JOBHUNT_BROWSER=edge
BINARIES = {
    "chrome": {
        "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "PATH": ["google-chrome", "google-chrome-stable"],
    },
    "edge": {
        "Darwin": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        "PATH": ["microsoft-edge", "microsoft-edge-stable"],
    },
    "chromium": {
        "Darwin": ["/Applications/Chromium.app/Contents/MacOS/Chromium"],
        "PATH": ["chromium", "chromium-browser"],
    },
}

CONFIG_FILE = os.path.expanduser("~/.read-anything/browser.txt")


def _configured_browser() -> str:
    """优先级：环境变量 > 配置文件 > chrome。"""
    env = os.environ.get("JOBHUNT_BROWSER")
    if env:
        return env.strip().lower()
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            name = fh.read().strip().lower()
        if name in BINARIES:
            return name
    except Exception:
        pass
    return "chrome"


BROWSER = _configured_browser()
PROFILE_DIR = os.path.expanduser(f"~/.read-anything/{BROWSER}-profile")


def resolve_browser(name: str | None = None) -> str:
    return (name or BROWSER or "chrome").strip().lower()


def chrome_binary(name: str | None = None) -> str:
    """找到指定浏览器的可执行文件；找不到就报出候选路径。"""
    name = resolve_browser(name)
    spec = BINARIES.get(name)
    if not spec:
        raise RuntimeError(f"不认识的浏览器 '{name}'，可选：{', '.join(BINARIES)}")

    if platform.system() == "Darwin":
        for path in spec["Darwin"]:
            if os.path.exists(path):
                return path

    from shutil import which

    for candidate in spec["PATH"]:
        path = which(candidate)
        if path:
            return path

    wanted = spec["Darwin"][0]
    raise RuntimeError(f"没找到 {name}（找过 {wanted} 和 PATH 里的 {spec['PATH']}）")


def is_running(port: int = PORT) -> bool:
    try:
        Chrome(port=port, timeout=3).version()
        return True
    except Exception:
        return False


def attach(port: int = PORT) -> Chrome:
    """Attach to the first page target; open one if the browser has none."""
    chrome = Chrome(port=port)
    chrome.wait_ready(tries=8)
    if not chrome.pages():
        # 无头实例可能把最后一个标签关掉了：直接开一个
        chrome.new_tab("about:blank")
        time.sleep(0.3)
    return chrome.connect()


def attach_any() -> "Chrome":
    """连到任意一个还活着的浏览器实例（Chrome 9222 / Edge 9223 / Chromium 9224）。

    用户可能是在 Chrome 里登录的，也可能在 Edge 里，脚本不该假设。
    """
    live = [p for p in PORT_BY_BROWSER.values() if is_running(p)]
    if not live:
        raise RuntimeError("没有正在运行的浏览器实例，先跑 login.py")
    return attach(live[0])


def launch(port: int | None = None, headless: bool = False, url: str = "about:blank",
           browser_name: str | None = None) -> Chrome:
    """Start the browser with a persistent, dedicated profile and attach to it."""
    name = resolve_browser(browser_name)
    if port is None:
        port = PORT_BY_BROWSER.get(name, PORT)
    if is_running(port):
        return attach(port)

    profile = os.path.expanduser(f"~/.read-anything/{name}-profile")
    os.makedirs(profile, exist_ok=True)
    args = [
        chrome_binary(name),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    if headless:
        args.append("--headless=new")
    args.append(url)

    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    chrome = Chrome(port=port)
    chrome.wait_ready(tries=120)
    # A fresh profile opens about:blank; give it a moment to register.
    for _ in range(40):
        if chrome.pages():
            break
        time.sleep(0.25)
    return attach(port)


def open_tab(url: str = "about:blank", port: int = PORT) -> Chrome:
    """Attach to a *fresh* tab.

    Reusing pages[0] is fragile: after several runs the first target may be a
    closed page and the websocket dies mid-request. A new tab always works.
    """
    chrome = launch(port=port)
    tab = chrome.new_tab("about:blank")
    chrome.close()
    fresh = Chrome(port=port).connect(tab["webSocketDebuggerUrl"])
    # Chrome ignores the URL passed to /json/new, so navigate explicitly.
    if url and url != "about:blank":
        fresh.goto(url)
    return fresh




if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--set":
        name = sys.argv[2].strip().lower()
        if name not in BINARIES:
            raise SystemExit(f"可选：{', '.join(BINARIES)}")
        path = chrome_binary(name)
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            fh.write(name)
        print(f"已设为 {name}：{path}")
        print(f"配置写在 {CONFIG_FILE}")
    else:
        print(f"当前浏览器：{BROWSER}（{chrome_binary()}）")
        print("改：python3 browser.py --set edge")
