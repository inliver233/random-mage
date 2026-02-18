---
mode: plan
task: "随机推荐权重系统（illust_type + 可配置质量加权 + 可视化管理页）"
created_at: "2026-02-18T17:23:26"
complexity: complex
---

# Plan: 随机推荐权重系统（illust_type + 可配置质量加权 + 可视化管理页）

## Goal
- 默认 `GET /random` 在“不指定任何筛选参数”的情况下，更大概率返回高质量图片（收藏/浏览/评论更高 + 分辨率更高），而不是纯随机。
- 补全任务落库 Pixiv 作品类型 `illust_type`（插画/漫画/动图），以支持“漫画权重=0（不返回漫画）”等策略控制。
- 管理后台新增“推荐策略”页面：可视化展示当前评分公式/权重/倍率；支持在线修改并保存（runtime settings，无需重启容器）。
- 支持对 AI 图片、漫画等类别设置额外倍率（例如：AI=0.5，漫画=0），并提供预览/试运行能力。

## Research Summary（调查结论）
- Pixiv App API 的 `illust/detail` 返回字段包含热度相关信号（如 `total_bookmarks/total_view/total_comments`）与作品类型字段（`illust_type`），可用于“质量评分 + 类别权重”的随机推荐。
- `illust_type` 约定：`0=插画(illust) 1=漫画(manga) 2=动图(ugoira)`；AI 相关字段可通过 `illust_ai_type` 判断。

## Scope
- In:
  - Backend:
    - `images.illust_type` 数据库列与索引
    - `hydrate_metadata` 补全写入 `illust_type`
    - `/random` 质量评分支持权重配置（score_weights）+ 类别倍率（multipliers）+ 选择模式（weighted/best）
    - `admin/settings` 支持读写 `random.defaults.recommendation`
    - 单元/集成测试覆盖新增行为
  - Frontend:
    - 新增“推荐策略”管理页（全中文），可编辑并保存 recommendation 配置
    - 提供“预览”按钮：调用 `/random?format=json` 展示 debug（picked_by/quality_score/倍率等）
  - Docs:
    - 更新 `API契约-详细.md`：补齐 `illust_type` 字段与 recommendation 配置说明
- Out:
  - 不做个性化推荐/审美模型/embedding。
  - 不引入 Redis/ES 等外部依赖。

## Assumptions / Dependencies
- 运行时设置通过 `admin/settings` 写入 `runtime_settings`，接口侧与 worker 侧均可读取生效。
- 现有补全任务已能获取并写入 bookmark/view/comment/tags/width/height 等质量信号字段。

## Phases
1. 生成本批次 issues CSV（5 条）
2. 逐条 issue 闭环（每条 1 commit + push）
3. 全量回归（backend pytest + frontend vitest/typecheck），更新 Regression 状态并 push

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`
- Smoke（手工）：
  - 保存 recommendation 后，`/random?format=json` 的 `debug` 显示 `quality_*` 字段与倍率来源
  - 将 `multipliers.manga=0` 后，多次请求不再返回 `illust_type=1`

## Issue CSV
- Path: `issues/2026-02-18_17-23-26-random-recommendation-weights-ui.csv`
- Must share the same timestamp/slug as this plan.

## Acceptance Checklist
- [ ] `images.illust_type` 可被补全任务写入（含多页作品），并可用于推荐逻辑
- [ ] `/random` 默认走质量加权推荐，且支持按 runtime settings 调参
- [ ] 后台 Settings API 可读写 `random.defaults.recommendation`（严格校验）
- [ ] 新增“推荐策略”页面：全中文、可保存、可预览、无乱码
- [ ] backend + frontend 全量测试通过并 push 到 `origin/test`

## Risks / Blockers
- 冷启动数据：大量图片 `illust_type/热度字段` 为空时，推荐效果会退化；需配合补全覆盖率提升。
- 配置风险：倍率/温度设置不当可能导致 `NO_MATCH`；需要在页面中给出明确提示与推荐默认值。

## Rollback / Recovery
- 可通过回滚本批次 commits 恢复旧推荐逻辑；数据库新增列为向后兼容（允许 NULL）。

## Checkpoints
- Commit after: 每条 Issue 闭环完成（含更新 CSV 状态）后立即 push

## References
- `backend/app/jobs/handlers/hydrate_metadata.py`
- `backend/app/api/public/random.py`
- `backend/app/api/admin/settings.py`
- `frontend/src/pages/PlaygroundPage.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `API契约-详细.md`

