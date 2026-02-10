# TODO（全量 Issue 拆分）— 按依赖顺序可直接执行

> 目标：把“需求”拆成可执行的工程任务清单。  
> 规则：每个条目都应能对应一次 PR（或一个小的提交集），并有验收方式（接口/页面/测试/指标）。

---

## 0. 约定

- P0：阻断级（不做就无法闭环/无法上线）
- P1：重要（影响稳定性/体验）
- P2：增强（可延后）

验收方式缩写：
- API：curl / OpenAPI
- UI：后台页面可点击完成动作
- TEST：pytest / playwright / 单测
- METRICS：Prometheus 指标有变化

---

## 1. P0：项目骨架与基础设施

- [ ] P0 初始化仓库：`backend/` `frontend/` `deploy/`（验收：目录结构完成）
- [ ] P0 后端依赖管理（uv/poetry/pip-tools 三选一固定）（验收：可 reproducible install）
- [ ] P0 FastAPI 入口 + `/healthz`（验收：API）
- [ ] P0 `/version` 输出 build_time/commit/version（验收：API）
- [ ] P0 SQLite engine 初始化 + WAL pragma（验收：启动日志/DB pragma）
- [ ] P0 Alembic 初始化（验收：可生成/运行空迁移）
- [ ] P0 基础配置系统（env + runtime_settings 合并）（验收：可在不重启下改设置）
- [ ] P0 结构化日志（JSON）+ request_id middleware（验收：日志含 request_id）
- [ ] P0 Dockerfile（后端）+ compose（api+worker）能启动（验收：docker compose up）

---

## 2. P0：导入闭环（无元信息也能 random）

### 2.1 URL 解析与去重
- [ ] P0 实现 `parse_pixiv_original_url()`（pximg host + `_p{n}`）（验收：TEST）
- [ ] P0 支持 ext 白名单（jpg/jpeg/png/gif/webp）（验收：TEST）
- [ ] P0 支持密码含 `@` 的 proxy uri 解析（验收：TEST）
- [ ] P0 images 表 unique(illust_id,page_index) upsert（验收：API+DB）

### 2.2 Import API（Admin）
- [ ] P0 `POST /admin/api/imports`（json 文本）（验收：API）
- [ ] P0 `POST /admin/api/imports`（multipart 文件）（验收：API）
- [ ] P0 dry_run preview（返回前 N 条解析结果 + 错误行）（验收：API）
- [ ] P0 import record：imports 表写入（验收：DB）
- [ ] P0 import rollback（disable/delete）（验收：API+DB）

### 2.3 最小 /random（只靠 DB）
- [ ] P0 random_key 生成与索引（验收：DB 索引 + API）
- [ ] P0 `GET /random` image 模式（验收：API）
- [ ] P0 `GET /random?format=json`（验收：API）
- [ ] P0 `redirect=1` 302 到 `/i/{id}.{ext}`（验收：API）
- [ ] P0 `/i/{id}.{ext}` 流式反代（验收：API）

---

## 3. P0：反代 Pixiv（流式 + Referer + 断连处理）

- [ ] P0 httpx 流式回源 `i.pximg.net`（验收：大图不爆内存）
- [ ] P0 固定 `Referer: https://www.pixiv.net/`（验收：403→200）
- [ ] P0 客户端断连时取消上游请求（验收：日志与资源释放）
- [ ] P0 图片响应头：
  - legacy/`/i/*`：长缓存
  - `/random`：no-store（验收：API headers）
- [ ] P1 Range 支持（可选）与透传（验收：curl -r）

---

## 4. P0：任务系统（SQLite jobs + worker）

- [ ] P0 jobs 表 + DDL migration（验收：DB）
- [ ] P0 claim 算法（UPDATE…RETURNING）+ lock TTL（验收：TEST 多 worker 不重复）
- [ ] P0 job 状态机（pending→running→completed/failed/dlq）（验收：TEST）
- [ ] P0 backoff 计算（验收：TEST）
- [ ] P0 Jobs API：list/detail/retry/cancel/move-to-dlq（验收：API）
- [ ] P0 UI：Jobs 页面可看可操作（验收：UI）

---

## 5. P0：Pixiv Token（refresh_token 加密 + 轮换 + 退避）

- [ ] P0 加密模块（Fernet/AES-GCM）封装（验收：TEST）
- [ ] P0 refresh_token write-only（验收：API 不回显）
- [ ] P0 tokens CRUD（验收：API+UI）
- [ ] P0 Pixiv OAuth refresh flow（验收：真实 token 可刷新）
- [ ] P0 access token 缓存（内存）+ expireTimestamp（验收：减少 refresh 次数）
- [ ] P0 refresh 失败退避（400/401/403 长 backoff；网络短 backoff）（验收：TEST）
- [ ] P0 token 策略：round_robin/least_error/weighted（验收：TEST）

---

## 6. P0：代理池（手工导入 + easy_proxies）

