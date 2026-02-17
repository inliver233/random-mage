---
mode: plan
task: "代理展示清晰化 + 运维指引 + 质量随机 v2（收藏率参与评分）"
created_at: "2026-02-17T16:14:38"
complexity: complex
---

# Plan: 代理展示清晰化 + 运维指引 + 质量随机 v2（收藏率参与评分）

## Goal
- easy_proxies（pool / multi-port / hybrid）接入后，后台能**清晰解释**“这是单入口代理池还是多端口节点”，并能看懂与绑定关系的对应。
- 后台页面完全中文化（包含少量残留英文 UI 文案），并提升“是否已部署到最新版本”的可见性，避免用户误以为功能缺失。
- 质量随机策略进一步优化：在保持热路径性能的前提下，把“收藏率（bookmark/view）”纳入质量评分，让默认随机更偏向高质量图片。

## Scope
- In:
  - Admin Proxies：代理节点列表接口增加 `source/source_ref`，前端表格展示“来源/提示”，并强化 easy_proxies(pool/hybrid) 解释。
  - Admin Bindings：绑定页展示“节点#ID + 地址（掩码）”，使“单入口 pool”与“多端口节点”差异更直观。
  - Admin I18N：清理少量残留英文 UI 文案（如 Payload），并保证不引入编码乱码。
  - Ops：后台 Header 展示版本信息（来自 `/version`），并给出“需要重建镜像才能更新前端”的提示入口。
  - Random：质量评分引入收藏率（bookmark/view），并更新相关设计/接口文档。
- Out:
  - 不修改 easy_proxies 项目本身（仅在本项目侧增强兼容与可解释性）。
  - 不引入高成本的全表排序/扫描随机方案（仍保持 SQLite 读路径可控）。

## Assumptions / Dependencies
- easy_proxies 可能存在“单入口 pool”与“多端口节点”两类使用方式；单入口 pool 无法在本项目侧直接观测到 pool 内部选中的具体节点端口（除非上游额外提供可观测接口）。
- Docker 镜像在构建阶段会打包前端静态资源；更新代码后需要 `docker compose up -d --build` 才能看到最新 UI。

## Phases
1. 代理节点来源/提示字段（API + UI）增强
2. 绑定页展示优化（节点#ID + 地址/提示）
3. UI 残留英文清理（全中文）
4. Header 版本信息展示 + 升级提示
5. 质量随机评分 v2（收藏率参与）+ 文档更新
6. 全量回归（backend pytest + frontend vitest/typecheck），更新本批次 issues CSV Regression 状态

## Tests & Verification
- Backend: `.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- Frontend: `cd frontend && npm test && npm run typecheck`

## Issue CSV
- Path: `issues/2026-02-17_16-14-38-proxy-clarity-ops-quality-v2.csv`
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- none

## Acceptance Checklist
- [ ] Proxies 页可看到代理节点来源（manual / easy_proxies）与来源引用（面板地址），并有中文提示解释 pool/multi-port/hybrid
- [ ] Bindings 页能直观看懂“令牌 → 节点#ID → 地址（掩码）”的生效关系
- [ ] 后台 UI 不出现明显英文按钮/标题（保留 URL 等技术名词可接受）
- [ ] Header 可看到版本信息，并能提示“更新代码需要重建镜像”
- [ ] 质量随机评分纳入收藏率，默认随机更偏向高质量作品；文档同步更新
- [ ] backend+frontend 全量测试通过

## Risks / Blockers
- 对代理“模式”的判断只能做启发式提示：单入口 pool 无法在本项目侧直接展示 pool 内部实际选中节点端口。
- Header 每页展示版本信息会增加一次 API 调用；需确保缓存/请求频率可控。

## Rollback / Recovery
- 若 Header 版本请求带来额外开销，可改为仅在 Dashboard 加载或用 localStorage 缓存较长时间。
- 若收藏率项导致部分数据缺失时评分退化，可通过保持现有 log1p(bookmark) 主导来降低风险。

## Checkpoints
- 每个 issue 1 commit（同 commit 更新对应 issues CSV 状态），并 `git push origin test`。

## References
- `backend/app/api/admin/proxies.py`
- `frontend/src/pages/ProxiesPage.tsx`
- `frontend/src/pages/BindingsPage.tsx`
- `frontend/src/app/AdminLayout.tsx`
- `backend/app/api/public/random.py`
