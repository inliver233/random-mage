# Plan: 代理稳定性（PROXY_REQUIRED 可诊断）+ illust_type 全链路展示

## Goal
- 在代理池暂不可用/全部被拉黑时，/random 与补全任务能返回“可诊断、可操作”的信息并进行更合理的延后重试；同时补全/图片管理页面补齐 illust_type（插画/漫画/动图）字段的补全、展示与筛选。

## Scope
- In:
  - 后端：proxy 选择失败时的错误细化（reason + pool 统计 + next_available_at），hydrate_metadata 的 defer 逻辑，代理节点列表 blacklisted 状态判定
  - 后端：summary / images 列表补齐 illust_type 与 missing=illust_type
  - 前端：HydrationPage/ImagesPage 展示与筛选 illust_type
- Out:
  - easy_proxies 的 hybrid/multi-port 自动扩展导入（本轮仅把“无可用代理”的诊断与重试做稳）
  - 随机推荐算法的进一步升级（已有推荐页面，本轮不改权重策略本身）

## Assumptions / Dependencies
- 代理黑名单时间使用 ISO UTC 文本（`YYYY-MM-DDTHH:MM:SS.mmmZ`）存储，字符串比较可用于“是否过期”的判断。
- 代理池与入口数量取数仅在“无可用代理”错误路径触发，避免影响正常请求性能。

## Phases
1. 实现 PRX-0900：proxy_routing 失败细化 + hydrate defer 使用 next_available_at + 修复 proxies list blacklisted 判定
2. 实现 IMG-0900：summary/images/hydration/images UI 全链路补齐 illust_type
3. 跑针对性测试与全量回归，逐 Issue commit 并 push 到 `test`

## Tests & Verification
- PRX-0900 -> `python -m pytest -q backend/tests/test_proxy_pool_routing.py backend/tests/test_job_handler_hydrate_metadata.py backend/tests/test_error_codes.py`
- IMG-0900 -> `python -m pytest -q backend/tests/test_admin_hydration_stats.py backend/tests/test_admin_images_list_filters.py` + `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: issues/2026-02-18_18-58-32-proxy-required-illust-type-ui.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none（本轮主要为代码修复 + 本地测试 + git push）

## Acceptance Checklist
- [ ] /random 在无可用代理时返回 PROXY_REQUIRED 且 details 可诊断（reason + pool 统计 + next_available_at）
- [ ] hydrate_metadata 在同场景 defer 到 next_available_at（优先）并保持任务不进入 DLQ
- [ ] 代理节点列表 blacklisted 状态仅在黑名单仍生效时显示
- [ ] 补全/图片管理页面补齐 illust_type 的补全字段选项、覆盖率统计、列表展示与 missing 筛选
- [ ] 后端/前端测试通过；逐 Issue commit 并 push 到 `test`

## Risks / Blockers
- 如果代理服务整体不可用（网络故障/认证失效），系统只能延后重试并提供诊断信息，无法“无代理”完成 Pixiv 访问。

## Rollback / Recovery
- 逐 Issue 回滚对应 commit（每条 Issue 一个 commit），重新部署即可恢复到上一版本行为。

## Checkpoints
- Commit after: PRX-0900, IMG-0900

## References
- `backend/app/core/proxy_routing.py`
- `backend/app/jobs/handlers/hydrate_metadata.py`
- `backend/app/api/admin/images.py`
- `frontend/src/pages/HydrationPage.tsx`
- `frontend/src/pages/ImagesPage.tsx`

