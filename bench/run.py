#!/usr/bin/env python3
"""跑一批「搜索答不出来」的问题，看工具能不能答。

    python bench/run.py            # 全部
    python bench/run.py --limit 3  # 冒烟
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).parent
CMD = [sys.executable, "-m", "read_anything.ra"]


def ask(site: str, query: str, limit: int = 8) -> tuple[list[dict], float, str]:
    t0 = time.time()
    p = subprocess.run([*CMD, "list", site, query, "--limit", str(limit), "--json"],
                       capture_output=True, text=True, timeout=180)
    dt = time.time() - t0
    try:
        data = json.loads(p.stdout.strip() or "[]")
    except json.JSONDecodeError:
        return [], dt, (p.stderr or "bad json")[:60]
    if isinstance(data, dict):
        return [], dt, str(data.get("reason"))[:60]
    return data, dt, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ns = ap.parse_args()

    qs = yaml.safe_load((HERE / "questions.yaml").read_text(encoding="utf-8"))["questions"]
    if ns.limit:
        qs = qs[: ns.limit]

    rows, passed = [], 0
    for i, q in enumerate(qs, 1):
        hits, dt, err = ask(q["site"], q["q"])
        blob = " ".join((h.get("title", "") + " " + h.get("text", "")) for h in hits).lower()
        ok = bool(hits) and any(k.lower() in blob for k in q["expect"])
        passed += ok
        rows.append({
            "q": q["q"], "site": q["site"], "rows": len(hits),
            "ok": ok, "secs": round(dt, 1), "err": err,
            "first": (hits[0].get("title", "")[:48] if hits else ""),
        })
        print(f"{'PASS' if ok else 'FAIL'}  {q['site']:8} {len(hits):2} 条 {dt:5.1f}s  {q['q'][:34]}")

    out = HERE / "results.md"
    lines = [
        "# Benchmark", "",
        f"跑于 {time.strftime('%Y-%m-%d')}，{len(rows)} 个「网页搜索答不出来」的问题。", "",
        f"**命中 {passed}/{len(rows)}**（{passed / max(len(rows), 1):.0%}）", "",
        "| 结果 | 站点 | 条数 | 耗时 | 问题 | 首条 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {'✅' if r['ok'] else '❌'} | {r['site']} | {r['rows']} | {r['secs']}s | {r['q'][:30]} | {r['first']} |")
    lines += ["", "计分规则见 `questions.yaml`：只统计首页搜不到答案的问题。", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
