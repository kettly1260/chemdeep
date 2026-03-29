# ChemDeep GitHub 发布整理说明

本文档用于指导将 `ChemDeep` 整理后发布到 GitHub，并明确哪些内容属于隐私、运行态数据或第三方派生内容，不能公开提交。

## 1. 当前仓库状态结论

- `chemdeep/` 目录内当前**没有真实嵌套 Git 仓库**（未发现 `chemdeep/.git/` 或子目录中的 `.git/`）。
- 当前所谓“嵌套 git”问题，主要不是 Git submodule，而是：
  - 仓库里混入了多个可独立运行的子项目目录，例如 `paper-search-mcp-nodejs/`、`mcp-websearch/`
  - 同时还混入了大量本地运行产物，例如 `.venv/`、`profiles/`、`logs/`、`data/`、`runs/`
- 因此这次发布的核心不是移除 submodule，而是**把本地运行态内容与敏感配置从待发布内容中剥离**。

## 2. 绝对不要公开提交的内容

以下内容应视为隐私或本地运行数据：

### 2.1 密钥 / 凭证 / Cookie / 本地环境变量

- `config/.env`
- `paper-search-mcp-nodejs/.env`
- `mcp-websearch/.env`（若后续出现）
- `mcp-websearch/.envrc`
- `config/cf_cookies.json`

说明：
- `config/.env` 中包含 Telegram、OpenAI、Gemini、代理、OpenAlex 等配置位。
- `paper-search-mcp-nodejs/.env` 已检测到真实 API Key，必须视为**已泄露风险**内容，禁止上传。
- `config/cf_cookies.json` 属于浏览器/站点访问凭据数据，禁止上传。

## 2.2 本地浏览器配置与会话数据

- `profiles/`

说明：
- 该目录包含 Edge 用户数据、扩展、缓存、会话、同步状态等。
- 发布到 GitHub 会暴露个人浏览器环境痕迹、访问状态、扩展信息，存在明显隐私风险。

## 2.3 本地运行产物 / 数据库 / 报告 / 缓存

- `.venv/`
- `logs/`
- `cache/`
- `runs/`
- `data/`
- `chemdeep.db`
- 其他 `*.db`

说明：
- `data/` 下有研究结果、抓取文本、报告、检查点、项目状态。
- 这些内容通常体积大、可再生，而且可能包含你的研究主题、使用痕迹与抓取结果。

## 2.4 Node 依赖与构建产物

- `paper-search-mcp-nodejs/node_modules/`
- `paper-search-mcp-nodejs/dist/`

说明：
- 这类内容应由安装命令重新生成，不应直接入库。

## 3. 建议公开提交的内容

以下内容适合作为开源仓库主体：

### 3.1 核心源码

- `main.py`
- `apps/`
- `core/`
- `utils/`
- `config/settings.py`
- `mcp_server/`
- `mcp-websearch/`
- `paper-search-mcp-nodejs/src/`
- `tests/`

### 3.2 项目元数据与依赖描述

- `README.md`
- `UV_README.md`
- `pyproject.toml`
- `requirements.txt`
- `requirements.lock.txt`
- `bootstrap.ps1`
- `paper-search-mcp-nodejs/package.json`
- `paper-search-mcp-nodejs/package-lock.json`
- `paper-search-mcp-nodejs/.env.example`

### 3.3 历史代码（可选）

- `_legacy/`

如果你希望仓库更干净，可以不公开旧实现；如果要保留，建议在主 `README.md` 中注明它是历史归档代码。

## 4. 已新增的发布保护

已新增根级忽略文件：

- `.gitignore`

它会忽略以下高风险目录与文件：

- `.venv/`
- `config/.env`
- `paper-search-mcp-nodejs/.env`
- `mcp-websearch/.envrc`
- `logs/`
- `cache/`
- `runs/`
- `profiles/`
- `data/`
- `*.db`
- `paper-search-mcp-nodejs/node_modules/`
- `paper-search-mcp-nodejs/dist/`

## 5. 关于“嵌套 Git”的发布策略

### 方案 A：把子目录作为普通目录随主项目一起发布（推荐）

适用场景：
- `paper-search-mcp-nodejs/` 和 `mcp-websearch/` 只是主项目附属组件
- 你希望一个仓库完成全部部署

做法：
- 保留目录结构
- 不要保留它们各自的 `.git/`
- 使用主仓库统一管理版本

当前你的目录已经基本符合这个状态。

### 方案 B：把子项目拆成独立仓库，再以 submodule 或文档方式引用

适用场景：
- 你希望 `paper-search-mcp-nodejs/` 单独维护
- 你希望 `mcp-websearch/` 成为独立项目

做法：
- 先各自单独建仓
- 主仓库通过 Git submodule 引入，或仅在文档中说明外部依赖

当前不建议立即这样做，因为会增加维护复杂度。

## 6. 发布前手工检查清单

在真正 push 前，建议逐项确认：

- [ ] `config/.env` 没有进入暂存区
- [ ] `paper-search-mcp-nodejs/.env` 没有进入暂存区
- [ ] `config/cf_cookies.json` 没有进入暂存区
- [ ] `profiles/` 没有进入暂存区
- [ ] `data/` 没有进入暂存区
- [ ] `logs/` 没有进入暂存区
- [ ] `.venv/` 没有进入暂存区
- [ ] `chemdeep.db` 没有进入暂存区
- [ ] `paper-search-mcp-nodejs/node_modules/` 没有进入暂存区

## 7. 建议的 GitHub 发布命令

在 `g:\LLM` 根仓库下执行时，可按下面顺序操作：

```bash
git status --short -- chemdeep
git add chemdeep/.gitignore chemdeep/README.md chemdeep/RELEASE_GITHUB.md
git add chemdeep/apps chemdeep/core chemdeep/utils chemdeep/config/settings.py
git add chemdeep/mcp_server chemdeep/mcp-websearch chemdeep/paper-search-mcp-nodejs
git add chemdeep/main.py chemdeep/bootstrap.ps1 chemdeep/pyproject.toml chemdeep/requirements.txt chemdeep/requirements.lock.txt
```

然后再次检查：

```bash
git status --short -- chemdeep
```

如果发现以下文件仍被暂存，必须移除：

```bash
git restore --staged chemdeep/config/.env
git restore --staged chemdeep/config/cf_cookies.json
git restore --staged chemdeep/paper-search-mcp-nodejs/.env
git restore --staged -SW chemdeep/data chemdeep/logs chemdeep/profiles chemdeep/.venv chemdeep/cache chemdeep/runs
```

最后提交并推送：

```bash
git commit -m "chore: prepare chemdeep for github release"
git remote add origin <your-github-repo-url>
git push -u origin main
```

## 8. 额外安全提醒

你当前已经暴露迹象较明显的敏感文件包括：

- `paper-search-mcp-nodejs/.env`
- `config/.env`
- `config/cf_cookies.json`

如果这些内容曾经被提交过或发给他人，建议尽快：

1. 轮换相关 API Key
2. 失效 Cloudflare / 站点 Cookie
3. 更换 Telegram Bot Token（如已暴露）
4. 检查代理账号、邮箱、私有接口地址是否也在环境文件中暴露

## 9. 推荐的仓库定位

建议将本仓库定位为：

- 一个面向化学文献研究的 AI Agent 项目
- 包含 Telegram Bot、研究流程、MCP 搜索集成
- 不包含个人运行数据、浏览器配置、真实 API 密钥与已抓取语料

这样发布后的仓库会更适合作为：

- 开源展示
- 团队协作
- 新机器复现部署
- 后续持续维护
