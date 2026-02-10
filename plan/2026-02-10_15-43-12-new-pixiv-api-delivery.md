---
mode: plan
task: "New Pixiv Random API (FastAPI+SQLite+React) end-to-end delivery (M0-M7)"
created_at: "2026-02-10T15:43:12"
complexity: complex
---

# Plan: New Pixiv Random API — 工程交付（M0→M7）

## 冲突点与采用规则来源（必须先说明）
- Issue CSV 字段：用户要求的 `priority/milestone/component/...` 等列与本仓库强制 CSV schema 冲突；本仓库要求表头 **必须**严格等于 `issues/README.md` 与 `validate_issues_csv.py` 的 `REQUIRED_COLUMNS`。因此本计划采用仓库 schema，并把 `priority/milestone/component/estimate/commands` 等元数据写入每行 `Notes/Test_Method/Acceptance`（来源：`issues/README.md`、`.codex/skills/plan/scripts/validate_issues_csv.py`）。
- Plan 命名：用户要求 `plan/YYYY-MM-DD_plan.md`；仓库 plan 规范要求 `plan/YYYY-MM-DD_HH-mm-ss-<slug>.md` 且与 Issue CSV timestamp/slug 匹配（来源：`.codex/skills/plan/SKILL.md`、`.codex/skills/plan/scripts/create_plan.py`）。本仓库内以 timestamp/slug 文件为权威，同时额外提供用户格式的同日 plan 便于查阅。
- “CONFIRM”交互：仓库 plan skill 文档建议写文件前请求确认；但用户要求不中断提问且明确要求立刻产出文件。本次视为用户已明确授权创建 plan 与 issues 文件，继续执行（来源：用户指令优先于“交互建议”）。

## 约束来源清单（扫描结果）
- Issue CSV 规则：`issues/README.md`
- Issue CSV 校验器：`.codex/skills/plan/scripts/validate_issues_csv.py`
- CSV 闭环执行流程（分支/提交/推送/状态机）：`.codex/prompts/issues_csv_execute.md`
- Git 工作流（强制 test 分支 + 每 Issue 一个 commit + push）：`docs/engineering/git-workflow.md`
- 测试策略：`docs/testing-policy.md`
- 安全红线（敏感信息/脱敏/鉴权/合规/测试门禁）：`安全规范-敏感信息与合规.md`
- 需求总纲与路线图：`new随机api开发文档.md`
- DB 详细 DDL：`数据库结构-详细DDL.md`
- API 契约：`API契约-详细.md`
- 前端原型：`前端页面-详细原型.md`
- Worker 与稳定性：`任务系统-Worker与稳定性.md`
- Docker 运维 Runbook：`DockerCompose-部署与运维.md`
- 高层 TODO（需再细化）：`TODO-全量Issue拆分.md`

## Goal
- 将 `new-pixiv-api实现/` 从“仅文档”交付为可运行工程：`backend/`(FastAPI+SQLite+Worker) + `frontend/`(React+AntD) + `deploy/`(compose) + `scripts/`(一键测试)。
- 以 `issues/<timestamp>-<slug>.csv` 为单一任务边界与状态源：每个 issue 完成必须实现+测试+更新 CSV+commit+push 到 `test` 分支。

## Scope
- In:
  - Public API：`/random`、`/i/{image_id}.{ext}`、`/images`、`/images/{id}`、`/tags`、`/authors`、legacy 路由。
  - Admin API：`/admin/api/*` 全量按契约实现（导入、tokens、proxies、pools、bindings、jobs、settings、hydration-runs、auth）。
  - Worker：SQLite jobs queue（claim/lock TTL/重试/退避/DLQ）+ handlers（import/hydrate/heal/probe/easy_proxies）。
  - 安全：敏感字段加密落库 + write-only + 日志全局脱敏 + /admin 与 /metrics 保护 + 自动化测试门禁。
  - 部署：Docker Compose（api+worker；web 可选）+ 备份/升级/回滚 SOP。
- Out:
  - 不落盘图片内容（仅反代/缓存头）。
  - 不引入 Redis（MVP）。
  - 不做 imgproxy/变换 URL（后续 P1）。
  - 不做完整“对外计费/API key 系统”（后续 P1）。

## Assumptions / Dependencies
- 代码落点：直接在本仓库 `new-pixiv-api实现/` 下创建 `backend/ frontend/ deploy/ scripts/`（便于按本仓库 issue/plan 规范闭环）。
- SQLite 版本：运行环境 SQLite >= 3.35（支持 `RETURNING`），否则 claim 实现需降级为事务 + SELECT/UPDATE（将作为兼容 issue 处理）。
- Admin 鉴权默认选型：Bearer JWT（`POST /admin/api/login` 返回 token），Secret 来自 `SECRET_KEY` 环境变量；仅支持单管理员账号（用户名/密码来自环境变量；密码只在内存校验，不落库）。
- 字段加密默认选型：Fernet（`FIELD_ENCRYPTION_KEY` 环境变量），用于 `refresh_token_enc` 与 `password_enc`；明文永不回显、永不落日志。
- 出站 HTTP：统一使用 `httpx`，默认支持超时/取消/流式；代理路由策略按配置 `PROXY_ROUTE_MODE` 走 allowlist/pixiv_only。
- Rate limit：MVP 采用“进程内”限流（单实例有效）；生产推荐在反代层追加限流（记录在 runbook）。

