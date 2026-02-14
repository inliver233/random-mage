---
mode: plan
task: "Admin 管理后台完善（Jobs/补全/图片/代理池/全量汉化）"
created_at: "2026-02-15T03:17:36"
complexity: complex
---

# Plan: Admin 管理后台完善（Jobs/补全/图片/代理池/全量汉化）

## Goal
- Docker Compose 启动后，无需进后台/命令行即可在前端完成：导入、查看图片、补全元数据、管理任务队列、管理令牌/代理/代理池/绑定、随机接口调试。
- 修复 `/admin/jobs` “加载失败/操作不可用/英文残留”等问题，并提供可自助排障的“版本信息/工作线程状态/覆盖率统计”。
- 全站可见文案中文化（含 Ant Design 默认文案），避免乱码与编码问题。

## Scope
- In:
  - 前端：Admin 路由保护、401 自动回登录、全局中文 Locale、主布局导航（全功能入口）、Jobs 可操作、补全覆盖率展示、图片管理增强、代理池管理页、版本信息展示、运维指令补充。
  - 后端：Jobs 详情接口、补全覆盖率统计接口（或扩展 summary）、图片管理（admin list/filter）接口、图片热度字段迁移与补全持久化。
  - 文档：Docker Compose up/down/升级/回滚/日志/重启指令补全。
- Out:
  - 不做完整的 E2E 浏览器自动化（当前用 vitest/pytest + 手工 smoke）。
  - 不引入 Redis/消息队列（仍用 SQLite jobs + worker）。
  - 不做“智能推荐算法/加权随机”的策略落地（先把数据结构与采集打通）。

## Assumptions / Dependencies
- 分支：所有提交仅在 `test` 分支（或 `test/*`）进行，并且 **每条 Issue 一个 commit 且 commit 后立即 push**（`docs/engineering/git-workflow.md`）。
- Issue CSV schema 必须严格符合 `issues/README.md` 且通过校验脚本：`.codex/skills/plan/scripts/validate_issues_csv.py`。
- 后端测试环境使用仓库自带虚拟环境：`.venv/backend_verify/Scripts/python.exe`。
- 用户要求不中断确认流程，本次跳过 “Reply CONFIRM” 交互，直接落盘 plan 与 issues（与 `.codex/skills/plan/SKILL.md` 的建议流程冲突时，以用户指令优先）。

## Phases
1. 体验与稳定性基线：路由保护/401 处理 + 全站中文 Locale + 导航布局升级 + 版本信息可见
2. 管理闭环：Jobs 可操作（重试/取消/DLQ/详情）+ 代理池管理页（CRUD+成员配置）
3. 数据完整性：补全覆盖率统计 + 图片管理增强（缺失过滤/单图补全）+ 热度字段迁移与补全持久化
4. 全量 review + 回归 smoke：记录证据、补齐残留英文/易用性缺口、更新 CSV regression 状态

## Tests & Verification
- Admin 401/路由保护：手工（无 token 访问 `/admin/jobs` 应跳转 `/admin/login`）+ `cd frontend && npm test && npm run typecheck`
- Jobs 动作：`pytest -q backend/tests`（新增/更新接口测试）+ 前端 vitest
- 补全覆盖率/图片筛选：`pytest -q backend/tests` + 前端 vitest；手工 smoke：创建补全任务后覆盖率随时间变化
- DB 迁移：`alembic upgrade head`（compose 启动时自动跑）+ `pytest -q backend/tests`（包含迁移后读写断言）
- 回归：`cd frontend && npm test && npm run typecheck` + `.venv/backend_verify/Scripts/python.exe -m pytest -q backend/tests`

## Issue CSV
- Path: issues/2026-02-15_03-17-36-admin-management-improvements.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- `functions.shell_command`: repo 搜索、运行测试、git 操作、生成/校验 CSV
- `functions.apply_patch`: 写入/修改 plan、CSV、代码与文档
- MCP: none

## Acceptance Checklist
- [ ] 未登录/失效 token 访问任意 admin 页自动回到登录页，并给出中文提示
- [ ] `/admin/jobs` 可正常加载并支持重试/取消/移入死信/查看详情
- [ ] “补全管理”页面能看到覆盖率/缺失字段统计，并能按缺失字段创建补全任务
- [ ] “图片管理”能按缺失字段筛选并支持单图手动补全
- [ ] “代理池管理”可在前端完成 CRUD 与成员配置，Bindings 能闭环
- [ ] 全站可见文案中文化（含 antd 默认文案），无乱码
- [ ] 版本信息可在后台直接查看（用于确认已升级）
- [ ] 回归测试通过或记录受限验收原因与风险

## Risks / Blockers
- SQLite 写放大：补全与使用统计引入额外写入可能影响低配机器；需要控制频率/批量更新，避免卡顿。
- DB 迁移风险：生产环境需先备份 `data/app.db*`；不提供 downgrade 时回滚只能靠备份恢复。
- 线上未更新镜像：若用户未 `docker compose up -d --build`，仍会看到旧的英文 UI；需在前端显式展示 `/version` 来协助确认。

## Rollback / Recovery
- 回滚代码：`git revert <sha>` 或切回旧版本并重新 build
- 回滚数据：按 `DockerCompose-部署与运维.md` 先 stop，再恢复 `data/app.db*` 备份文件

## Checkpoints
- Commit after: 每条 Issue 完成（含更新 CSV 状态）即 commit + push
- 批次末：统一回归通过后，提交一次仅更新 CSV 的 meta commit（Regression_Status= DONE）

## References
- `.codex/skills/plan/SKILL.md`
- `.codex/skills/plan/assets/_template.md`
- `issues/README.md`
- `docs/engineering/git-workflow.md`
- `docs/testing-policy.md`
- `DockerCompose-部署与运维.md`

