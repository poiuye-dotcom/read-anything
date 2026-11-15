# 发布清单

## 一、PyPI（暂缓，等有人问「怎么装」再发）

当前安装方式是 `pip install "git+https://…/#subdirectory=python"`，无需 PyPI。

名字 `read-anything` 在 PyPI 上可用（查过）。发布后，用户只需：

```bash
pip install read-anything
```

bundle 里 `<VENV_PYTHON>` 就填那个环境的 `python`，不用 clone 仓库。

### 步骤

```bash
cd python
python3 -m venv .venv
./.venv/bin/pip install build twine

# 1. 打包（会读 pyproject.toml）
./.venv/bin/python -m build

# 2. 本地校验
./.venv/bin/python -m twine check dist/*

# 3. 传到测试库先试
./.venv/bin/python -m twine upload --repository testpypi dist/*

# 4. 装下来验一遍
python3 -m venv /tmp/t && /tmp/t/bin/pip install -i https://test.pypi.org/simple/ read-anything
/tmp/t/bin/read-anything suggest "embedded vs FPGA"

# 5. 正式发布
./.venv/bin/python -m twine upload dist/*
```

Token 用环境变量，别写进任何文件、别贴进聊天：

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...      # 在 pypi.org/manage/account/token/ 生成
```

### 发版前改三处

1. `pyproject.toml` 的 `version`
2. `python/README.md` —— 从 `../README.en.md` 复制（构建需要在本目录）
3. `pyproject.toml` 的 `[project.urls]`，把 `yourname` 换成你的 GitHub 用户名

## 二、GitHub

```bash
cd read-anything
git init && git add . && git commit -m "read-anything 2.0"
git remote add origin git@github.com:<你>/read-anything.git
git push -u origin main
gh release create v2.0.0 --notes "First release" read-anything-plugin.zip
```

仓库根目录放什么：

```
README.md  README.en.md  SKILL.md  SKILL.en.md  LICENSE  .gitignore
bundle/     DSH 插件
python/     pip 包（含 dist/ 不入库）
```

`.gitignore` 已经排除 `dist/`、`build/`、`*.egg-info`。

## 三、MCP 目录

按影响力排：

| 目录 | 提交方式 |
|---|---|
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | PR 到 community 列表 |
| [Smithery](https://smithery.ai) | 网页提交仓库地址 |
| [mcp.so](https://mcp.so) / [Glama](https://glama.ai/mcp) | 网页提交 |
| [PulseMCP](https://www.pulsemcp.com) | 网页提交 |

提交时用 `README.en.md` 的内容，description 抄 `pyproject.toml` 里那句。

## 四、发之前自查

- [ ] 全仓库搜一遍：路径、用户名、学校名、邮箱 —— 无命中
- [ ] `python -m read_anything.mcp` 能被 MCP 客户端拉起
- [ ] wheel 里包含 `sites.yaml` 和 `queries.yaml`（`unzip -l` 看）
- [ ] README 第一屏写清「哪些站开箱能用」
- [ ] 没有把任何账号、token、cookie 提交进仓库
