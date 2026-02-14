# REV-0109 管理后台闭环 Smoke / Review

- 日期：2026-02-14
- 分支：`test`
- 目标：按“导入 → 图片 → 补全 → Jobs → random”路径做一次端到端自查，并记录回归命令执行证据；同时检查管理后台中文化与常见易用性问题。

## 回归命令（证据）

### Backend
- 命令：`.venv\\backend_verify\\Scripts\\python.exe -m pytest -q backend/tests`
- 结果：`240 passed`（含新增 `test_hydrate_persists_popularity_fields.py`）

### Frontend
- 命令：`cd frontend && npm test && npm run typecheck`
- 结果：`vitest: 17 files / 33 tests passed`；`tsc --noEmit` 通过（仅存在 React Router future flags 与 antd Modal deprecation 警告，不影响构建与运行）

## 闭环路径（手工 Smoke Checklist）

> 说明：以下步骤面向 Docker Compose 部署后的可视化验证（不依赖手动操作后台/DB）。

### 1) 登录与路由保护
- 未登录访问任意 `/admin/*` 页面：应自动跳转到 `/admin/login`，并提示原因（如 token 失效/未登录）。
- 登录成功后：应自动回跳到之前页面（`next=`）。

### 2) 主页（Dashboard）
- `/admin` 展示：图片/令牌/代理/代理池/绑定关系数量汇总、Worker 心跳与任务队列统计。
- 展示 `/version` 的 `version/build_time/git_commit`，便于确认当前部署版本。

### 3) 导入
- `/admin/import` 可创建导入任务（导入 Pixiv 图片 URL/illust/page）。
- 导入完成后：`/admin/import/:id` 可查看导入明细与成功/失败数量。

### 4) 图片管理
- `/admin/images`：
  - 可分页查看图片列表（含缺失字段提示/缺失过滤）。
  - 可对单张图片执行“手动补全（image_id）”，用于快速修复 `NO_MATCH`（元数据缺失导致的严格过滤无匹配）。

### 5) 补全管理（Hydration）
- `/admin/hydration`：
  - 可查看元数据缺失覆盖率统计（geometry/r18/ai/user/title/created_at/tags）。
  - 可勾选缺失项并一键创建补全任务（hydration run + job）。

### 6) Jobs / 任务队列
- `/admin/jobs`：
  - 可按状态/类型筛选与刷新。
  - 行内操作：重试/取消/移入死信（DLQ）。
  - 可打开详情抽屉查看 payload/锁/错误与后端返回的 request_id（便于排障）。

### 7) random JSON 调试
- `/admin/random` 或直接请求 `/random?format=json`：
  - 有匹配：返回 `ok:true` 且包含 `debug` 信息。
  - 无匹配：返回 `NO_MATCH` 并给出 hints（例如：建议运行补全、或将 `r18_strict=0` 放宽未知 `x_restrict`）。

## 发现的问题与处理

- 本次未新增“token ↔ 代理节点使用统计（次数/间隔/命中节点）”的可视化与聚合报表；当前以“代理池/绑定关系/审计日志/请求日志”等页面为主进行排障。
- 图片热度字段（收藏/浏览/评论）已完成 DB 预留与补全持久化，但尚未用于随机策略权重（后续可基于该数据实现更智能的随机选择）。

## 执行记录

- Backend 回归：`240 passed`（2026-02-14）
- Frontend 回归：`npm test` 通过（17 files / 33 tests），`npm run typecheck` 通过（2026-02-14）
