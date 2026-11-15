"""read-anything 核心：配置驱动的列表抓取。

四件事，对应 v2 的 1–5：
  1. 合理性校验 —— 换关键词结果不变就报错，不静默返回垃圾
  2. 站点配置化 —— sites.yaml 决定容器/字段/链接，加站不写代码
  3. 重试与限速 —— 指数退避 + 每站最小间隔
  4. 增量去重   —— SQLite 记 seen(url)，--new 只出没见过的
  5. 并发       —— read_many 用多标签页并行
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import browser

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "sites.yaml")
DB_PATH = os.path.expanduser("~/.read-anything/read-anything.db")


# --------------------------------------------------------------------------- 配置
def load_sites() -> tuple[dict, dict]:
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    defaults = cfg.get("defaults") or {}
    sites = {}
    for key, site in (cfg.get("sites") or {}).items():
        merged = dict(defaults)
        merged.update(site)
        sites[key] = merged
    return defaults, sites


# --------------------------------------------------------------------------- 限速
class RateLimiter:
    """每个域名一个最小间隔，线程安全。"""

    def __init__(self, delay: float):
        self.delay = delay
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.time()
            nxt = self._last.get(host, 0) + self.delay
            if nxt > now:
                time.sleep(nxt - now)
            self._last[host] = time.time()


# --------------------------------------------------------------------------- 存储
class Store:
    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS seen(
                 url TEXT PRIMARY KEY,
                 site TEXT, title TEXT,
                 first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                 last_seen  TEXT DEFAULT CURRENT_TIMESTAMP)"""
        )
        self.conn.commit()
        self._lock = threading.Lock()

    def mark(self, rows: list[dict], site: str) -> dict[str, bool]:
        """返回 {url: 是否第一次见}，并刷新 last_seen。"""
        out = {}
        with self._lock:
            for r in rows:
                url = r.get("url") or ""
                if not url:
                    continue
                cur = self.conn.execute("SELECT 1 FROM seen WHERE url=?", (url,)).fetchone()
                if cur:
                    self.conn.execute("UPDATE seen SET last_seen=CURRENT_TIMESTAMP WHERE url=?", (url,))
                    out[url] = False
                else:
                    self.conn.execute(
                        "INSERT INTO seen(url, site, title) VALUES(?,?,?)",
                        (url, site, (r.get("title") or "")[:200]),
                    )
                    out[url] = True
            self.conn.commit()
        return out

    def stats(self) -> list[tuple[str, int]]:
        return self.conn.execute(
            "SELECT site, COUNT(*) FROM seen GROUP BY site ORDER BY 2 DESC"
        ).fetchall()


# --------------------------------------------------------------------------- 异常
class SanityError(RuntimeError):
    pass


class LoginRequired(RuntimeError):
    pass


# --------------------------------------------------------------------------- 会话
@dataclass
class Session:
    site_key: str
    site: dict
    _ch: Any = field(default=None, repr=False)

    def __post_init__(self):
        self.limiter = RateLimiter(self.site.get("crawl_delay", 2.0))

    # -- 连接 ---------------------------------------------------------------
    def connect(self):
        if self._ch is None:
            self._ch = browser.attach_any()
            if self.site.get("requires_headed"):
                ua = self._ch.version().get("User-Agent", "")
                if "Headless" in ua:
                    raise LoginRequired(
                        f"{self.site['name']}：这个站会拦无头浏览器。"
                        f"先跑 `python3 login.py {self.site_key}` 开一个可见窗口再来。"
                    )
        return self._ch

    def close(self):
        if self._ch is not None:
            self._ch.close()
            self._ch = None

    # -- 带重试的动作 --------------------------------------------------------
    def _retry(self, fn, *a, **kw):
        attempts = int(self.site.get("retry", 3))
        backoff = list(self.site.get("backoff") or [2, 6, 15])
        last = None
        for i in range(attempts):
            try:
                return fn(*a, **kw)
            except Exception as exc:            # noqa: BLE001
                last = exc
                if i == attempts - 1:
                    break
                wait = backoff[min(i, len(backoff) - 1)] + random.uniform(0, 1)
                time.sleep(wait)
        raise last  # type: ignore[misc]

    def goto(self, url: str, settle: float | None = None) -> None:
        ch = self.connect()
        host = url.split("/")[2]
        self.limiter.wait(host)

        def _go():
            ch.call("Page.navigate", {"url": url})
            for _ in range(60):
                if ch.eval("document.readyState") == "complete":
                    break
                time.sleep(0.3)
            time.sleep(self.site.get("settle", 3.0) if settle is None else settle)

        self._retry(_go)

    def check_login(self) -> None:
        spec = self.site.get("login") or {}
        ch = self.connect()
        if spec.get("check_url"):
            ch.call("Page.navigate", {"url": spec["check_url"]})
            time.sleep(1.5)
            landed = ch.eval("location.href") or ""
            if any(m in landed for m in spec.get("redirect_markers", [])):
                raise LoginRequired(f"{self.site['name']}：需要登录（跑 login.py {self.site_key}）")
            return
        if spec.get("cookie"):
            ch.call("Network.enable")
            for url in spec.get("urls", []):
                cookies = ch.call("Network.getCookies", {"urls": [url, url + "/"]}).get("cookies", [])
                if any(c["name"] == spec["cookie"] for c in cookies):
                    return
            raise LoginRequired(f"{self.site['name']}：需要登录（跑 login.py {self.site_key}）")

    def scroll(self, times: int) -> None:
        ch = self.connect()
        for _ in range(times):
            ch.eval("window.scrollBy(0, window.innerHeight * 1.2)")
            time.sleep(self.site.get("scroll_pause", 1.2))


