---
mode: plan
task: "代理池与后台稳定性硬化（easy_proxies 兼容 + 全中文错误 + 异常 JSON）"
created_at: "2026-02-17T05:04:22"
complexity: complex
---

# Plan: 代理池与后台稳定性硬化（easy_proxies 兼容 + 全中文错误 + 异常 JSON）

## Goal
- easy_proxies 导出代理 URI（包含 `@` 或 URL 编码）可被系统正确导入、探测与路由；绑定计算支持 pool 模式（通过权重表达节点数）。
- `/admin/audit`、`/admin/jobs` 等页面遇到后端异常时仍返回统一 JSON（带 request_id），前端可展示中文错误而不是“加载失败/空白”。
- API 错误 message 全中文（至少覆盖常见 Unsupported/Invalid/Upstream/Encryption not configured 等文案），减少用户直接调用 API 时的困惑。

## Scope
- In:
  - `parse_proxy_uri` 增强：支持 URL-encoded userinfo decode（`%40` 等），并补充单测覆盖。
  - bindings recompute 增强：容量与分配按 `proxy_pool_endpoints.weight` 计算（权重=容量倍率）；前端错误提示可展示权重汇总信息。
  - 后端稳定性增强：新增全局未捕获异常的 JSON handler；对英文 ApiError message 做统一中文化（保持 error code 不变）。
  - 前端说明增强：ProxiesPage 增加 easy_proxies 使用说明（面板地址/访问密码、pool vs multi-port/hybrid、密码包含 `@` 的两种写法、权重建议）。
- Out:
  - 不修改 easy_proxies 项目本身（仅在本项目侧做兼容与指引）。
  - 不改变现有 API 字段与 error code（仅增强 message/details 与错误一致性）。

## Assumptions / Dependencies
- easy_proxies 的 `/api/export` 返回每行一个代理 URI；pool 模式下可能导出多行但入口重复；且可能不会对 `proxy_password` 做 URL 编码（导致 URI 中出现多个 `@`）。
- 权重默认 1；用户可在“代理池”页面把成员权重设置为“节点数”，从而让绑定/路由更贴近真实容量。

## Phases
1. 代理 URI 解析增强 + 测试
2. 绑定容量按权重计算 + 测试 + 前端展示
3. 全局异常 JSON + 错误文案中文化 + 测试
4. 代理页面说明增强 + 测试
5. 全量回归（backend pytest + frontend vitest/typecheck），更新本批次 issues CSV Regression 状态

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: `issues/2026-02-17_05-04-05-proxy-pool-i18n-hardening.csv`
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none

## Acceptance Checklist
- [ ] easy_proxies 导出 URI（`http://user:pass@123@host:port` 与 `%40` 编码版本）可正确 parse 并导入
- [ ] bindings/recompute 容量按权重计算；pool 模式可通过设置权重避免“容量不足”
- [ ] 任意未捕获异常返回 JSON error（含 request_id），前端不再出现“无法解析/空白”
- [ ] API error message 全中文（覆盖 Unsupported/Invalid/Upstream/Encryption not configured 等常见文案）
- [ ] backend+frontend 全量测试通过

## Risks / Blockers
- 全局异常 handler 会改变非 ApiError 的响应格式（从默认 HTML 变为 JSON）；需要确保前端与测试均能接受。
- 权重能力会让“单入口 pool”在绑定上看起来像多节点，需要在 UI 文案中明确解释含义，避免误解为“真实多入口”。

## Rollback / Recovery
- 若上线后发现某些客户端依赖 FastAPI 默认 500 HTML，可在全局异常 handler 中仅对 `/admin/api/*` 与 public API 返回 JSON，其他路径保留默认行为。

## Checkpoints
- 每个 issue 1 commit（同 commit 更新对应 issues CSV 状态），并 `git push origin test`。

## References
- `backend/app/core/proxy_uri.py`
- `backend/app/api/admin/bindings.py`
- `backend/app/core/errors.py`
- `backend/app/main.py`
- `frontend/src/pages/ProxiesPage.tsx`
