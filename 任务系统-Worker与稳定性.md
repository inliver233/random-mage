# 任务系统（Worker）与稳定性设计

> 目标：在不引入 Redis 的前提下，用 SQLite 做“够用且可运维”的持久化任务系统。  
> 核心：所有长耗时动作（导入、补全、heal、代理探测、easy_proxies 导入）必须 job 化：  
> **立即返回** → **可追溯**（jobId/进度/错误）→ **可重试** → **可取消**。

---

## 1. 为什么不用“同步执行”

你在旧项目里遇到的典型问题：
- Admin 点击按钮 → pending/504
- 动作成功入队但 UI 不知道 jobId（不可追溯）
- 外部依赖抖动（代理/上游）放大为整站不可用

结论：任何触网/批量/可能慢的操作必须异步。

---

## 2. jobs 表语义（与总纲一致）

字段要点：
- `type`: 任务类型
- `status`: pending/running/paused/canceled/completed/failed/dlq
- `priority`: 越大越先（或相反，需统一）
- `run_after`: 延迟执行（退避重试/定时任务）
- `attempt/max_attempts`: 重试计数
- `payload_json`: 输入
- `ref_type/ref_id`: 业务关联（Import/HydrationRun/ProxyEndpoint…）
- `locked_by/locked_at`: claim 锁

---

## 3. SQLite claim 算法（关键：多 worker 不重复执行）

### 3.1 基本要求
- 多个 worker 实例可同时运行
- 同一 job 只能被一个 worker 执行
- worker 崩溃后，锁要能被“抢回”（lock 超时）

### 3.2 推荐实现：`UPDATE ... WHERE ... LIMIT ... RETURNING`

SQLite 3.35+ 支持 `RETURNING`。claim 逻辑：

1) 找到一个可执行 job（pending/failed 且 run_after<=now 且未锁或锁过期）
2) 原子更新：status=running、locked_by、locked_at
3) RETURNING 返回被 claim 的 job

示例 SQL（概念）：

```sql
WITH candidate AS (
  SELECT id
  FROM jobs
  WHERE status IN ('pending','failed')
    AND (run_after IS NULL OR run_after <= :now)
    AND (
      locked_at IS NULL OR locked_at <= :lock_expired_before
    )
  ORDER BY priority DESC, id ASC
  LIMIT 1
)
UPDATE jobs
SET status='running',
    locked_by=:worker_id,
    locked_at=:now,
    updated_at=:now
WHERE id IN (SELECT id FROM candidate)
RETURNING *;
```

### 3.3 lock TTL
- 建议：`lock_ttl = 5 minutes`（可配置）
- worker 每隔 N 秒心跳续租（更新 locked_at），避免被误抢回

续租 SQL：
```sql
UPDATE jobs
SET locked_at = :now,
    updated_at = :now
WHERE id = :id AND locked_by = :worker_id AND status='running';
```

---

## 4. 重试/退避/死信（DLQ）

### 4.1 什么时候重试
必须做错误分类（见 5）：
- 可重试：网络超时、代理连接失败（可换代理）、上游 5xx
- 不可重试：参数错误、URL 解析失败、illust 被删（404）、token 失效（400/401/403 refresh）

### 4.2 退避策略（建议）

```text
attempt 0 -> 0s
attempt 1 -> 5s
attempt 2 -> 30s
attempt 3 -> 2m
attempt 4 -> 10m
attempt 5 -> 30m
...
```

规则：
- 每次失败：`attempt += 1`
- `attempt >= max_attempts` → `status=dlq`
- 否则：`status=failed` 并设置 `run_after=now+backoff(attempt)`

### 4.3 DLQ 管理
UI 必须提供：
- `重试（回 pending）`
- `丢弃（标记 canceled 或删除）`
- `批量重试`

---

## 5. 任务类型（type）与处理器（handler）

### 5.1 `import_images`
payload：
- import_id
- text_lines 或 file_ref（建议入库时就展开 lines，避免 worker 读文件）
- options：hydrate_on_import、source、created_by

处理：
- 逐行 parse pximg original url（illust/page/ext）
- 去重（(illust_id,page_index) unique）
- upsert images（生成 random_key，写 proxy_path）
- 更新 imports.accepted/failed
- 若 hydrate_on_import：按 illust_id 去重后入队 hydrate_metadata（ref_type=import）

