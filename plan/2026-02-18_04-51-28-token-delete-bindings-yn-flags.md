---
mode: plan
task: "令牌删除/禁用生效 + 绑定固定性说明 + R18/AI 用 Y/N 展示"
created_at: "2026-02-18T04:51:28"
complexity: medium
---

# Plan: 令牌删除/禁用生效 + 绑定固定性说明 + R18/AI 用 Y/N 展示

## Goal
- 令牌管理页支持**删除令牌**；禁用令牌后，补全任务不会再使用该令牌。
- 令牌与代理绑定页展示更清晰：绑定是否固定、绑定更新时间、以及“为何所有令牌都绑定到同一入口”的原因可解释。
- 图片列表里 `R18` / `AI` 不再显示 `0/1/2` 这类不直观数字，改为更明确的 `Y/N`（未知则 `-`）。

## Scope
- In:
  - Backend：新增 `DELETE /admin/api/tokens/{token_id}`，并保证删除后相关绑定数据一致。
  - Backend：补全任务（hydrate/backfill）在获取 access token 前校验 `enabled`，禁用令牌不参与补全。
  - Frontend：Tokens 页增加删除按钮（带二次确认）并刷新列表。
  - Backend/Frontend：Bindings 列表返回绑定 `created_at/updated_at`，前端增加“固定性/更新时间/入口数量”提示，解释单入口 pool 导致全绑定同一入口的现象。
  - Frontend：Images 页 `R18/AI` 渲染为 `Y/N`。
- Out:
  - 不改动 easy-proxies 本体；不尝试在本项目侧“猜测/还原” pool 内部真实命中节点端口。

## Assumptions / Dependencies
- `token_proxy_bindings.token_id` 已设置 `ON DELETE CASCADE`；即使 SQLite 外键未启用，也会在 API 层做显式清理以保证一致性。
- 绑定是“本项目侧入口（host:port）”的固定分配；若入口本身是上游 pool，则上游可能内部轮询节点，这属于上游行为。

## Phases
1. 生成 issue CSV（3 条）
2. Issue 逐条闭环（每条 1 commit + push）
3. 批次回归（backend pytest + frontend test/typecheck），更新 Regression 状态并 push

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: `issues/2026-02-18_04-51-28-token-delete-bindings-yn-flags.csv`
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none

## Acceptance Checklist
- [ ] Tokens 页可删除令牌；删除后列表与绑定数据一致
- [ ] 禁用令牌后，补全任务不会再使用该令牌（必要时会跳过并选择其他启用令牌；若无可用令牌则 defer/报错清晰）
- [ ] Bindings 页能清晰说明“绑定固定性/更新时间/为何全绑定同一入口”
- [ ] Images 页 `R18/AI` 显示为 `Y/N`（未知为 `-`），避免 0/1 语义歧义
- [ ] backend + frontend 回归通过并 push 到 `test`

## Risks / Blockers
- 运行中的补全任务可能在禁用发生前已拿到 access token；本批次会确保在“使用 access token 前”阻止禁用令牌继续使用，以达到快速生效。

## Checkpoints
- 每个 issue 1 commit（同 commit 更新对应 issues CSV 状态），并 `git push origin test`。

## References
- `backend/app/api/admin/tokens.py`
- `backend/app/jobs/handlers/hydrate_metadata.py`
- `backend/app/api/admin/bindings.py`
- `frontend/src/pages/TokensPage.tsx`
- `frontend/src/pages/BindingsPage.tsx`
- `frontend/src/pages/ImagesPage.tsx`
