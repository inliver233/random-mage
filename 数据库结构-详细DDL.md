# 数据库结构（SQLite）— 详细 DDL 与索引设计

> 本文属于 `new-pixiv-api实现/` 的“可直接落地”设计稿：你可以按本文建库，或作为 Alembic migration 的来源。  
> 时间字段统一使用 `TEXT` 存 ISO8601 UTC（例如 `2026-02-09T15:20:48Z`）。

---

## 0. SQLite 全局建议（必须）

启动后端/worker 时，第一时间执行：

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;
PRAGMA busy_timeout = 5000;
```

说明：
- WAL 提升读并发；写仍是单写者，但足够支撑本项目（写入主要来自 worker）。
- `busy_timeout` 避免轻易抛出 `database is locked`（仍需应用层重试）。

---

## 1. 通用时间函数

建议统一用 SQLite 表达式：

```sql
-- 以 UTC 生成 ISO8601（带毫秒）
strftime('%Y-%m-%dT%H:%M:%fZ','now')
```

---

## 2. 枚举约定（用 INTEGER/TEXT + CHECK）

### 2.1 images.status
- `1` active（默认对外可见）
- `2` disabled（软禁用）
- `3` broken（坏图：回源 403/404 等）
- `4` deleted（软删：默认不出现在随机/列表）

### 2.2 jobs.status
- `pending` / `running` / `paused` / `canceled` / `completed` / `failed` / `dlq`

### 2.3 hydration_runs.status
- 同 jobs.status，但不使用 dlq（run 内部错误计数即可）

---

## 3. 核心表 DDL

> 说明：DDL 里包含了一些“运行态字段”（例如 token/proxy 的 backoff/健康数据），用于让 UI 更直观，也方便多进程共享状态。

### 3.1 imports（导入批次）

```sql
CREATE TABLE IF NOT EXISTS imports (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  created_by        TEXT,
  source            TEXT,

  total             INTEGER NOT NULL DEFAULT 0,
  accepted          INTEGER NOT NULL DEFAULT 0,
  success           INTEGER NOT NULL DEFAULT 0,
  failed            INTEGER NOT NULL DEFAULT 0,

  detail_json       TEXT
);

CREATE INDEX IF NOT EXISTS idx_imports_created_at ON imports(created_at);
```

### 3.2 images（图片页级记录）

```sql
CREATE TABLE IF NOT EXISTS images (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,

  illust_id          INTEGER NOT NULL,
  page_index         INTEGER NOT NULL,
  ext                TEXT NOT NULL,

  original_url       TEXT NOT NULL,
  proxy_path         TEXT NOT NULL,
  random_key         REAL NOT NULL,

  width              INTEGER,
  height             INTEGER,
  aspect_ratio       REAL,
  orientation        INTEGER,          -- 1/2/3
  x_restrict         INTEGER,          -- 0/1/2, NULL=unknown
  ai_type            INTEGER,          -- 0/1, NULL=unknown
  user_id            INTEGER,
  user_name          TEXT,
  title              TEXT,
  created_at_pixiv   TEXT,

  -- 热度（来自 Pixiv App API illust/detail 的 total_*）
  bookmark_count     INTEGER,
  view_count         INTEGER,
  comment_count      INTEGER,

  status             INTEGER NOT NULL DEFAULT 1,
  fail_count         INTEGER NOT NULL DEFAULT 0,
  last_fail_at       TEXT,
  last_ok_at         TEXT,
  last_error_code    TEXT,
  last_error_msg     TEXT,

  created_import_id  INTEGER,
  added_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  CONSTRAINT uq_images_illust_page UNIQUE (illust_id, page_index),
  CONSTRAINT fk_images_import FOREIGN KEY (created_import_id) REFERENCES imports(id) ON DELETE SET NULL,
  CONSTRAINT ck_images_status CHECK (status IN (1,2,3,4)),
  CONSTRAINT ck_images_random_key CHECK (random_key >= 0.0 AND random_key < 1.0)
);

CREATE INDEX IF NOT EXISTS idx_images_filter
  ON images(status, x_restrict, orientation, width, height, random_key);

CREATE INDEX IF NOT EXISTS idx_images_user_random
  ON images(status, user_id, random_key);

CREATE INDEX IF NOT EXISTS idx_images_created_at_pixiv
  ON images(created_at_pixiv);

CREATE INDEX IF NOT EXISTS idx_images_created_import_id
  ON images(created_import_id);