## Milestones（M0→M7）与 DoD
- M0 基础：目录结构+依赖+FastAPI 启动+SQLite(WAL/busy_timeout/foreign_keys)+Alembic 可迁移+日志脱敏+一键测试脚本可跑+Docker compose skeleton。
- M1 导入+最小随机闭环：导入 URL 入库；`/random` 仅查 DB；`/i/*` 流式反代；legacy 路由可用；无元信息也可跑通。
- M2 代理池闭环：代理端点导入/探测/健康；easy_proxies 导入；随机/worker 出站可走代理且可 failover。
- M3 Token 闭环：refresh_token 加密落库；tokens CRUD；test-refresh job；token 选择策略与退避。
- M4 Worker+补全/修复闭环：jobs claim/重试/DLQ；hydrate_metadata/heal_url handlers；hydration_runs 管控（pause/resume/cancel）。
- M5 强筛选闭环：r18/orientation/min_*/tags/user/illust/ai_type/time 全量支持；NO_MATCH hints；性能/正确性测试覆盖 random_key 方案。
- M6 管理后台闭环：React+AntD+TanStack Query；按原型完成页面与关键按钮动作；敏感字段 UI write-only（保存后不回显）。
- M7 观测/安全/运维闭环：/metrics 与关键指标；审计与请求日志；CI 门禁（安全泄露测试必须 fail）；备份/升级/回滚 SOP 完整；docker compose 生产建议。

## 依赖图（文字版）
- M0 → M1（DB/迁移/基础 API/测试脚本）→ M2（proxy 表+API+worker 出站）→ M3（token 表+加密+Pixiv oauth）→ M4（jobs 表+worker+hydrate/heal）→ M5（filters+tags/authors/images API）→ M6（admin web）→ M7（metrics/audit/ci/runbook）。

## 回归策略（按批次）
- 每个 Issue：优先跑该 issue 的最小测试集（pytest/vitest/类型检查/构建），写入该行 `Test_Method` 并在 `Notes` 留证据摘要。
- 每个 Milestone 完成：运行 `scripts/test_all.ps1`（后端+前端）并记录结果摘要到 milestone 收尾 issue 的 `Notes`。
- 全量完成：跑一次全回归后，将 CSV 全部 `Regression_Status=DONE` 并提交一次 meta commit（仅 CSV）。

## 发布/回滚/备份策略（与迁移一致）
- 备份：遵循 `DockerCompose-部署与运维.md`，优先停机复制 `/data/app.db`；或在线 `.backup` 到 `/backups/`。
- 升级：备份 → 拉取/构建新镜像 → `alembic upgrade head` → 重启 api/worker → smoke（/healthz、/random?format=json）。
- 回滚：stop → 恢复 DB 备份（或 alembic downgrade 若提供）→ 启动旧镜像。

## Phases
1. M0：工程骨架 + 测试脚手架 + Docker skeleton
2. M1：导入 + /random + /i/*（热路径不触网）
3. M2→M7：按 issues CSV 依赖顺序逐步闭环

## Tests & Verification
- 安全：敏感字段不回显/不落日志（pytest 必测，失败即阻断）。
- 随机：禁止 `ORDER BY random()`；random_key 策略正确性+性能回归（pytest）。
- 并发：SQLite WAL + busy_timeout + 应用层重试；jobs claim 多 worker 不重复（pytest/integration）。
- 前端：vitest（组件/请求层）+ 最小 e2e（后续可选 Playwright）。

## Issue CSV
- Path: issues/2026-02-10_15-43-12-new-pixiv-api-delivery.csv
- Must share the same timestamp/slug as this plan.

## Tools / MCP
- context7:*：查询 FastAPI/httpx/SQLAlchemy/Alembic/AntD/TanStack Query 的最新用法（按需）。
- chrome-devtools:*：前端页面联调与最小 e2e（按需）。

## Acceptance Checklist
- [ ] `backend` API + `worker` 可通过 docker compose 启动
- [ ] `/random` 热路径不触网且不使用 `ORDER BY random()`
- [ ] `/admin` 与 `/metrics` 受保护
- [ ] refresh_token / proxy password 不回显、不落库明文、不落日志（测试门禁）
- [ ] issues CSV 全部 `Dev_Status=DONE` 且全回归通过

## Risks / Blockers
- push 可能因 remote/权限失败：按 `issues_csv_execute.md` 记 `validation_limited` 与错误输出（脱敏），保持本地 `test` 提交链继续推进。
- SQLite 并发与锁：需要 WAL+busy_timeout+短事务；批量写入分 chunk；必要时加重试与 backoff。

## Rollback / Recovery
- 每次发布前备份 `app.db`；迁移严格使用 Alembic revision，必要时提供 downgrade（仅在安全可逆时）。

## Checkpoints
- Commit after: 每个 Issue（强制）并 push `test`
- Milestone 收尾：补一个“milestone smoke/regression”issue 记录证据

## References
- `new随机api开发文档.md`
- `数据库结构-详细DDL.md`
- `API契约-详细.md`
- `前端页面-详细原型.md`
- `任务系统-Worker与稳定性.md`
- `DockerCompose-部署与运维.md`

