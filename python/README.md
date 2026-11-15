read-anything
-------------

[中文](README.md)

read-anything is a read-only site reader for agents and for you.
Give it a word and it searches Xiaohongshu, Zhihu, Weibo, CSDN, Tieba, V2EX, GitHub, Reddit and
YouTube, returning titles, authors, links and excerpts; give it a link and it reads the post and
its comments.

It reads the rendered page rather than a site's API, so there is no signing to reverse.

Other tools return an empty list when they are blocked, and you conclude the platform has
nothing. read-anything treats "can't get in" as a signal: a block, a rate limit or a login wall
each become the next route — the caller's search, a mirror, another site, a reprint — until
something usable comes out.

It runs on macOS, Linux and Windows with Chrome or Edge.

It overlaps with tools like Agent Reach and MediaCrawler,
but smooths out what happens after a block: queries handed back, a mirror, another site, until
something comes out.

MIT licensed.


### Changes

No CHANGELOG. Behavior lives in two files: `bench/results.md` and `health/health.md`.

### Documentation

* [Install](#install)
* [Usage](#usage)
* [Sites](#sites)
* [Adding a site](#adding-a-site)
* [SKILL.md](SKILL.md): trigger rules for agents
* [FAQ](#faq)
* [Release checklist](PUBLISHING.md)

### One search looks like this

```
$ python -m read_anything.ra suggest "embedded vs FPGA, which one"
intent: tech
topic: embedded FPGA

[zhihu]   "embedded FPGA 原理" / "embedded FPGA 对比" / "embedded FPGA 坑"
[reddit]  "FPGA vs" / "FPGA production experience"
[bilibili]"embedded FPGA 教程" / "embedded FPGA 实测"

$ python -m read_anything.ra list zhihu "嵌入式 FPGA 就业" --limit 3
 1. FPGA未来岗位会不断压缩吗？
    https://www.zhihu.com/question/2035302534269625895/answer/2089327122158458006
 2. 现在FPGA就业怎么样?
    https://www.zhihu.com/question/1911036427732485617/answer/2062332901086307551
 3. 如果有一天FPGA技术大爆发了…
    https://www.zhihu.com/question/2054564528495628983/answer/2094029607666180648

(3 rows, 3 new)
```

### Compared to other tools

| Tool | Coverage | Shape | When blocked |
|---|---|---|---|
| read-anything | 11 sites, 8 without login | MCP server / CLI / Python package | Hands queries back, then mirror, other site, reprint |
| omniseek | Bilibili, Zhihu, V2EX and more | MCP server | No dedicated handling |
| Agent Reach | A dozen platforms | MCP server | No dedicated handling |
| MediaCrawler | Major Chinese platforms | Standalone crawler | No dedicated handling |

It does not have the most coverage. The difference is in the last column.

### Why use it

* **11 sites, 8 of them without a login.** CSDN, V2EX, GitHub, Weibo, YouTube, Tieba and Reddit
  work immediately. The login sites need one QR scan, then stay usable.

* **A block returns the next step, not an empty list.** The `fallback` object leads with
  `0_handoff`: control goes back to the caller with 3–5 queries it can run, and the URL comes
  back to `read_url` to be read. Mirror, other site and reprint follow.
  `ra.py list reddit fpga` shows this live.

* **A new site is eight lines of config.** Container selector, field mapping and login check all
  live in `sites.yaml`. No code.

* **Failures are classified.** Needs login, needs a headed window, rate limited, no data —
  four states, four different next steps, instead of one generic error.

* **Incremental by default.** `--new` prints only what you have not seen, tracked in
  `~/.read-anything/read-anything.db`.

* **A benchmark you can rerun.** It only counts questions whose answer is not on the first page
  of web search. Currently 6/6. The first run scored 5/6 — CSDN returned an empty list for a
  moment, which is why empty responses are now retried.

### Install

Python 3.10 or newer, and Chrome or Edge. No clone needed.

```bash
python3 -m venv ~/.read-anything/venv
~/.read-anything/venv/bin/pip install "git+https://github.com/poiuye-dotcom/read-anything#subdirectory=python"
```

For any MCP client (Claude, Cursor and others):

```json
{ "mcpServers": { "readanything": {
    "command": "/Users/<you>/.read-anything/venv/bin/python",
    "args": ["-m", "read_anything.mcp"] } } }
```

DSH needs the plugin shape, which lives in the repo:

```bash
git clone https://github.com/poiuye-dotcom/read-anything
```

Point `command` in `bundle/cordis.patch.yml` at that interpreter, then **Plugins → Add plugin**
and pick the `bundle/` directory.

To work on the code, clone and run `pip install -e python/`.

### Usage

```bash
python -m read_anything.ra suggest "embedded vs FPGA, which one"
python -m read_anything.ra list zhihu "embedded jobs" --limit 8
python -m read_anything.ra crawl zhihu --queries "embedded,FPGA" --limit 8
python -m read_anything.ra read "<URL>" --site xhs --comments 10
python -m read_anything.ra read-many --site xhs --urls urls.txt --workers 3
python -m read_anything.ra db stats
```

As a library:

```python
from read_anything.core import Session, extract_list, load_sites
_, sites = load_sites()
sess = Session("zhihu", sites["zhihu"])
sess.goto("https://www.zhihu.com/search?type=content&q=IC")
rows = extract_list(sess, 10)
```

### Sites

| Site | Prerequisite | How it reads |
|---|---|---|
| Xiaohongshu | log in once | rendered page |
| Zhihu | log in once | page, comments via api/v4 |
| Bilibili | none | API + buvid3 cookie |
| CSDN | none | public JSON API |
| V2EX | none | sov2ex public search |
| GitHub | none | repo search, 10/min without a token |
| Weibo | none | m.weibo.cn API |
| Tieba | per board, captcha possible | rendered page |
| YouTube | none | yt-dlp ytsearch |
| Reddit | none | public Atom |
| Handshake | headed window + your school subdomain | rendered page |
| X | log in once | rendered page, unverified |

Reddit has rate-limited this machine's egress before. Switch device or network; it is not the tool.

### Adding a site

```yaml
  xhs:
    search_url: "https://www.rednote.com/search_result?keyword={q}"
    login: {cookie: web_session, urls: ["https://www.rednote.com"]}
    container: "section.note-item"
    fields: {title: ".title", author: ".name", likes: ".count"}
    link: "a.cover"
```

`type` is one of `dom`, `api`, `rss`, `ytdlp`.

### Limits

Read-only. No posting, commenting, liking or DMs.

Platform redesigns break selectors. That is the ceiling on this category of tool, not a bug.

Xiaohongshu is the most sensitive to automation. Use a throwaway account, keep requests at least
two seconds apart.

### FAQ

**Why not call the API?**
Xiaohongshu signs every request with x-s, computed by the page's own JavaScript at request time.
Zhihu wants a session. Tieba wants a captcha. So this reads the rendered page.

**A selector broke. Now what?**
`list_site` returns zero rows or an error, never fake results. Edit `container` and `fields` in
`sites.yaml`.

**Will I get banned?**
Yes, Xiaohongshu especially. That depends on how you use it, not on this tool.

### License

MIT
