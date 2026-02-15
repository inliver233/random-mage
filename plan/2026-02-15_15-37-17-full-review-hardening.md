---
mode: plan
task: "全量 Review & 功能补全（可运营/可管理/默认行为一致）"
created_at: "2026-02-15T15:37:17"
complexity: complex
---

# Plan: 全量 Review & 功能补全（可运营/可管理/默认行为一致）

## Goal
- 能批量导入图片（支持大文本/文件），并能在后台追踪导入进度、错误原因与回滚。
- Token 池 + 代理池 + 绑定关系可在前端全套管理（启停/权重/覆盖代理/探测），无需手工改库或重启服务。
- Hydrate 能补全 tags/作者/R18/AI/热度等元数据，并能直观看到缺失覆盖率与任务进度。
- `/random` 默认更偏向高质量图片，并且其默认参数与“系统设置”一致（避免“设置页改了但接口没生效”的错觉）。

## Scope
- In:
  - `/random` 默认参数（attempts/r18_strict/fail_cooldown/strategy/quality_samples）统一走 runtime settings（可在 Settings 页面修改）。
  - Token 管理补齐“编辑/启停/权重调整”等缺失能力。
  - Proxy 节点管理补齐“启停”能力，并修复“无密码代理也因加密未配置而失败”的导入体验问题。
  - Bindings 页面补齐“override/clear override”全套前端操作，提升 token↔proxy 关系可观测性。
  - 导入页面增强：明确支持的 URL 格式、展示预览与错误行（避免“看着导入成功但库里没图”的困惑）。
  - 文档落盘：Pixiv App API 元数据字段与 OAuth 刷新关键头（来自联网调研）引用补强。
- Out:
  - 不引入 Redis/ES/新队列服务。
  - 不做审美模型/ML 推荐（仅基于可拿到的元数据做质量随机）。

## Assumptions / Dependencies
- 运行环境按 `deploy/docker-compose.yml`（api+worker 共享 `../data` volume）。
- Pixiv OAuth refresh 仍可用（Android App headers + X-Client-Hash 机制）。
- 现有测试基线通过（pytest + vitest + typecheck）。

## Phases
1. 全量 review 落盘（问题清单与风险点）+ batch 初始化（plan + issues CSV）。
2. 补齐缺失的管理能力（tokens/proxies/bindings）并确保中文 UI + request_id 可追踪。
3. 统一 `/random` 默认行为与 Settings（并在 JSON debug 暴露来源，便于解释）。
4. 导入 UX 增强（错误可见 + 支持格式说明 + worker 未启动时的指引更明确）。
5. 全量回归（backend pytest + frontend vitest/typecheck）+ Regression 状态提交。

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: issues/2026-02-15_15-37-17-full-review-hardening.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none（本批次以 repo 内测试与代码审查为主）

## Acceptance Checklist
- [ ] Settings 中修改随机默认参数后，未显式传参的 `/random` 立即生效且 debug 显示来源
- [ ] Tokens/Proxies/Bindings 页面可完成启停、探测、绑定重算与覆盖代理操作
- [ ] 导入页面能清楚展示错误行与预览，导入详情页能明确提示 worker 状态
- [ ] 后端/前端测试全绿，issues CSV 全部 DONE + Regression DONE

## Risks / Blockers
- Pixiv 侧鉴权规则变更（X-Client-Hash、UA 等）会导致 refresh/hydrate 失败；需持续验证与可回退配置。
- 运营体验与安全取舍：降低严格 R18 过滤可能提高“未标记图片”命中率；需通过 Settings 可控。

## Rollback / Recovery
- 所有变更保持向后兼容：新增字段/接口为可选；默认值从 runtime settings 读取，出错回退到安全默认。
- 若出现不可预期行为，可回退单个 issue commit（每个 issue 一个 commit）。

## Checkpoints
- Commit after: 每条 issue 完成后立即 commit + push（遵循 `docs/engineering/git-workflow.md`）

## References
- `docs/research/pixiv-illust-metadata.md`
- `backend/app/api/public/random.py`
- `backend/app/api/admin/settings.py`
- `frontend/src/pages/*`