```

> 注意：`proxy_path` 不是必须入库（可动态拼），但入库能避免路径规则变更导致历史链接失效。

### 3.3 tags / image_tags

```sql
CREATE TABLE IF NOT EXISTS tags (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              TEXT NOT NULL,
  translated_name   TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  CONSTRAINT uq_tags_name UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS image_tags (
  image_id          INTEGER NOT NULL,
  tag_id            INTEGER NOT NULL,

  PRIMARY KEY (image_id, tag_id),
  CONSTRAINT fk_image_tags_image FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
  CONSTRAINT fk_image_tags_tag   FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_image_tags_tag_image ON image_tags(tag_id, image_id);
```

### 3.4 pixiv_tokens（refresh token，write-only）

```sql
CREATE TABLE IF NOT EXISTS pixiv_tokens (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  label                TEXT,
  enabled              INTEGER NOT NULL DEFAULT 1,

  refresh_token_enc    TEXT NOT NULL,   -- 加密后（不可逆读回明文）
  refresh_token_masked TEXT NOT NULL,   -- UI 展示用
  weight               REAL NOT NULL DEFAULT 1.0,

  -- 运行态（可选但强烈建议）
  error_count          INTEGER NOT NULL DEFAULT 0,
  backoff_until        TEXT,            -- ISO
  last_ok_at           TEXT,
  last_fail_at         TEXT,
  last_error_code      TEXT,
  last_error_msg       TEXT,

  CONSTRAINT ck_pixiv_tokens_enabled CHECK (enabled IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_pixiv_tokens_enabled ON pixiv_tokens(enabled);
```

### 3.5 proxy_endpoints（代理端点）

```sql
CREATE TABLE IF NOT EXISTS proxy_endpoints (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  scheme             TEXT NOT NULL,     -- http/https/socks4/socks5
  host               TEXT NOT NULL,
  port               INTEGER NOT NULL,
  username           TEXT NOT NULL DEFAULT '',
  password_enc       TEXT NOT NULL DEFAULT '',  -- 加密；空表示无密码

  enabled            INTEGER NOT NULL DEFAULT 1,
  source             TEXT NOT NULL DEFAULT 'manual',
  source_ref         TEXT,

  -- 健康运行态
  last_latency_ms    REAL,
  last_ok_at         TEXT,
  last_fail_at       TEXT,
  success_count      INTEGER NOT NULL DEFAULT 0,
  failure_count      INTEGER NOT NULL DEFAULT 0,
  blacklisted_until  TEXT,
  last_error         TEXT,

  CONSTRAINT uq_proxy_identity UNIQUE (scheme, host, port, username),
  CONSTRAINT ck_proxy_enabled CHECK (enabled IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_proxy_endpoints_enabled ON proxy_endpoints(enabled);
CREATE INDEX IF NOT EXISTS idx_proxy_endpoints_source ON proxy_endpoints(source);
```

### 3.6 proxy_pools / proxy_pool_endpoints

```sql
CREATE TABLE IF NOT EXISTS proxy_pools (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  name               TEXT NOT NULL,
  description        TEXT,
  enabled            INTEGER NOT NULL DEFAULT 1,

  CONSTRAINT uq_proxy_pools_name UNIQUE (name),
  CONSTRAINT ck_proxy_pools_enabled CHECK (enabled IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_proxy_pools_enabled ON proxy_pools(enabled);

CREATE TABLE IF NOT EXISTS proxy_pool_endpoints (
  pool_id            INTEGER NOT NULL,
  endpoint_id        INTEGER NOT NULL,
  enabled            INTEGER NOT NULL DEFAULT 1,
  weight             INTEGER NOT NULL DEFAULT 1,

  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  PRIMARY KEY (pool_id, endpoint_id),
  CONSTRAINT fk_ppe_pool FOREIGN KEY (pool_id) REFERENCES proxy_pools(id) ON DELETE CASCADE,
  CONSTRAINT fk_ppe_ep   FOREIGN KEY (endpoint_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE,
  CONSTRAINT ck_ppe_enabled CHECK (enabled IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_ppe_pool_enabled ON proxy_pool_endpoints(pool_id, enabled);
CREATE INDEX IF NOT EXISTS idx_ppe_endpoint_pool ON proxy_pool_endpoints(endpoint_id, pool_id);
```

### 3.7 token_proxy_bindings

```sql
CREATE TABLE IF NOT EXISTS token_proxy_bindings (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  token_id           INTEGER NOT NULL,
  pool_id            INTEGER NOT NULL,

  primary_proxy_id   INTEGER NOT NULL,
  override_proxy_id  INTEGER,
  override_expires_at TEXT,

  CONSTRAINT uq_token_pool UNIQUE (token_id, pool_id),
  CONSTRAINT fk_tpb_token FOREIGN KEY (token_id) REFERENCES pixiv_tokens(id) ON DELETE CASCADE,
  CONSTRAINT fk_tpb_pool  FOREIGN KEY (pool_id) REFERENCES proxy_pools(id) ON DELETE CASCADE,
  CONSTRAINT fk_tpb_primary FOREIGN KEY (primary_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE RESTRICT,
  CONSTRAINT fk_tpb_override FOREIGN KEY (override_proxy_id) REFERENCES proxy_endpoints(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tpb_pool ON token_proxy_bindings(pool_id);
CREATE INDEX IF NOT EXISTS idx_tpb_primary ON token_proxy_bindings(primary_proxy_id);
CREATE INDEX IF NOT EXISTS idx_tpb_override ON token_proxy_bindings(override_proxy_id);
```

### 3.8 runtime_settings

```sql
CREATE TABLE IF NOT EXISTS runtime_settings (
  key                TEXT PRIMARY KEY,
  value_json         TEXT NOT NULL,
  description        TEXT,
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_by         TEXT
);
```

### 3.9 jobs（SQLite 队列）

```sql
CREATE TABLE IF NOT EXISTS jobs (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  type               TEXT NOT NULL,
  status             TEXT NOT NULL,
  priority           INTEGER NOT NULL DEFAULT 0,
  run_after          TEXT,

  attempt            INTEGER NOT NULL DEFAULT 0,
  max_attempts       INTEGER NOT NULL DEFAULT 3,

  payload_json       TEXT NOT NULL,
  last_error         TEXT,

  locked_by          TEXT,
  locked_at          TEXT,

  -- 方便 UI：业务关联（可选）
  ref_type           TEXT,
  ref_id             TEXT,

  CONSTRAINT ck_jobs_status CHECK (status IN ('pending','running','paused','canceled','completed','failed','dlq'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON jobs(status, priority, id);
CREATE INDEX IF NOT EXISTS idx_jobs_run_after ON jobs(run_after);
CREATE INDEX IF NOT EXISTS idx_jobs_ref ON jobs(ref_type, ref_id);
```

### 3.10 hydration_runs（批量补全批次）

```sql
CREATE TABLE IF NOT EXISTS hydration_runs (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

  type               TEXT NOT NULL,
  status             TEXT NOT NULL,

  criteria_json      TEXT,
  cursor_json        TEXT,

  total              INTEGER,
  processed          INTEGER NOT NULL DEFAULT 0,
  success            INTEGER NOT NULL DEFAULT 0,
  failed             INTEGER NOT NULL DEFAULT 0,

  started_at         TEXT,
  finished_at        TEXT,
  last_error         TEXT,

  CONSTRAINT ck_hr_status CHECK (status IN ('pending','running','paused','canceled','completed','failed'))
);

CREATE INDEX IF NOT EXISTS idx_hr_status_updated ON hydration_runs(status, updated_at);
```

### 3.11 request_logs / admin_audit（可观测与审计）

```sql
CREATE TABLE IF NOT EXISTS request_logs (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  request_id         TEXT,
  method             TEXT NOT NULL,
  route              TEXT NOT NULL,
  status             INTEGER NOT NULL,
  duration_ms        INTEGER NOT NULL,
  ip                 TEXT,
  user_agent         TEXT,
  sample_rate        REAL
);

CREATE INDEX IF NOT EXISTS idx_request_logs_created_at ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_request_logs_route ON request_logs(route);
CREATE INDEX IF NOT EXISTS idx_request_logs_status ON request_logs(status);

CREATE TABLE IF NOT EXISTS admin_audit (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  actor              TEXT,
  action             TEXT NOT NULL,
  resource           TEXT NOT NULL,
  record_id          TEXT,
  request_id         TEXT,
  ip                 TEXT,
  user_agent         TEXT,
  detail_json        TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_created_at ON admin_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON admin_audit(action);
CREATE INDEX IF NOT EXISTS idx_admin_audit_resource ON admin_audit(resource);
CREATE INDEX IF NOT EXISTS idx_admin_audit_record_id ON admin_audit(record_id);
```

---

## 4. 触发器（可选，但强烈建议）

统一维护 `updated_at`：

```sql
CREATE TRIGGER IF NOT EXISTS trg_images_updated_at
AFTER UPDATE ON images
FOR EACH ROW
BEGIN
  UPDATE images SET updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE id = NEW.id;
END;
```

对其他表同理（pixiv_tokens/proxy_endpoints/imports/jobs/hydration_runs/tags 等）。

---

## 5. 查询性能要点（SQLite 版）

### 5.1 随机挑选避免 `ORDER BY random()`
- 统一使用 `random_key` 策略（见总纲）。
- `idx_images_filter` 的末尾必须含 `random_key`，才能快速定位第一条。

### 5.2 tags 筛选（included/excluded）
SQLite 下多对多筛选推荐两种方案：
1) 小数据量：JOIN + GROUP BY HAVING
2) 大数据量：先查出满足 tags 条件的 image_id 集合（临时表/CTE），再与 images 过滤

### 5.3 min_pixels
`width*height` 会溢出风险（理论上），建议用 `CAST(width AS INTEGER) * CAST(height AS INTEGER)` 并在应用层限制上限。

---

## 6. 迁移策略（Alembic）

强建议：
- 每次变更 schema → 新增 migration
- migration 只做结构变更，数据修复用 job（可回滚/可观测）

发布流程：
1) 备份 `data/app.db`
2) `alembic upgrade head`
3) 启动服务
4) 跑健康检查与一组回归（/version /healthz /random?format=json）
