---
mode: plan
task: "代理体系修复（easy_proxies 兼容/探测可靠性/绑定可用性）+ 审计日志可用"
created_at: "2026-02-17T02:51:07"
complexity: complex
---

# Plan: 代理体系修复 + 审计日志可用

## Goal
- `GET /admin/audit` 页面可正常加载，并能看到后台操作的审计记录（至少对写操作落盘）。
- easy_proxies 接入不再“看似导入很多但实际只有一个入口/绑定无法用”，能给出明确提示与可操作的解决路径。
- 代理健康探测默认更贴近真实业务（Pixiv），减少误判导致的“节点全红/全拉黑/无法路由”。

## Scope
- In:
  - 后端补齐 `/admin/api/audit` 列表接口；补齐 admin 写操作审计落库（不记录敏感 body）。
  - easy_proxies 导入：密码可选、导出结果去重、对 pool 模式（单入口重复导出）给出告警与建议（multi-port/hybrid）。
  - 代理探测：默认探测目标改为 Pixiv 轻量 URL；前端允许自定义目标/超时/并发（可选）。
  - 绑定：当代理容量不足时，前端提示更明确，并支持“允许超出容量继续计算”（用于 easy_proxies 单入口场景）。
- Out:
  - 不改动 easy_proxies 项目本身（仅在本项目侧做兼容与指引）。
  - 不引入新外部服务（Redis/消息队列等）。

## Phases
1. 审计日志：补齐 API + 落库（中间件）+ 测试。
2. easy_proxies：导入兼容增强（去重/告警/密码可选）+ worker auto refresh 配置对齐 + 测试。
3. 代理探测：默认目标优化 + 可配置探测参数（UI/接口）+ 测试。
4. 绑定：容量不足时的“继续计算”能力 + UI 提示 + 测试。
5. 全量回归：backend pytest + frontend vitest/typecheck；更新本批次 issues CSV Regression 状态。

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: `issues/2026-02-17_02-51-07-proxy-audit-fixes.csv`

