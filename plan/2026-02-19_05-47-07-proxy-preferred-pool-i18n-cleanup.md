# Plan: 代理池选择修复 + 全中文收尾（避免 PROXY_REQUIRED 误判）

## Goal
- 当“默认代理池/域名路由代理池”被停用时，运行时不再误用停用池，自动回退到启用池，避免出现：代理池明明已启用且有节点，但仍被旧/停用池拖累导致 `PROXY_REQUIRED`。
- 后台页面不再出现明显英文文案（重点：`Increase Value` / `Decrease Value`）。
- 本地仓库保持干净，避免把包含敏感信息的临时文件误提交。

## Scope
- In:
  - 后端：proxy_routing 只在启用的代理池中选择入口（preferred pool 若停用则忽略）
  - 后端：导入接口残留英文错误文案中文化（导入 body / 写入 payload 失败）
  - 前端：全局处理 AntD InputNumber stepper 的英文 aria 文案（Increase/Decrease Value）
  - 仓库：补充 `.gitignore` 忽略本地临时/敏感文件（不进 git）
- Out:
  - 代理探测算法/黑名单策略的大改（本轮只修“停用池仍被选中”与 i18n 收尾）

## Assumptions / Dependencies
- 代理池“停用”语义：不应参与任何自动选择（/random、补全任务、图片代理下载）。
- AntD 的 `InputNumber` stepper aria-label 目前不可通过 locale 直接翻译，需要前端侧额外处理。

## Phases
1. 修复后端：preferred pool 若停用则忽略，并补齐单测覆盖
2. 修复前端：全局替换 InputNumber stepper 的英文 aria-label，并修复导入接口残留英文错误文案
3. 跑后端/前端测试，全量 `git push` 到 `test`

## Tests & Verification
- PRX-1000 -> `python -m pytest -q backend/tests/test_proxy_pool_routing.py`
- I18N-1001 -> `cd frontend && npm test && npm run typecheck`
- REPO-1002 -> `git status --porcelain=v1` 无多余未跟踪临时文件

## Issue CSV
- Path: issues/2026-02-19_05-47-07-proxy-preferred-pool-i18n-cleanup.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- `mcp__chrome-devtools__*`：用于复现实机页面问题与确认无英文残留（验收辅助）

## Acceptance Checklist
- [ ] 停用的 default/route pool 不会再被自动选中（优先使用启用池）
- [ ] `/admin` 页面不再出现 `Increase Value` / `Decrease Value`
- [ ] 导入接口错误文案中文化
- [ ] `.gitignore` 覆盖本地敏感/临时文件，避免误提交
- [ ] 后端/前端测试通过；逐 Issue commit 并 push 到 `test`

## Risks / Blockers
- 如果用户只配置了一个代理池并将其停用，则会被视为“未配置可用代理池”，按 `fail_closed` 规则拦截（符合预期）。

## Rollback / Recovery
- 逐 Issue 回滚对应 commit（每条 Issue 一个 commit），重新部署即可恢复上一版本行为。

## Checkpoints
- Commit after: PRX-1000, I18N-1001, REPO-1002

## References
- `backend/app/core/proxy_routing.py`
- `backend/app/api/admin/imports.py`
- `frontend/src/app/App.tsx`
- `frontend/src/pages/*`

