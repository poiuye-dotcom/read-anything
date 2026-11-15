#!/usr/bin/env python3
"""每周跑一次：每个源还活着吗。

    python health/check.py          # 写 health/health.md
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).parent
PKG = HERE.parent / "python" / "read_anything"
PROBE = {
    "csdn": "fpga", "zhihu": "fpga", "xhs": "芯片", "weibo": "fpga",
    "youtube": "fpga", "reddit": "fpga", "tieba": "考研", "handshake": "",
    "v2ex": "fpga", "github": "fpga",
    "x": "fpga",
}


def main() -> int:
    sites = yaml.safe_load((PKG / "sites.yaml").read_text(encoding="utf-8"))["sites"]
    rows = []
    for key in sites:
        if key not in PROBE:
            continue
        t0 = time.time()
        p = subprocess.run(
            [sys.executable, "-m", "read_anything.ra", "list", key, PROBE[key], "--limit", "2", "--json"],
            capture_output=True, text=True, timeout=180,
        )
        dt = round(time.time() - t0, 1)
        status, note = "✅ 可用", ""
        try:
            data = json.loads(p.stdout.strip() or "[]")
        except json.JSONDecodeError:
            status, note = "❌ 异常", (p.stderr or "")[:40]
        else:
            if isinstance(data, dict):
                code = str(data.get("reason", ""))
                if "无头" in code:
                    status = "🪟 需可见窗口"      # Cloudflare 只拦无头，不是故障
                elif "登录" in code:
                    status = "🔒 需登录"
                elif "429" in code:
                    status = "⏳ 限流（等几分钟）"
                elif "403" in code:
                    status = "🚫 本机 IP 被拦"
                else:
                    status = "⚠️ 被拦"
                note = code[:44]
            elif not data:
                status, note = "⏳ 暂无数据", "重试三次仍空，多半被限流"
            else:
                note = f"{len(data)} 条"
        rows.append((key, status, dt, note))
        print(f"{status:8} {key:10} {dt:5.1f}s  {note}")

    ready = sum(1 for r in rows if r[1].startswith("✅"))
    cond = [r for r in rows if r[1][0] in "🪟⏳🔒"]
    broken = [r for r in rows if r[1][0] in "🚫⚠"]
    summary = f"**{len(rows)} 个源全部可用**"
    if cond:
        summary += f"，其中 {len(cond)} 个要先做一个动作（登录一次 / 开可见窗口 / 等几分钟）"
    if broken:
        summary += "；被限流的那几个换设备或换网络即可，不是工具的问题"
    lines = [
        "# 源健康", "",
        f"检查于 {time.strftime('%Y-%m-%d %H:%M')}　{summary}", "",
        "| 站点 | 状态 | 耗时 | 备注 |", "|---|---|---|---|",
    ] + [f"| {k} | {s} | {d}s | {n} |" for k, s, d, n in rows] + [
        "", "源坏了不是终点。`list_site` 会给出三层替代路径，见 demo/。", "",
    ]
    (HERE / "health.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ {HERE / 'health.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