### 6.1 Proxy Endpoints
- [ ] P0 proxy_endpoints CRUD（验收：API+UI）
- [ ] P0 proxy password write-only（验收：API 不回显）
- [ ] P0 手工导入多行 URI（冲突策略）（验收：API+UI）

### 6.2 easy_proxies 对接
- [ ] P0 easy_proxies auth（可选 password）+ export（验收：API+TEST mock）
- [ ] P0 easy_proxies 导入 job（source=easy_proxies, source_ref=baseUrl）（验收：UI）
- [ ] P1 auto refresh 定时任务（验收：METRICS/日志）

### 6.3 Proxy Health
- [ ] P0 proxy_probe job（验收：API+DB 更新 latency）
- [ ] P0 健康评分与过滤（验收：random/hydrate 只用健康 proxy）
- [ ] P1 blacklist 策略（失败阈值→blacklisted_until）（验收：DB）

---

## 7. P0：token ↔ proxy 绑定（稳定身份 + failover）

- [ ] P0 proxy_pools CRUD（验收：UI）
- [ ] P0 pool_endpoints 管理（enabled/weight）（验收：UI）
- [ ] P0 rendezvous hashing primary 绑定（验收：TEST）
- [ ] P0 bindings 表维护（recompute）（验收：API+UI）
- [ ] P0 override TTL（验收：TEST + UI 显示倒计时）
- [ ] P0 failover：proxy_connect/proxy_auth → override；rate_limit → token backoff（验收：TEST）

---

## 8. P0：元信息补全（hydrate_metadata）

- [ ] P0 Pixiv App API client：`/v1/illust/detail`（验收：真实返回解析）
- [ ] P0 normalize：width/height/orientation/aspect（验收：TEST）
- [ ] P0 normalize：tags(name/translated_name) 去重（验收：TEST）
- [ ] P0 persist：更新 images、upsert tags、sync image_tags（验收：DB）
- [ ] P0 hydrate job handler（验收：Jobs UI 可看到成功/失败）
- [ ] P0 backfill run（hydration_runs）创建/暂停/恢复/取消（验收：UI）
- [ ] P1 opportunistic hydrate（random 命中缺元信息时入队）（验收：METRICS）

---

## 9. P0：随机 API 强筛选（基于元信息）

- [ ] P0 filters：r18 + strict（含 NULL 语义） （验收：TEST）
- [ ] P0 filters：orientation/min_width/min_height/min_pixels（验收：TEST）
- [ ] P0 filters：included_tags/excluded_tags（验收：TEST）
- [ ] P0 filters：user_id/illust_id（验收：TEST）
- [ ] P1 filters：created_from/to（验收：TEST）
- [ ] P0 NO_MATCH hints（applied_filters + suggestions）（验收：API）
- [ ] P0 attempts 换图重试（坏图/超时）（验收：API）
- [ ] P0 fail cooldown（last_fail_at 冷却）（验收：DB+API）

---

## 10. P0：管理后台（React）

### 10.1 框架与布局
- [ ] P0 登录与路由保护（验收：UI）
- [ ] P0 全局错误处理（ApiErrorAlert）与 request_id 展示（验收：UI）
- [ ] P0 TanStack Query 缓存策略（验收：UI 不卡）

### 10.2 页面打通（按闭环顺序）
- [ ] P0 Dashboard 闭环卡片（验收：UI）
- [ ] P0 Import（preview/导入/记录/详情/回滚）（验收：UI）
- [ ] P0 Images（列表/详情/动作）（验收：UI）
- [ ] P0 Tokens（新增/测试/启停/退避）（验收：UI）
- [ ] P0 Proxies（导入/easy_proxies/探测）（验收：UI）
- [ ] P0 Pools（CRUD+加入端点）（验收：UI）
- [ ] P0 Bindings（recompute/override）（验收：UI）
- [ ] P0 Jobs（list/detail/retry）（验收：UI）
- [ ] P0 Settings（保存与恢复默认）（验收：UI）
- [ ] P1 Audit（验收：UI）

### 10.3 Playground
- [ ] P0 Random Playground（拼参数+预览+复制 curl）（验收：UI）

---

## 11. P0：可观测与质量门禁

- [ ] P0 `/metrics` 基础指标（random 成功率、job 成功率、代理健康）（验收：METRICS）
- [ ] P0 `/healthz` 输出依赖状态（DB/worker/queue）（验收：API）
- [ ] P0 安全单测：敏感字段不回显（验收：TEST）
- [ ] P0 e2e 最小脚本：导入 10 条 → random json 返回 OK/NO_MATCH 合理（验收：TEST）
- [ ] P1 负载测试脚本（k6/locust）（验收：报告）

---

## 12. P1/P2：后续增强（可选）

- [ ] P1 imgproxy 支持（签名 URL，防滥用）
- [ ] P1 API Key 系统（对外限流/计费）
- [ ] P1 多 proxy pool（按域名/按地区路由）
- [ ] P2 FTS（tags/author 搜索加速）
- [ ] P2 数据归档/清理策略（request_logs 分表/清理）

