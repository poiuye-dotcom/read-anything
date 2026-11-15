"""搜职位 / 读 JD / 扫身份限制。

搜职位：JobSpy（公开页面，不用登录）
读详情：CDP 打 LinkedIn 的 guest 接口（不用登录，拿全文）
扫限制：正则扫 JD 正文，标出哪些岗位你根本投不了

用法：
    ./.venv/bin/python jobs.py search "asic intern" --location "Roseville, CA"
    ./.venv/bin/python jobs.py read "https://www.linkedin.com/jobs/view/4483125446"
    ./.venv/bin/python jobs.py screen jobs.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time

# 命中就基本没戏：需要公民身份 / 出口管制 / 安全许可
HARD = [
    r"\bU\.?\s?S\.?\s?person\b",
    r"\bU\.?\s?S\.?\s?citizen",
    r"\bUS\s?citizen",
    r"citizenship\s+(?:is\s+)?required",
    r"must\s+be\s+a\s+(?:U\.?S\.?\s+)?citizen",
    r"\bITAR\b",
    r"export\s+control",
    r"security\s+clearance",
    r"clearance\s+required",
    r"ability\s+to\s+obtain\s+a\s+clearance",
]

# 命中要留意：不 sponsor / 只收绿卡
SOFT = [
    r"(?:will|does|do)\s+not\s+(?:provide\s+)?sponsor",
    r"unable\s+to\s+sponsor",
    r"no\s+(?:visa\s+)?sponsorship",
    r"not\s+able\s+to\s+sponsor",
    r"not\s+sponsor(?:ing|ed|s)?",
    r"permanent\s+resident",
    r"green\s+card",
]

# 命中只是提示：F-1 + CPT/OPT 通常能满足"可合法工作"这条
NOTE = [
    r"authorized\s+to\s+work",
    r"work\s+authorization",
    r"legally\s+authorized",
    r"eligible\s+to\s+work\s+in\s+the\s+U\.?S",
]

HARD_RE = [re.compile(p, re.I) for p in HARD]
SOFT_RE = [re.compile(p, re.I) for p in SOFT]
NOTE_RE = [re.compile(p, re.I) for p in NOTE]


def scan(text: str) -> tuple[str, str]:
    """返回 (等级, 证据)。等级：hard / soft / note / none。"""
    for rx in HARD_RE:
        m = rx.search(text)
        if m:
            return "hard", snippet(text, m.start())
    for rx in SOFT_RE:
        m = rx.search(text)
        if m:
            return "soft", snippet(text, m.start())
    for rx in NOTE_RE:
        m = rx.search(text)
        if m:
            return "note", snippet(text, m.start())
    return "none", ""


def snippet(text: str, at: int, width: int = 90) -> str:
    start = max(0, at - width // 2)
    return re.sub(r"\s+", " ", text[start : at + width // 2]).strip()


# --------------------------------------------------------------------- 浏览器
def _open():
    import browser

    ch = browser.open_tab("https://www.linkedin.com/jobs/")
    for _ in range(40):
        if ch.eval("document.readyState") == "complete":
            break
        time.sleep(0.3)
    return ch


def fetch_jd(ch, url: str, retries: int = 3) -> tuple[int, str]:
    """返回 (HTTP 状态, 正文)。被限流时退避重试。"""
    m = re.search(r"/(\d{6,})", url) or re.search(r"-(\d{6,})", url)
    if not m:
        return 0, ""
    target = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}"
    status = 0
    for attempt in range(retries):
        res = ch.fetch_text(target)
        status = res["status"]
        if status == 200:
            text = re.sub(r"<[^>]+>", " ", res["body"])
            return status, re.sub(r"\s+", " ", text).strip()
        time.sleep(3 * (attempt + 1))  # 3s, 6s, 9s
    return status, ""


# --------------------------------------------------------------------- 命令
def search(query: str, location: str, limit: int, flag_risk: bool) -> int:
    from jobspy import scrape_jobs

    df = scrape_jobs(
        site_name=["linkedin"],
        search_term=query,
        location=location or "United States",
        results_wanted=limit,
        hours_old=24 * 30,
        verbose=0,
    )
    rows = df.to_dict("records")
    for row in rows:
        line = f"- {row.get('title','')[:68]} | {row.get('company','')}"
        if flag_risk:
            level, why = scan(str(row.get("description") or ""))
            if level != "none":
                line += f"   ⚠ {level}: {why[:70]}"
        print(line)
        print(f"  {str(row.get('job_url',''))[:110]}")
    return 0


def read(url: str) -> int:
    ch = _open()
    try:
        status, text = fetch_jd(ch, url)
    finally:
        ch.close()
    if not text:
        print(f"没拿到正文（HTTP {status}）", file=sys.stderr)
        return 1
    level, why = scan(text)
    print(text[:5000])
    print(f"\n[身份限制] {level}" + (f"：{why}" if why else ""))
    return 0


def screen(csv_path: str, out_path: str, pause: float) -> int:
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    # 同一岗位常在 Indeed 和 LinkedIn 各出现一次：留 LinkedIn 那条（能扫），去掉重复
    def norm(t: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (t or "").lower())[:40]

    best: dict[tuple, dict] = {}
    for row in rows:
        key = (norm(row.get("title", ""))[:36], norm(row.get("company", ""))[:18])
        url = row.get("job_url") or row.get("url") or ""
        if key not in best or ("linkedin.com/jobs" in url and "linkedin.com/jobs" not in (best[key].get("job_url") or "")):
            best[key] = row
    dropped = len(rows) - len(best)
    rows = list(best.values())
    print(f"待扫 {len(rows)} 条（去掉 {dropped} 条跨站重复）\n")

    ch = _open()
    try:
        for i, row in enumerate(rows, 1):
            url = row.get("job_url") or row.get("url") or ""
            desc = row.get("description") or ""
            if len(desc) > 200:
                # JobSpy 已经把 Indeed 的 JD 正文带回来了，不用再开浏览器
                row["intl_risk"], row["evidence"] = scan(desc)
                mark = {"hard": "🔴", "soft": "🟡", "note": "🔵", "none": "🟢"}[row["intl_risk"]]
                print(f"{mark} [{i:2}/{len(rows)}] {row.get('company','')[:24]:24} {row.get('title','')[:44]}  (csv)")
                if row["evidence"]:
                    print(f"      {row['evidence'][:110]}")
                continue
            if "linkedin.com/jobs" not in url:
                row["intl_risk"], row["evidence"] = "unknown", "无正文且非 LinkedIn 链接"
                continue
            status, text = fetch_jd(ch, url)
            if len(text) < 200:
                row["intl_risk"], row["evidence"] = "unknown", f"正文没拿到（HTTP {status}）"
            else:
                row["intl_risk"], row["evidence"] = scan(text)
            mark = {"hard": "🔴", "soft": "🟡", "note": "🔵", "none": "🟢", "unknown": "⚪"}[row["intl_risk"]]
            print(f"{mark} [{i:2}/{len(rows)}] {row.get('company','')[:24]:24} {row.get('title','')[:44]}")
            if row["evidence"]:
                print(f"      {row['evidence'][:110]}")
            time.sleep(pause)
    finally:
        ch.close()

    order = {"hard": 0, "soft": 1, "note": 2, "unknown": 3, "none": 4}
    rows.sort(key=lambda r: order.get(r["intl_risk"], 9))
    fields = ["intl_risk", "company", "title", "location", "evidence", "job_url"]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    tally = {}
    for r in rows:
        tally[r["intl_risk"]] = tally.get(r["intl_risk"], 0) + 1
    print(f"\n🔴 卡死 {tally.get('hard',0)}  🟡 不 sponsor {tally.get('soft',0)}  "
          f"🔵 需工作许可 {tally.get('note',0)}  🟢 无限制 {tally.get('none',0)}  "
          f"⚪ 未扫 {tally.get('unknown',0)}")
    print(f"→ {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--location", default="")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--risk", action="store_true", help="顺带扫身份限制")

    r = sub.add_parser("read")
    r.add_argument("url")

    c = sub.add_parser("screen")
    c.add_argument("csv")
    c.add_argument("--out", default="")
    c.add_argument("--pause", type=float, default=1.6)

    ns = ap.parse_args()
    if ns.cmd == "search":
        return search(ns.query, ns.location, ns.limit, ns.risk)
    if ns.cmd == "read":
        return read(ns.url)
    out = ns.out or ns.csv.replace(".csv", "_screened.csv")
    return screen(ns.csv, out, ns.pause)


if __name__ == "__main__":
    raise SystemExit(main())