# --------------------------------------------------------------------------- 抽取
JS_LIST = r"""
(() => {
  const CONTAINER = %(container)s, FIELDS = %(fields)s, LINK = %(link)s, MODE = %(mode)s;
  const TITLE_LINE = %(title_line)s;
  const out = [];
  for (const el of document.querySelectorAll(CONTAINER)) {
    let box = el;
    if (MODE === 'anchors') {
      while (box && (box.innerText || '').length < 60) box = box.parentElement;
      if (!box) continue;
    }
    const rec = {};
    for (const k in FIELDS) {
      const n = box.querySelector(FIELDS[k]);
      rec[k] = n ? (n.innerText || n.textContent || '').trim().replace(/\s+/g, ' ') : '';
    }
    const a = LINK ? box.querySelector(LINK) : (MODE === 'anchors' ? el : box.querySelector('a[href]'));
    rec.url = a ? a.href : '';
    if (MODE === 'anchors' && !FIELDS.title) {
      const lines = (box.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
      const tl = (typeof TITLE_LINE === 'number') ? TITLE_LINE : 1;
      rec.title = lines[tl] || lines[0] || '';
      rec.company = lines[0] || '';
      rec.text = lines.slice(tl + 1).join(' · ').slice(0, 160);
    }
    if (rec.url) out.push(rec);
  }
  return out;
})()
"""


def extract_list(sess: Session, limit: int) -> list[dict]:
    ch = sess.connect()
    js = JS_LIST % {
        "container": json.dumps(sess.site["container"]),
        "fields": json.dumps(sess.site.get("fields") or {}),
        "link": json.dumps(sess.site.get("link") or ""),
        "mode": json.dumps(sess.site.get("mode") or "cards"),
        "title_line": json.dumps(sess.site.get("title_line")),
    }
    found: dict[str, dict] = {}
    by_path = sess.site.get("dedupe_key") == "path"
    for _ in range(sess.site.get("scrolls", 3) + 1):
        for r in ch.eval(js) or []:
            key = r["url"].split("?")[0] if by_path else r["url"]
            found.setdefault(key, r)
        if len(found) >= limit:
            break
        sess.scroll(1)
    rows = list(found.values())
    ex = sess.site.get("exclude")
    if ex:
        import re as _re
        rows = [r for r in rows if not _re.search(ex, (r.get("title") or ""))]
    rows = rows[:limit]
    for r in rows:
        r["site"] = sess.site_key
        r["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return rows


def sanity_check(site_key: str, query: str, rows: list[dict], baseline: dict[str, str]) -> None:
    """同一个站，换关键词后首条结果还一样 → 搜索参数大概率失效。"""
    if not rows:
        raise SanityError(f"{site_key}: 0 条结果（选择器失效？被反爬？）")
    first = (rows[0].get("title") or rows[0].get("url") or "")[:80]
    prev = baseline.get(site_key)
    if prev and prev == first and query:
        raise SanityError(
            f"{site_key}: 换关键词后首条结果没变（{first[:40]}…）——搜索参数可能被忽略，"
            f"结果不可信。检查 search_url 模板。"
        )
    baseline[site_key] = first