幂等性：
- upsert by unique key；重复导入不应产生新 rows

### 5.2 `hydrate_metadata`
payload：
- illust_id
- reason：import/backfill/opportunistic/heal
- request_id（可选）

处理：
- 获取 access_token（multi token）
- 选择代理（token↔proxy binding + failover）
- 调用 Pixiv App API illust/detail
- 解析：
  - page_count 与 original urls
  - width/height/aspect/orientation
  - x_restrict/ai_type/user/title/create_date/tags
- persist：
  - 更新 images 对应页
  - upsert tags
  - sync image_tags

幂等性：
- 同一个 illust_id 重复 hydrate 会覆盖更新（原图 URL 会变化，必须允许覆盖）

### 5.3 `heal_url`
payload：
- illust_id
- trigger：upstream_403/upstream_404/manual

处理：
- 本质复用 hydrate_metadata，但重点是：
  - 更新 original_url/ext（可能变更）
  - 将 broken 的 images 改回 active（如果恢复成功）

### 5.4 `proxy_probe`
payload：
- probe_url（可选覆盖）
- timeout_ms
- concurrency

处理：
- 遍历 enabled proxy_endpoints
- 用代理对 probe_url 发起请求（HEAD/GET generate_204）
- 记录 latency、success/failure、blacklist_until（阈值失败）

### 5.5 `easy_proxies_import`
payload：
- base_url
- password（可选）
- conflict_policy

处理：
- 若 password：POST /api/auth 拿 token（短期内缓存）
- GET /api/export（text/plain）
- 按行 parse proxy uri，并入库 proxy_endpoints（source=easy_proxies）

---

## 6. 并发控制（稳定的关键）

### 6.1 全局并发（worker 线程数）
- worker 主循环同时运行的 job 数：`WORKER_MAX_CONCURRENCY`（建议 4~16）

### 6.2 hydrate 专用限速（global + per-token + per-proxy）
原因：
- Pixiv API 有速率限制（403 Rate Limit）
- 代理池也可能被打穿（大量并发连接失败）

建议 3 层 limiter：
1) global max in-flight（例如 8）
2) per-token max in-flight（例如 1~2）
3) per-proxy min interval（例如 200ms）

实现方式：
- 内存信号量 + 时间戳（适合单 worker）
- 多 worker 需要共享时：将 limiter 状态写入 DB（复杂，MVP 可不做）

折中策略：
- 第一版允许每个 worker 自己限速（整体仍能降低打穿概率）

---

## 7. 错误分类（用于 failover 与重试决策）

分类维度：
- `proxy_connect`：代理不可达/握手失败
- `proxy_auth`：代理 407/认证失败
- `timeout`：连接或读超时
- `network`：DNS/断开
- `pixiv_rate_limit`：Pixiv API 403 + message=Rate Limit
- `pixiv_403`：403 但不是 rate limit（可能权限/R18/风控）
- `pixiv_404`：作品不存在/被删
- `pixiv_5xx`：上游错误
- `unknown`

决策：
- proxy_connect/proxy_auth → 允许换 proxy（override）
- pixiv_rate_limit → 换 token 或对 token 进入 backoff
- pixiv_404 → 标记为不可恢复（不再重试 hydrate）

---

## 8. 观测（必须）

每个 job 执行必须记录：
- job_id、type、attempt、duration_ms、status
- request_id（如果有）
- token_id（脱敏，不要打印 refresh_token）
- proxy_id（不要打印完整 proxy uri）
- error_code/error_message（脱敏）

Prometheus 指标建议：
- `jobs_total{type,status}`
- `jobs_duration_ms_bucket{type}`
- `pixiv_token_backoff_until{token_id}`（注意 label cardinality，可只暴露计数/TopN）
- `proxy_health_score{proxy_id}`（同上，谨慎）

---

## 9. MVP 与后续增强

MVP：
- SQLite jobs + 单 worker
- 关键动作 job 化
- UI 能追溯 jobId

增强：
- 引入 Redis 队列（RQ/Celery）提升吞吐与可观测
- 引入分布式 rate limit（Redis token bucket）
- 将 proxy health 与 binding 策略做成“自适应”（按成功率动态权重）

