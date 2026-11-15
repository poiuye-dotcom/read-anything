#!/usr/bin/env python3
"""三幕演示：源坏了，然后呢。

    python demo/demo.py

不需要参数，不需要网络里的一切都成功——第二幕和第三幕失败才是重点。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time

CMD = [sys.executable, "-m", "read_anything.ra"]


def run(*args: str) -> tuple[str, int]:
    p = subprocess.run([*CMD, *args], capture_output=True, text=True, timeout=180)
    return (p.stdout or "") + (p.stderr or ""), p.returncode


def banner(text: str) -> None:
    print(f"\n\033[1m{'─' * 62}\n{text}\n{'─' * 62}\033[0m")


def main() -> int:
    banner("场景 1／4   打一个正在限流的源")
    print("$ ra.py list reddit \"fpga\"\n")
    out, _ = run("list", "reddit", "fpga", "--limit", "3")
    print(out.rstrip())
    print("\n它没有硬扛。它把控制权交回来了：你去搜，搜到链接我读。")

    time.sleep(0.5)

    banner("场景 2／4   换个源，同一个问题")
    print("$ ra.py list zhihu \"fpga\"\n")
    out, _ = run("list", "zhihu", "fpga", "--limit", "3")
    print(out.rstrip()[:1200])
    url = ""
    m = re.search(r"https://www\.zhihu\.com/\S+", out)
    if m:
        url = m.group(0)

    time.sleep(0.5)

    banner("场景 3／4   控制权交回后的下一步：读那条链接")
    if url:
        print(f"$ ra.py read \"{url[:60]}…\" --site zhihu\n")
        out, _ = run("read", url, "--site", "zhihu")
        print(out.rstrip()[:900])
    else:
        print("（上一幕没抓到链接，跳过）")

    banner("场景 4／4   换成 JSON，给 agent 直接执行")
    print("$ ra.py list x \"fpga\" --json\n")
    out, _ = run("list", "x", "fpga", "--limit", "2", "--json")
    try:
        data = json.loads(out)
        print(json.dumps({k: data[k] for k in ("ok", "blocked_at", "reason")}, ensure_ascii=False, indent=1))
        print(json.dumps(data["fallback"], ensure_ascii=False, indent=1)[:700])
    except Exception:
        print(out[:800])

    banner("完")
    print("同一个问题，三条路。没有一条是“返回空列表”。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
