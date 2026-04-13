# paper-search-mcp-nodejs Vendor 维护说明

## 目标

把 `paper-search-mcp-nodejs/` 继续作为主仓库内的 vendored 目录维护，同时把上游导入和 ChemDeep 本地定制明确分层，降低后续同步成本。

## 当前结论

- 当前最适合的维护模型是 `Vendor Import + 本地 Patch Stack`
- 现阶段不建议直接迁移到 `submodule` 或 `subtree`
- 如果未来 ChemDeep 对该目录的偏离继续扩大，再考虑独立 fork

## 当前维护映射

- Vendored 路径：`paper-search-mcp-nodejs/`
- Upstream 仓库：`https://github.com/Dianel555/paper-search-mcp-nodejs`
- 当前本地基线：`v0.2.5`（推定值；下次正式同步前必须再核对一次 upstream tag/commit）
- 已知上游漂移：upstream `main` 的 `package.json` 已显示 `0.2.6`，说明本地 vendored 目录已经落后于上游

## 当前本地 Patch Stack

按顺序保留以下 ChemDeep 补丁层，不要混入纯上游导入提交：

1. `7b19b31` `Move paper-search-mcp-nodejs config to config/ directory and update documentation`
   - 作用：ChemDeep 配置路径与启动适配
   - 主要文件：`paper-search-mcp-nodejs/src/server.ts`, `paper-search-mcp-nodejs/README.md`
2. `3b4c682` `enhance research fetch workflows and mirror resilience`
   - 作用：ChemDeep 的镜像 / Scholar / Lanfanshu / MCP 行为增强
   - 主要文件：`paper-search-mcp-nodejs/src/config/constants.ts`, `paper-search-mcp-nodejs/src/mcp/handleToolCall.ts`, `paper-search-mcp-nodejs/src/platforms/LanfanshuSearcher.ts`, `paper-search-mcp-nodejs/src/platforms/MirrorManager.ts`, `paper-search-mcp-nodejs/src/server.ts`

## 冲突热点

以下文件在未来同步上游时最容易冲突，应该优先保持“少改核心逻辑、多加扩展层”的策略：

- `paper-search-mcp-nodejs/src/mcp/handleToolCall.ts`
- `paper-search-mcp-nodejs/src/platforms/LanfanshuSearcher.ts`
- `paper-search-mcp-nodejs/src/server.ts`

相对更稳定、也更适合作为 ChemDeep 扩展落点的文件：

- `paper-search-mcp-nodejs/src/platforms/MirrorManager.ts`

## 标准同步节奏

每次同步上游时，固定按以下顺序执行：

1. 确认目标 upstream tag/release
2. 导出当前 ChemDeep patch stack
3. 导入纯 upstream 快照，形成单独的 vendor commit
4. 重放 ChemDeep patch stack
5. 解决冲突并验证构建 / 测试 / lint / 核心功能

## 建议提交结构

- `vendor(paper-search-mcp-nodejs): import upstream v0.2.6`
- `chemdeep(paper-search): adapt config loading`
- `chemdeep(paper-search): add mirror-aware scholar fallback`

不要把 upstream 导入和 ChemDeep 本地改动写进同一个提交。

## Patch 导出工具

仓库内已提供 `scripts/export-paper-search-patches.ps1`，用于把当前已知的 ChemDeep patch stack 导出成可重放的补丁文件。

默认输出目录：`.kilo/vendor-patches/paper-search-mcp-nodejs/`

示例：

```powershell
pwsh -NoProfile -File .\scripts\export-paper-search-patches.ps1
```

如果需要指定提交列表：

```powershell
pwsh -NoProfile -File .\scripts\export-paper-search-patches.ps1 `
  -PatchCommits 7b19b31,3b4c682
```

导出后可在合适的 vendor import 分支上使用 `git am` 重放：

```powershell
git am .kilo/vendor-patches/paper-search-mcp-nodejs/*.patch
```

## 推荐同步工作流

### 1. 导出本地补丁

```powershell
pwsh -NoProfile -File .\scripts\export-paper-search-patches.ps1
```

### 2. 创建同步分支

```powershell
git switch -c vendor/paper-search-v0.2.6
```

### 3. 导入纯上游快照

建议使用临时 clone 或 release archive，把上游 `v0.2.6` 的目录内容覆盖到 `paper-search-mcp-nodejs/`，然后只提交 vendor 变化。

此步骤提交时，提交内容必须只包含上游原始代码变化，不要混入 ChemDeep 自定义逻辑。

### 4. 创建 vendor commit

```powershell
git add paper-search-mcp-nodejs
git commit -m "vendor(paper-search-mcp-nodejs): import upstream v0.2.6"
```

### 5. 重放 ChemDeep 补丁

```powershell
git am .kilo/vendor-patches/paper-search-mcp-nodejs/*.patch
```

如有冲突，只在 ChemDeep patch 层解决，不要把解决过程重新揉回 vendor commit。

## 验证清单

在 `paper-search-mcp-nodejs/` 下至少执行：

```powershell
npm install
npm run build
npm test
npm run lint
```

同时做一次 ChemDeep 回归验证：

- `search_papers` 基础能力仍然可用
- `config/paper-search-mcp-nodejs.env` 仍然被正确加载
- Lanfanshu / mirror fallback 行为符合 ChemDeep 预期
- MCP tool dispatch 未被上游改坏
- 上游已有平台搜索能力未被本地补丁误伤

## 维护规则

- 优先跟 release/tag，不要长期追 `main`
- 能新增 helper/module，就不要持续重写上游高频文件
- ChemDeep 私有说明优先写在主仓库文档，不要过多改上游 README
- 对 `handleToolCall.ts` 这类高冲突文件，优先做注入式或包装式扩展
- Patch 数量变多时，继续拆小提交，不要堆成“大杂烩提交”

## 当前难度判断

- 现在的整理难度属于中等，不是需要推倒重来的级别
- 有利因素：`paper-search-mcp-nodejs/` 在当前主仓库里的路径历史很短，且本地改动已经自然分成两层
- 主要难点：上游后续如果继续改 `handleToolCall.ts`、`LanfanshuSearcher.ts`、`server.ts`，冲突仍会发生，但会集中在少数热点文件内

## 每次源库更新后，你的引用会怎样

- 只要 `paper-search-mcp-nodejs/` 的目录位置和入口文件路径不变，主仓库里对它的路径引用不会因为同步上游而自动失效
- 真正会变化的是 vendored 目录内部实现，需要重新应用 ChemDeep patch 并做回归验证
- 如果上游修改了你已经定制过的同一段逻辑，补丁会在重放时冲突；这时修的是补丁层，不是整仓库的引用关系
- 如果上游没有改到你的扩展点，通常只需要导入 vendor commit 后直接重放补丁即可
