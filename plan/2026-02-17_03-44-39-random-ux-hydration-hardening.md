---
mode: plan
task: "随机系统体验硬化（NO_MATCH 友好化 + 元数据自愈 + 全面汉化）"
created_at: "2026-02-17T03:44:39"
complexity: complex
---

# Plan: 随机系统体验硬化（NO_MATCH 友好化 + 元数据自愈 + 全面汉化）

## Goal
- 让用户在“刚导入图片但尚未补全元数据”的冷启动阶段，也能顺利测试 `/random`，并得到**明确、全中文**的下一步指引。
- 让 `urls.proxy`（`/i/{image_id}.{ext}`）在被访问时具备“自愈能力”：当发现元数据缺失时自动触发 opportunistic hydrate，从而逐步提升 `width/height/x_restrict/tags/popularity` 覆盖率，最终提升质量随机的效果。
- 管理后台的随机调试（Playground）错误显示与其它页面一致：不再直接显示英文 message；当 `NO_MATCH` 时展示可操作的 hints（例如建议关闭 `r18_strict`、触发补全）。

## Research Summary（联网调研结论）
- Pixiv App API `illust/detail` 的 `illust` 对象中存在热度字段（`total_bookmarks/total_view/total_comments`）、标签（`tags`）、几何信息（`width/height`）与 `x_restrict` 等字段，可作为“质量随机”的信号源。字段与获取途径已落盘：`docs/research/pixiv-illust-metadata.md`。
- 冷启动阶段 `x_restrict` 可能为 `NULL`，此时若 `r18=0 & r18_strict=1` 会把“未知”排除，导致 `/random` 返回 `NO_MATCH`；因此需要提供更友好的提示与可执行路径（补全或放宽 strict）。

## Current Implementation（本地调查结论）
- `/random` 已实现 Tournament Selection 的质量优先随机（收藏为主、分辨率为辅），但在元数据缺失时质量评分会退化为 0 分，体验上像“纯随机”。
- `/random` 的 `NO_MATCH` 响应包含英文 `message` 与英文 `suggestions`；用户直接请求 API（或在 Playground 的 image/redirect 模式）会看到英文。
- `/i/{image_id}.{ext}` 目前只负责代理回源，不会：
  - 标记图片成功/失败（无法积累坏图/健康信息）
  - 触发 opportunistic hydrate（导致“我一直访问 proxy，但 width/height 还是 null”）
- Playground 对 image/redirect 的错误解析走自定义逻辑，未复用 `apiJson` 的中文翻译规则，导致同一个错误在不同页面显示语言不一致。

## Design（方案）
- Public API（后端）：
  - `/random` 的 `NO_MATCH`：统一中文 `message` + 中文 `suggestions`（保持 `details.hints.applied_filters` 不变）。
  - `/i`：在返回流之前基于 DB 行判断是否“需要补全”，若缺失则 enqueue opportunistic hydrate（按 illust_id 去重）；对上游 403/404/stream error 等按既有策略记录失败。
- Admin UI（前端）：
  - Playground：统一使用与 `apiJson` 一致的错误消息格式化（中文优先），并在 `NO_MATCH` 时把 `details.hints`（filters/suggestions）清晰展示出来。
  - 导入：默认勾选“导入后立即补全元数据”，并给出说明（冷启动质量/筛选依赖元数据覆盖率）。
- 文档：
  - `数据库结构-详细DDL.md` 补齐 images 热度字段（bookmark/view/comment）以匹配实际 schema，避免“文档与实现不一致”。

## Scope
- In:
  - `/random` NO_MATCH 文案中文化 + hints 可读性增强
  - `/i` 端点的元数据自愈（opportunistic hydrate）与失败标记
  - Playground 错误展示一致性 + NO_MATCH hints 展示
  - 导入默认开启补全（前端默认值与说明）
  - 数据库 DDL 文档与实际实现对齐
- Out:
  - 不引入新的推荐模型/外部依赖（Redis/ES）
  - 不改变现有 `/random` 参数语义（只增强提示与自愈）

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: issues/2026-02-17_03-44-39-random-ux-hydration-hardening.csv

## Risks / Notes
- `/i` 端点新增写库操作可能带来额外开销；实现上需避免“每次请求都写库/入队”，优先只在“缺失元数据或上游失败”时触发。
- 文案中文化需要同时兼顾：API 直接调用（用户看 JSON）与 UI 展示（用户看页面）。

## References
- `backend/app/api/public/random.py`
- `backend/app/api/public/images.py`
- `backend/app/jobs/enqueue.py`
- `frontend/src/pages/PlaygroundPage.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/pages/ImportPage.tsx`
- `docs/research/pixiv-illust-metadata.md`
- `数据库结构-详细DDL.md`

