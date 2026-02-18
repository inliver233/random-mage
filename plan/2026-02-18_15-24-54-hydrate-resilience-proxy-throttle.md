---
mode: plan
task: "补全任务更稳：代理健康检查/粘性节点 + Pixiv 请求节流 + 自重试"
created_at: "2026-02-18T15:24:54"
complexity: complex
---

# Plan: 补全任务更稳：代理健康检查/粘性节点 + Pixiv 请求节流 + 自重试

## Goal
- `hydrate_metadata` 在代理不稳定/偶发失败时不再“卡死/频繁 NO_TOKEN_AVAILABLE”，而是自动切换可用节点并持续推进任务。
- 对 Pixiv 请求增加节流（间隔 + 抖动），避免过于频繁触发风控/限流。
- 当出现可恢复的网络/代理错误时，任务以 **defer** 方式自重试，避免进入 DLQ。

## Scope
- In:
  - 为 `hydrate_metadata` 增加 Pixiv 请求节流（最小间隔 + 随机抖动），配置来源：`admin/settings` 的 `rate_limit.*`
  - 代理/网络失败识别：对“疑似代理问题”的错误优先归因到代理节点（更新 `proxy_endpoints` 健康字段 + 快速临时拉黑），并在同一令牌下尝试其他入口
  - 粘性节点：当故障切换到新入口后，自动写入 `token_proxy_bindings.override_*`（带 TTL），使后续补全持续使用同一可用入口
  - 错误策略：只有当所有令牌都不可用（禁用/退避）时才 defer；可恢复网络错误不应导致 job attempt 累计直至 DLQ
- Out:
  - 不更改 easy-proxies 项目本体；仅在本项目侧增强容错与可观察性

## Assumptions / Dependencies
- 代理池内存在多个可用入口（multi-port/hybrid 场景），才能实现稳定节点切换；若池内仅 1 个入口，则只能“节流 + 自重试”
- 运行时设置通过 `admin/settings` 写入 `runtime_settings`，worker 会在每次补全时读取（`load_runtime_config`）

## Phases
1. 生成本批次 issues CSV（2 条）
2. 逐条 issue 闭环（每条 1 commit + push）
3. 全量回归（backend pytest + frontend vitest/typecheck），更新 Regression 状态并 push

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: `issues/2026-02-18_15-24-54-hydrate-resilience-proxy-throttle.csv`
- Must share the same timestamp/slug as this plan.

## Acceptance Checklist
- [ ] 可通过设置节流参数让补全请求“有间隔”，并默认不会高频轰炸 Pixiv
- [ ] 代理不稳定时：会自动切换节点并把可用节点“粘住”（override TTL）
- [ ] 可恢复错误不会导致 job 很快 DLQ；会 defer 自重试并在 tokens 全不可用时清晰提示原因/下一次重试时间
- [ ] backend + frontend 全量测试通过并 push

## References
- `backend/app/jobs/handlers/hydrate_metadata.py`
- `backend/app/core/proxy_routing.py`
- `backend/app/jobs/handlers/proxy_probe.py`
- `frontend/src/pages/SettingsPage.tsx`
