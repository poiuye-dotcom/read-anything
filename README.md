read-anything
-------------

[English](README.en.md)

read-anything 是一个只读的站点读取工具，给 agent 或你本人使用。
给一个词，它去小红书、知乎、微博、CSDN、贴吧、V2EX、GitHub、Reddit、YouTube 上搜，
返回标题、作者、链接和摘要；给一个链接，它读正文和评论。

默认读的是浏览器渲染后的页面，不是站点接口，所以不需要逆向签名。

别的工具被挡住时返回空列表，然后你以为那个平台没内容。
read-anything 把「拿不到」当成一个信号：拦截、限流、登录墙都会变成下一步的路由——
交回给调用方的搜索、镜像、换站、转载——直到出现能用的东西。

支持 macOS、Linux 和 Windows，只要有 Chrome 或 Edge。

它在功能上和 Agent Reach、MediaCrawler 这类工具重叠，
但优化了被挡住之后的那一段：交回查询、换镜像、换站，一直走到有结果。

以 MIT 协议发布。


### 变更

没有 CHANGELOG。行为变化看两个地方：`bench/results.md`（每次跑基准的记录）和
`health/health.md`（每个源最近一次检查的结果）。

### 文档速查

* [安装](#安装)
* [用法](#用法)
* [站点清单](#站点清单)
* [加一个站点](#加一个站点)
* [SKILL.md](SKILL.md)：给 agent 的触发规则
* [FAQ](#faq)
* [发布清单](PUBLISHING.md)

### 搜一次长这样

```
$ python -m read_anything.ra suggest "嵌入式 和 FPGA 学哪个"
意图：技术与工具（tech）
实体：嵌入式 FPGA

[zhihu]   "嵌入式 FPGA 原理" / "嵌入式 FPGA 对比" / "嵌入式 FPGA 坑"
[reddit]  "FPGA vs" / "FPGA production experience"
[bilibili]"嵌入式 FPGA 教程" / "嵌入式 FPGA 实测"

$ python -m read_anything.ra list zhihu "嵌入式 FPGA 就业" --limit 3
 1. FPGA未来岗位会不断压缩吗？
    https://www.zhihu.com/question/2035302534269625895/answer/2089327122158458006
 2. 现在FPGA就业怎么样?
    https://www.zhihu.com/question/1911036427732485617/answer/2062332901086307551
 3. 如果有一天FPGA技术大爆发了…
    https://www.zhihu.com/question/2054564528495628983/answer/2094029607666180648

（3 条，其中新增 3 条）
```

### 和别的工具比

| 工具 | 覆盖 | 形态 | 被挡住时 |
|---|---|---|---|
| read-anything | 11 个站，8 个不用登录 | MCP 服务器 / CLI / Python 包 | 交回查询给调用方，再走镜像、换站、转载 |
| omniseek | B站、知乎、V2EX 等 | MCP 服务器 | 未做专门处理 |
| Agent Reach | 十几个平台 | MCP 服务器 | 未做专门处理 |
| MediaCrawler | 国内主流平台 | 独立抓取程序 | 未做专门处理 |

覆盖数量上 read-anything 不是最多的。差别在最后一列。

### 为什么用它

* 11 个站里 8 个不需要登录。CSDN、V2EX、GitHub、微博、YouTube、贴吧、Reddit 直接能查，
  登录站各扫一次码就长期可用。

* 被挡住时不返回空列表，而是给出 `fallback` 对象：第一项 `0_handoff` 把控制权交回调用方，
  附 3–5 条可直接执行的查询；搜到链接再回来 `read_url` 读正文。
  后面还有镜像、换站、转载三层。
  （`ra.py list reddit fpga` 可以现场看这个输出。）

* 加一个站点改 `sites.yaml`，八行。
  容器选择器、字段映射、登录判据都写在配置里，不用改代码。

* 支持增量：`--new` 只输出上次没见过的条目，
  去重记录在 `~/.read-anything/read-anything.db`。

* 失败会分类：需要登录、需要可见窗口、被限流、暂无数据，
  各自给不同的下一步，而不是一律报错。

* 有可复跑的基准和源健康检查。
  基准只统计「网页搜索首页答不出来」的问题，当前 6/6；
  第一次跑是 5/6，漏的那次是 CSDN 瞬时返回空列表，据此加了空列表重试。

### 安装

需要 Python 3.10 以上，和一个 Chrome 或 Edge。

```bash
cd python
python3 -m venv .venv
./.venv/bin/pip install -e .
```

接进 MCP 客户端（DSH、Claude、Cursor），在 `bundle/cordis.patch.yml` 里填解释器路径：

```yaml
command: /绝对路径/python/.venv/bin/python
args: ["-m", "read_anything.mcp"]
```

DSH 里用 **Plugins → Add plugin** 选 `bundle/` 目录。其他客户端写 JSON：

```json
{ "mcpServers": { "readanything": {
    "command": "/绝对路径/python/.venv/bin/python",
    "args": ["-m", "read_anything.mcp"] } } }
```

### 用法

```bash
python -m read_anything.ra suggest "嵌入式 和 FPGA 学哪个"
python -m read_anything.ra list zhihu "嵌入式 就业" --limit 8
python -m read_anything.ra crawl zhihu --queries "嵌入式,FPGA" --limit 8
python -m read_anything.ra read "<URL>" --site xhs --comments 10
python -m read_anything.ra read-many --site xhs --urls urls.txt --workers 3
python -m read_anything.ra db stats
```

当包用：

```python
from read_anything.core import Session, extract_list, load_sites
_, sites = load_sites()
sess = Session("zhihu", sites["zhihu"])
sess.goto("https://www.zhihu.com/search?type=content&q=IC")
rows = extract_list(sess, 10)
```

### 站点清单

| 站点 | 前置动作 | 走什么 |
|---|---|---|
| 小红书 | 登录一次 | 渲染后的 DOM |
| 知乎 | 登录一次 | DOM，评论走页面内 api/v4 |
| B站 | 无 | 接口 + buvid3 cookie |
| CSDN | 无 | 公开 JSON 接口 |
| V2EX | 无 | sov2ex 公开搜索 |
| GitHub | 无 | 仓库搜索接口，无 token 时每分钟 10 次 |
| 微博 | 无 | m.weibo.cn 接口，visitor cookie 由浏览器处理 |
| 贴吧 | 按「吧」读，可能需要过验证码 | 渲染后的 DOM |
| YouTube | 无 | yt-dlp 的 ytsearch |
| Reddit | 无 | 公开 Atom |
| Handshake | 开可见窗口 + 填学校子域 | 渲染后的 DOM，Cloudflare 只拦无头浏览器 |
| X | 登录一次 | 渲染后的 DOM，未验证 |

本机出口被 Reddit 限流过，换设备或换网络即可，与工具无关。

### 加一个站点

```yaml
  xhs:
    search_url: "https://www.rednote.com/search_result?keyword={q}"
    login: {cookie: web_session, urls: ["https://www.rednote.com"]}
    container: "section.note-item"
    fields: {title: ".title", author: ".name", likes: ".count"}
    link: "a.cover"
```

`type` 支持 `dom`、`api`、`rss`、`ytdlp` 四种。

### 限制

只读。不发布、不评论、不点赞、不私信。

平台改版会让选择器失效。这是这类工具的天花板，不是 bug。

小红书对自动化最敏感，用小号，请求间隔不低于两秒。

### FAQ

**为什么不直接调接口？**
小红书每次请求要 x-s 签名，由页面里的 JS 在请求那一刻算出来，页面外算不出。
知乎要会话，贴吧要过验证码。所以读渲染后的 DOM。

**选择器失效了怎么办？**
`list_site` 会报 0 条或报错，不会给假结果。改 `sites.yaml` 里的 `container` 和 `fields`。

**会不会被封号？**
会，尤其小红书。这取决于你的用法，不取决于这个工具。

### License

MIT
