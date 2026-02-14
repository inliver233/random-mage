# new 随机 Pixiv 图片 API — 开发文档（总纲）

> 工作区：`E:\pixiv-download-修改版本`  
> 目标：以 **FastAPI + SQLite + React(组件库)** 重做一个“可长期稳定运行”的 Pixiv 随机图片系统：  
> **导入海量 pximg 原图 URL → 反代图片 → 多 refresh token + 代理池获取元信息 → DB 分类检索 → 高度可配置随机图片 API → Docker Compose 一键部署**。  
>
> 本文是“开发根文档”：功能清单、页面/按钮、接口契约、数据库结构、核心算法伪代码、任务队列与稳定性策略、部署与安全规范、以及分阶段 TODO。

---

## 0. 读者与边界

### 0.1 读者
- 你（产品/运营/自用）：想要“能用、好用、稳定、可运维”的随机图片 API。
- 开发者（后端/前端）：按图施工实现；所有关键口径以本文为准。

### 0.2 非目标（避免需求漂移）
- 不做“下载并永久存储图片文件”的图床（本项目 **仅反代/缓存策略**，不落盘图片内容）。
- 不做“绕过 Pixiv 合规/版权”的灰产系统：必须提供下架/禁用、审计、与默认全年龄策略。
- 不以“单次请求直连 Pixiv API”为核心路径（会被限流拖垮）；Pixiv API 只能走 **冷路径补全**。

### 0.3 安全硬规则（贯穿全项目）
- `refresh_token`、代理 `password`、任何鉴权 secret：**写入后不可读（write-only）**；前端/接口/日志中不得出现明文。
- 所有日志默认脱敏；任何可疑泄露必须被 CI/测试挡住（写安全单测）。

---

## 1. 背景调研结论（你当前目录里的 3 个关键“知识源”）

### 1.1 `pixiv-反代/pixivcat-backend` 给我们的可复用能力

> 该项目（Node/TS）已经实现了大量“我们需要的理念”，但存在你指出的：页面混乱、可维护性差、实现方式（AdminJS）不符合你想要的 React 体验等。  
> 我们要做的是 **学习其工程策略与关键算法**，并用全新技术栈重构成“可长期维护”的项目。

从代码与文档中可抽取的“必须复用的思想”：
- **图片流式反代**：对 `i.pximg.net` 原图用 `Referer: https://www.pixiv.net/` 回源，响应用 stream pipe（避免整图进内存）。
- **两类图片 URL**：
  - legacy 兼容：`/{illustId}.{ext}` 与 `/{illustId}-{page}.{ext}`（Pixivcat 兼容）
  - 稳定图片 URL：`/i/{imageId}.{ext}`（随机 API 推荐用 302 跳转到稳定 URL，利于 CDN 长缓存）
- **把 Pixiv API 移出热路径**：随机 API 的热路径只查本地 DB；Pixiv API 只用于元信息补全/修复。
- **多 refresh token 轮换 + 失败退避**：单 token 会触发 Pixiv 风控/限流；需要多 token + 策略化选择。
- **代理池与 failover**：
  - 支持 `http/https/socks4/socks5` 代理 URI
  - 代理健康检查、按健康过滤候选
  - “token ↔ proxy” 绑定（稳定身份/稳定出口），并支持临时 override（某代理失败 → TTL 内换另一个）
- **随机挑选算法**：使用 `random_key ∈ [0,1)` + 索引做近似均匀随机（避免 `ORDER BY random()`）。
- **任务化（导入/补全/修复）与可追溯**：每次导入/补全都有记录、进度、失败原因、可重试/回滚。

### 1.2 `easy_proxies` 给我们的“代理池契约”

我们要支持两种对接方式：
1) **最简单**：用户粘贴一行/多行通用代理 URI（如 `http://user:pa@ss@host:port`，密码含 `@` 也能解析）。
2) **easy_proxies 自动导入**：
   - `POST /api/auth`（可选）→ 拿到 token
   - `GET /api/export` → `text/plain`，每行一个 `http://host:port` 或 `http://user:pass@host:port`
   - hybrid/multi-port 模式下导出的端口是“每节点独立端口”，更适合做稳定绑定

### 1.3 你当前目录中的 MD 文档给我们的“验收基线”

这些文档体现了你对“最终系统”的真实期望与对旧实现的痛点：
- “导入大量 URL → 元信息补全 → 分类检索 → 强随机 API”闭环必须打通。
- UI 必须“看得懂、能操作、可追溯”，不能出现“按钮在但不可用/深链 not found/页面意义不明”等。
- 代理池与 token 绑定必须自动稳定，不需要你手工折腾。
- Docker Compose 必须一键部署、可稳定升级、可回滚。

---

## 2. 新项目的最终形态（你想要的“成品”是什么）

### 2.1 三条主链路（必须全部闭环）

1) **导入链路（冷→热准备）**  
   大量 pximg 原图 URL → 解析 illust/page/ext → 去重入库（Images）→ 生成 `random_key` →（可选）入队元信息补全任务

2) **补全链路（多 token + 代理池）**  
   worker 使用 token 刷 access token → 通过代理池出站访问 Pixiv App API → 拉取 illust detail → 写入 width/height/R18/tags/author/... → 建立 tags/image_tags 关系 → 为随机筛选提供数据

3) **随机链路（热路径）**  
   `/random` 根据筛选参数只查 SQLite → 随机挑选 →  
   - 默认返回图片 stream（内部会对坏图“换图重试”）  
   - 或 `format=json` 返回 JSON  
   - 或 `redirect=1` 返回 302 跳转到稳定 URL `/i/{id}.{ext}`

### 2.2 两类用户角色
- **公开调用方**：只调用 `/random`、`/i/*`、`/tags`、`/authors`、`/images` 等公开 API。
- **管理员**：通过 React 管理后台做导入/补全/绑定/观测/排障；拥有更高权限。

---

## 3. 技术栈（固定选择，除非你明确改口）

### 3.1 后端（FastAPI）
- Python：`>=3.11`（推荐 3.12）
- Web：FastAPI + Uvicorn
- ORM：SQLAlchemy 2.x（SQLite），迁移：Alembic
- HTTP：httpx（支持流式、代理、超时、HTTP/2 可选）
- 重试/退避：tenacity（或自研小型 backoff）
- 任务系统：**SQLite 持久化任务表 + worker 轮询/claim**（默认不引入 Redis），可选扩展 Celery/Redis
- 指标：prometheus-client
- 日志：structlog（JSON）或标准 logging（JSON formatter）

### 3.2 前端（React）
- React + TypeScript + Vite
- 组件库：Ant Design（或 Mantine；本文按 AntD 设计）
- 路由：react-router
- 数据请求：TanStack Query + axios（或 fetch）
- 表格大数据：虚拟滚动（react-window / antd Table virtual）

### 3.3 数据库（SQLite）
- 单文件数据库：`data/app.db`
- 强制启用 WAL：提升读写并发
- 关键索引：random_key、过滤字段、tag 关系表

### 3.4 部署（Docker Compose）
最小 2 服务：
- `api`：FastAPI（同时服务 public API + admin API）
- `worker`：后台任务（hydrate/heal/proxy health/easy_proxies import）

可选 3 服务：
- `web`：前端静态站（nginx），或由 `api` 直接托管静态文件

---

## 4. 总体架构（模块分层）

### 4.1 目录建议（最终代码仓库结构）

> 注意：本文所在目录 `new-pixiv-api实现/` 是文档与规划落盘目录；真正代码实现可以在同级新建 `new-pixiv-api/`（后续对话再做）。

建议后续代码仓库结构：

```text
new-pixiv-api/
  backend/
    app/
      main.py              # FastAPI 入口
      api/                 # 路由（public/admin）
      core/                # config, logging, security, utils
      db/                  # engine/session/migrations/models
      pixiv/               # oauth, app-api client, parsing
      proxy/               # proxy parsing, pools, health, binding
      random/              # filters, query builder, picker
      jobs/                # job types, worker logic
      observability/       # metrics, tracing, request_id
      tests/
  frontend/
    src/
    index.html
  deploy/
    docker-compose.yml
    nginx.conf
  docs/
    openapi.md
```

### 4.2 关键设计原则（避免走回旧项目的坑）
- **信息架构先行**：页面与功能必须“一眼看懂”，有统一导航与术语表。
- **冷热分离**：/random 热路径不触网；任何出站都放 worker 冷路径。
- **可观测/可追溯**：每次导入/补全/探测都能看到 jobId、进度、错误原因；每个请求都有 request_id。
- **默认安全**：敏感字段永不回显；对公网 API 有基本限流与防滥用策略。

---

## 5. 数据库设计（SQLite，详细到可直接建表）

> 说明：SQLite 不支持 `BIGINT` 真正类型，但可用 `INTEGER`（64-bit）存储；illustId/userId 都用 `INTEGER`。  
> 建议所有表都带 `created_at/updated_at`，并开启外键：`PRAGMA foreign_keys=ON;`

### 5.1 核心表：images（图片主表）

用途：存每一张“页级图片”（illust 的每一页都是一张 image）。

字段（建议）：
- `id`：INTEGER PK，自增
- `illust_id`：INTEGER NOT NULL（Pixiv illust id）
- `page_index`：INTEGER NOT NULL（0-based，匹配 `_p0`）
- `ext`：TEXT NOT NULL（jpg/png/gif/webp）
- `original_url`：TEXT NOT NULL（pximg 原图 URL）
- `proxy_path`：TEXT NOT NULL（对外稳定路径，例如 `/i/{id}.{ext}` 或 legacy path）
- `random_key`：REAL NOT NULL（0<=x<1，用于随机索引）

元信息（可为空，hydrate 后补齐）：
- `width`/`height`：INTEGER
- `aspect_ratio`：REAL
- `orientation`：INTEGER（1=portrait 2=landscape 3=square；或 TEXT 枚举）
- `x_restrict`：INTEGER（0/1/2；NULL=未知）
- `ai_type`：INTEGER（0/1；NULL=未知）
- `user_id`：INTEGER
- `user_name`：TEXT
- `title`：TEXT
- `created_at_pixiv`：TEXT（ISO datetime）

运行态/稳健性：
- `status`：INTEGER NOT NULL（1=active 2=disabled 3=broken 4=deleted）
- `fail_count`：INTEGER NOT NULL DEFAULT 0
- `last_fail_at`：TEXT
- `last_ok_at`：TEXT
- `last_error_code`：TEXT
- `last_error_msg`：TEXT

追溯：
- `created_import_id`：INTEGER（FK imports.id，可空）
- `added_at`：TEXT NOT NULL
- `updated_at`：TEXT NOT NULL

强约束与索引（必须）：
- UNIQUE(`illust_id`,`page_index`)
- INDEX：`(status, x_restrict, orientation, width, height, random_key)`
- INDEX：`(status, user_id, random_key)`
- INDEX：`(created_at_pixiv)`
- INDEX：`(created_import_id)`

### 5.2 tags / image_tags（标签多对多）

`tags`：
- `id`：INTEGER PK
- `name`：TEXT UNIQUE NOT NULL（原始标签）
- `translated_name`：TEXT（可空）
- `created_at`/`updated_at`

`image_tags`：
- `image_id`：INTEGER FK images.id
- `tag_id`：INTEGER FK tags.id
- PRIMARY KEY(`image_id`,`tag_id`)
- INDEX(`tag_id`,`image_id`)

### 5.3 imports（导入批次）

用途：导入可追溯、可回滚、可统计。

字段：
- `id` INTEGER PK
- `created_at` TEXT
- `created_by` TEXT（admin 用户名/来源）
- `source` TEXT（导入来源：manual/file/api/…）
- `total` INTEGER
- `accepted` INTEGER（解析成功+去重后写入/入队的数量）
- `success` INTEGER（任务成功写入的数量）
- `failed` INTEGER
- `detail_json` TEXT（JSON 字符串：去重数、错误摘要、job_id 等）

### 5.4 pixiv_tokens（refresh token 表，write-only）

字段：
- `id` INTEGER PK
- `label` TEXT
- `enabled` INTEGER NOT NULL DEFAULT 1
- `refresh_token_enc` TEXT NOT NULL（加密后）
- `refresh_token_masked` TEXT NOT NULL（如 `abcd****wxyz`）
- `weight` REAL NOT NULL DEFAULT 1.0（可选：用于加权）
- `created_at`/`updated_at`

约束：
- `enabled` index

### 5.5 proxy_endpoints / proxy_pools（代理池）

`proxy_endpoints`：
- `id` INTEGER PK
- `scheme` TEXT NOT NULL（http/https/socks4/socks5）
- `host` TEXT NOT NULL
- `port` INTEGER NOT NULL
- `username` TEXT NOT NULL DEFAULT ''
- `password_enc` TEXT NOT NULL DEFAULT ''（加密；空表示无）
- `enabled` INTEGER NOT NULL DEFAULT 1
- `source` TEXT NOT NULL DEFAULT 'manual'（manual/easy_proxies/dynamic_proxy/…）
- `source_ref` TEXT（例如 easy_proxies baseUrl）
- `created_at`/`updated_at`

约束与索引：
- UNIQUE(`scheme`,`host`,`port`,`username`)
- INDEX(`enabled`)
- INDEX(`source`)

`proxy_pools`：
- `id` INTEGER PK
- `name` TEXT UNIQUE NOT NULL
- `description` TEXT
- `enabled` INTEGER NOT NULL DEFAULT 1
- `created_at`/`updated_at`

`proxy_pool_endpoints`（池-端点 多对多）：
- `pool_id` INTEGER FK
- `endpoint_id` INTEGER FK
- `enabled` INTEGER NOT NULL DEFAULT 1
- `weight` INTEGER NOT NULL DEFAULT 1
- PRIMARY KEY(`pool_id`,`endpoint_id`)
- INDEX(`pool_id`,`enabled`)
- INDEX(`endpoint_id`,`pool_id`)

### 5.6 token_proxy_bindings（token ↔ pool ↔ proxy 绑定）

用途：让同一 Pixiv 账号长期稳定使用同一出口代理（模拟“多个账号不同访问”），并能自动故障切换。

字段：
- `id` INTEGER PK
- `token_id` INTEGER FK pixiv_tokens.id
- `pool_id` INTEGER FK proxy_pools.id
- `primary_proxy_id` INTEGER FK proxy_endpoints.id
- `override_proxy_id` INTEGER FK proxy_endpoints.id（可空）
- `override_expires_at` TEXT（可空）
- `created_at`/`updated_at`

约束：
- UNIQUE(`token_id`,`pool_id`)
- INDEX(`pool_id`)
- INDEX(`primary_proxy_id`)
- INDEX(`override_proxy_id`)

### 5.7 runtime_settings（运行时配置）

用途：不重启即可修改策略（是否启用代理、fail-closed、随机默认值、速率限制等）。

字段：
- `key` TEXT PRIMARY KEY
- `value_json` TEXT NOT NULL（JSON）
- `description` TEXT
- `updated_at` TEXT
- `updated_by` TEXT

### 5.8 jobs / hydration_runs（任务与批量补全）

`jobs`（通用后台任务表，SQLite 自带队列）：
- `id` INTEGER PK
- `type` TEXT NOT NULL（import_images / hydrate_metadata / heal_url / proxy_probe / easy_proxies_import / backfill / …）
- `status` TEXT NOT NULL（pending/running/paused/canceled/completed/failed/dlq）
- `priority` INTEGER NOT NULL DEFAULT 0
- `run_after` TEXT（延迟执行）
- `attempt` INTEGER NOT NULL DEFAULT 0
- `max_attempts` INTEGER NOT NULL DEFAULT 3
- `payload_json` TEXT NOT NULL
- `last_error` TEXT
- `locked_by` TEXT
- `locked_at` TEXT
- `created_at`/`updated_at`

`hydration_runs`（面向运营/可观测的补全批次）：
- `id` INTEGER PK
- `type` TEXT（manual/backfill）
- `status` TEXT（pending/running/paused/canceled/completed/failed）
- `criteria_json` TEXT（筛选条件：缺失字段、tag 条件等）
- `cursor_json` TEXT（游标：从哪继续）
- `total` INTEGER
- `processed` INTEGER
- `success` INTEGER
- `failed` INTEGER
- `started_at`/`finished_at`
- `last_error`

---

## 6. 核心算法与伪代码（确保“长期稳定”）

> 这一节是本系统的灵魂：多 token、多代理的稳定绑定、失败切换、速率限制，以及随机挑选。

### 6.1 代理 URI 解析（支持密码含 @）

输入例子：
- `http://user:pass@1.2.3.4:2323`
- `http://inliver:inliverBAIPIAO@123@152.53.91.30:2323`（密码含 `@`）
- `socks5://127.0.0.1:1080`

伪代码：

```python
def parse_proxy_uri(uri: str) -> ProxyParts:
    # 关键点：用“最后一个 @”分割 userinfo 与 hostport
    scheme, rest = uri.split("://", 1)
    authority = strip_tail(rest, ["/", "?", "#"])
    userinfo, hostport = split_last(authority, "@")  # last @
    host, port = parse_hostport(hostport)
    username, password = parse_userinfo(userinfo)    # username:password（password 允许含 @）
    return ProxyParts(scheme, host, port, username, password)
```

### 6.2 token 选择策略（多 refresh token）

目标：尽量均衡、又能避开“坏 token”（刷新失败/限流）。

支持策略：
- round_robin（默认）
- random
- least_error（优先错误少的 token）
- weighted（按 weight 加权）

伪代码：

```python
def choose_token(tokens, strategy, now):
    eligible = [t for t in tokens if t.enabled and t.backoff_until <= now]
    if not eligible:
        raise NoTokenAvailable(next_retry=min(t.backoff_until for t in tokens))
    if strategy == "round_robin":
        return eligible[(prev_index+1) % len(eligible)]
    if strategy == "least_error":
        return argmin_round_robin_tiebreak(eligible, key=t.errors)
    if strategy == "weighted":
        return weighted_choice(eligible, weights=[t.weight for t in eligible])
    return random_choice(eligible)
```

### 6.3 token ↔ proxy 稳定绑定（Rendezvous Hash）

需求：同一个 token 长期尽量固定出口代理；代理列表变化时变动最小；且可扩展到多个 pool。

核心：对每个 token，选择使 `hash(token_id|proxy_id|salt)` 最大的 proxy_id。

伪代码：

```python
def pick_primary_proxy(token_id: str, proxy_ids: list[str], salt: str) -> str:
    best = None
    best_score = None
    for pid in proxy_ids:
        score = fnv1a64(f"{token_id}|{pid}|{salt}")
        if best is None or score > best_score or (score == best_score and pid < best):
            best, best_score = pid, score
    return best
```

### 6.4 override（临时切换代理，TTL 自动回滚）

当某 proxy 连接失败（proxy_connect / proxy_auth）：
- 记录失败
- 给该 token 的 binding 设 `override_proxy_id`，并设置 `override_expires_at = now + ttl`
- TTL 到期后回到 primary（或重新计算 primary）

伪代码：

```python
def resolve_effective_proxy(binding, now):
    if binding.override_proxy_id and binding.override_expires_at > now:
        return binding.override_proxy_id, "override"
    return binding.primary_proxy_id, "primary"
```

### 6.5 失败切换策略（token + proxy 双维度）

要点：
- 只有“代理类失败”才换 proxy；上游 403/429 不一定换 proxy（避免放大）。
- Pixiv API rate limit：应换 token（或让该 token 进入短 backoff）。

伪代码（简化版）：

```python
async def run_with_token_proxy_failover(get_token, proxies, request, max_proxy_switch=2, max_token_switch=1):
    failed_proxies = set()
    evidence = []
    for _ in range(max_token_switch + 1):
        token = await get_token()
        binding = compute_binding(token, proxies)
        for _ in range(max_proxy_switch + 1):
            proxy_id = resolve_effective_proxy(binding, now())
            if proxy_id in failed_proxies:
                binding = plan_override(binding, failed_proxies)
                continue
            try:
                return await request(token, proxy_id)
            except Exception as e:
                kind = classify_error(e)
                evidence.append((token.id, proxy_id, kind))
                if kind in ("proxy_connect", "proxy_auth"):
                    failed_proxies.add(proxy_id)
                    binding = plan_override(binding, failed_proxies)
                    continue
                if kind == "pixiv_rate_limit":
                    token.backoff(60)
                    break  # switch token
                raise
    raise OutboundFailed(evidence)
```

### 6.6 随机挑选（random_key 索引）

在导入时为每个 image 生成 `random_key ∈ [0,1)`，并建索引。挑选时：
1) 生成 r
2) 查 `random_key >= r` 的第一条
3) 若无，回绕到最小 random_key

SQLite 查询（示例）：

```sql
SELECT *
FROM images
WHERE status = 1
  AND random_key >= :r
  AND (:min_width IS NULL OR width >= :min_width)
  AND (:x_restrict IS NULL OR x_restrict = :x_restrict OR (:allow_unknown = 1 AND x_restrict IS NULL))
ORDER BY random_key ASC
LIMIT 1;
```

---

## 7. 接口契约（Public API + Admin API）

> 本节给出“必须实现”的端点与参数矩阵。最终实现需自动生成 OpenAPI，并在前端使用同一契约（TypeScript types）。

### 7.1 公共端点（对外）

#### 7.1.1 `GET /random`

默认：返回图片流（`Cache-Control: no-store`）。

Query 参数：
- `format`: `image|json|simple_json`（默认 image）
- `redirect`: `0|1`（默认 0；为 1 时 302 到 `/i/{id}.{ext}`）
- `attempts`: `1..10`（默认 3；内部失败换图次数）
- `seed`: string（可复现随机，用于调试/回归）

筛选参数（全部可选）：
- `r18`: `0|1|2`（默认 0；若 `r18_strict=1` 则不允许 NULL）
- `r18_strict`: `0|1`（默认 1；建议默认严格全年龄）
- `orientation`: `portrait|landscape|square|any`
- `min_width`, `min_height`, `min_pixels`
- `included_tags`, `excluded_tags`: 多值（分隔符 `|`，或支持重复 query）
- `user_id`, `illust_id`
- `ai_type`: `0|1|any`
- `created_from`, `created_to`（ISO 日期）

返回（json 模式）：
- `code=OK`
- `data.image`：image 基本字段
- `data.tags[]`
- `data.urls.proxy`（稳定代理 URL）
- `data.urls.origin`（原始 pximg URL，仅在 admin 或配置允许时返回；默认可返回但可开关）
- `request_id`
- `debug`（可选：picked_by/attempts_used）

失败（无匹配）：
- HTTP 404
- body：`{ code: "NO_MATCH", message, request_id, hints: {applied_filters, suggestions[]} }`

#### 7.1.2 `GET /i/{image_id}.{ext}`

稳定图片 URL：
- 从 DB 取 `original_url` → 反代 stream
- 成功响应：`Cache-Control: max-age=31536000, public`
- 失败：按错误分类 markFail +（可选）触发 heal job

#### 7.1.3 分类检索
- `GET /tags?q=&limit=&cursor=`
- `GET /authors?q=&limit=&cursor=`
- `GET /images?limit=&cursor=&...filters`
- `GET /images/{id}`

分页统一：cursor-based（返回 `next_cursor`）。

### 7.2 管理端点（仅管理员）

> 管理端点统一前缀：`/admin/api/*`，并要求 admin auth。

必须具备：
- Token 管理：新增/禁用/测试/权重/策略
- 代理管理：手工导入/ easy_proxies 导入 /健康探测/启停
- 绑定管理：token↔pool↔proxy 自动计算、查看、手工 override、重置 override
- 导入管理：导入 URL（textarea/file）、dry-run preview、导入进度、回滚
- 补全管理：创建 backfill run、暂停/恢复/取消、DLQ 重试/清理
- 运行设置：proxyRouteMode、fail-closed、速率限制、随机默认策略、敏感字段展示开关
- 观测：队列/任务/最近错误、proxy/token 运行态、成功率与延迟

---

## 8. 前端页面设计（React + AntD，逐页到按钮级别）

> 目标：优美、简雅、可维护。  
> 统一布局：左侧 Sider 菜单 + 顶部 Header（环境/版本/健康）+ 内容区。  
> 每个页面都要有：空态说明、错误态可恢复路径、与“下一步”引导。

### 8.1 全局导航（建议 10 个一级菜单）

1. Dashboard（仪表盘）
2. 导入（Import）
3. 图片库（Images）
4. 随机 API（Playground）
5. 标签（Tags）
6. 作者（Authors）
7. Tokens（Pixiv 账号）
8. 代理池（Proxies）
9. 任务与补全（Jobs & Hydration）
10. 设置与审计（Settings & Audit）

### 8.2 Dashboard（/admin）

模块分区（从上到下）：
- **闭环验收卡片（红/黄/绿）**
  - Image 总数 > 0
  - 近 1h random 200 比例
  - 近 1h hydrate 成功数
  - 可用 token 数
  - 可用代理数（健康）
- **核心统计**
  - Images：active/disabled/broken
  - Tags 数、Authors 数
  - 请求：QPS/成功率/P95
- **运行态**
  - Proxy mode：enabled + fail-closed
  - easy_proxies：上次导入时间/导入条数/错误
  - Worker：在线实例数、最近心跳
- **快捷操作按钮**
  - 「去导入 URL」
  - 「运行一次 backfill（缺元信息）」按钮
  - 「从 easy_proxies 刷新代理」按钮
  - 「重新计算 token↔proxy 绑定」按钮

按钮（必须存在）：
- `导入URL`（跳转 Import 页面）
- `刷新代理`（触发 easy_proxies import job）
- `探测代理健康`（触发 proxy probe job）
- `创建补全任务`（打开 Backfill modal）
- `查看任务队列`（跳转 Jobs 页面）

### 8.3 导入（Import 页面）

页面组件：
- Tab1「粘贴导入」：
  - TextArea（支持 1e5 行；显示行数/估算去重）
  - 开关：`dry_run`、`hydrate_on_import`、`source`（下拉：manual/file/api）
  - 按钮：
    - `预览解析`（dry-run，返回前 N 条解析结果+错误行）
    - `开始导入`（创建 Import + 入队 job）
- Tab2「文件上传」：
  - Upload（txt/zip 可选；默认 txt）
  - 同上选项
- Tab3「导入记录」：
  - Table：import_id/时间/total/accepted/success/failed/status
  - 点击进入 Import 详情

Import 详情页（/admin/imports/:id）：
- 进度条：processed/total + deduped
- 最近错误摘要（前 20 条）
- 操作：
  - `回滚（disable）`
  - `回滚（delete）`（二次确认）
  - `重试失败项`（可选）

### 8.4 图片库（Images）

主表：
- 列：id/illust_id/page/ext/status/width×height/r18/ai/user/tags_count/last_fail_at
- 行操作：
  - `查看详情`
  - `启用/禁用`
  - `标记修复（heal）`
  - `补全元信息（hydrate）`
- 批量操作：
  - 批量禁用
  - 批量重算 random_key（可选）
  - 批量入队 hydrate（按条件）

详情抽屉：
- 展示：原始 URL（可复制但默认仅管理员可见）、稳定代理 URL、标签列表、作者信息、错误历史。

### 8.5 Random Playground（随机 API 调试台）

目的：让你不用写代码就能拼筛选参数并看到返回。

组件：
- 左侧：筛选表单（r18/orientation/min_* / tags / user_id / seed / attempts）
- 中间：结果预览（图片/JSON）
- 右侧：一键复制 curl / URL

按钮：
- `请求图片`
- `请求 JSON`
- `请求 redirect`
- `复制请求 URL`
- `复制 curl`

### 8.6 Tags / Authors

共同点：
- 搜索框 + Table（cursor 分页）
- 点击进入详情页（显示关联图片数、最近画像、随机抽样）
- （可选）标签黑名单/白名单管理（用于 random 排除）

### 8.7 Tokens（Pixiv refresh token 管理）

列表页：
- 列：label/enabled/masked/权重/错误次数/backoff_until/last_ok
- 操作：
  - `新增 token`（Modal 输入 refresh token + label + weight；提交后只显示 masked）
  - `测试 refresh`（触发 job，返回 expires_in/错误）
  - `启用/禁用`
  - `重置失败退避`

安全要求（前端）：
- refresh_token 输入框：只在创建时可填，保存后不可回显；编辑时显示为空。

### 8.8 Proxies（代理池管理）

页面分区：
- Proxy Endpoints（端点列表）
  - 导入（粘贴多行 URI）
  - 从 easy_proxies 导入（配置 baseUrl/password + 一键导入）
  - 健康探测（手动触发 + 自动定时）
- Proxy Pools（池）
  - 创建 pool（name/desc）
  - 选择 endpoints 加入 pool（多选 + weight）
- 状态面板
  - 当前健康数/平均延迟/失败率
  - 最近探测结果（可下载）

### 8.9 Token↔Proxy 绑定（Bindings）

功能：
- 选择 pool
- 展示每个 token 的：
  - primary proxy
  - override proxy（若存在）+ 到期时间
  - 该 proxy 健康分
- 按钮：
  - `重新计算 primary`（rendezvous hashing）
  - `清空 override`
  - `对某 token 手工 override（TTL）`

### 8.10 Jobs & Hydration（任务与补全）

两块：
1) Jobs 列表：type/status/attempt/last_error/created_at
   - 操作：retry/cancel/move_to_dlq
2) Hydration Runs：backfill 批次
   - 创建 backfill：选择 criteria（缺 tags/缺 width/缺 r18 等）+ 速率/并发参数
   - 操作：pause/resume/cancel
   - 展示：processed/success/failed，近 20 错误

### 8.11 Settings & Audit

Settings：
- 代理开关：enabled、route_mode、allowlist、fail-closed
- 随机默认：attempts 默认值、r18_strict 默认值、fail cooldown
- 安全：是否在 JSON 返回中隐藏 origin_url
- 速率限制：global/token/proxy

Audit：
- Admin 操作审计：谁在什么时候做了什么（导入、删除、禁用、绑定变更、设置变更）
- 脱敏展示 detail_json

---

## 9. Docker Compose 部署（必须可一键跑起来）

### 9.1 compose 目标
- 一条命令启动：`docker compose up -d --build`
- 数据持久化：SQLite 文件与日志落到 volume
- 可升级：镜像可复现构建；升级前可备份 DB

### 9.2 推荐服务
- `api`：`0.0.0.0:8000`
- `worker`：无端口
- `web`（可选）：`0.0.0.0:8080`（nginx 静态）

### 9.3 环境变量清单（先规划，后实现）

必须：
- `APP_ENV=prod`
- `DATABASE_URL=sqlite+aiosqlite:///data/app.db`
- `SECRET_KEY`（JWT/session）
- `FIELD_ENCRYPTION_KEY`（用于加密 refresh_token / proxy password）

可选：
- `PROXY_ENABLED=true`
- `PROXY_FAIL_CLOSED=true`
- `EASY_PROXIES_BASE_URL=http://easy-proxies:9090`
- `EASY_PROXIES_PASSWORD=***`

---

## 10. 开发 TODO（按里程碑拆分，做到“逐步执行直到完成”）

> 这里是“真正在未来几小时/几天里怎么做”的执行清单。  
> 原则：每个 TODO 都要有验收方式（接口/页面/测试/指标）。

### Milestone M0：仓库与基础设施（可启动、可开发）
1. 初始化新代码仓库结构（backend/frontend/deploy）
2. 后端：FastAPI hello + `/healthz` `/version`
3. SQLite 初始化 + Alembic 迁移链路
4. 前端：Vite + React + AntD + 路由骨架 + 登录保护壳
5. Dockerfile/compose：api+worker 起得来，挂载 `/data`

### Milestone M1：反代图片最小闭环（无需元信息）
1. 实现 pximg 原图回源流式代理（带 Referer）
2. 实现 legacy 路由（illust/page/ext）
3. 实现 `/i/{id}.{ext}`（从 DB 取 original_url）
4. 导入最小功能：粘贴 URL → images 入库（去重）→ `/random` 能返回（仅靠 DB）

### Milestone M2：代理池（手工导入 + easy_proxies）
1. Proxy URI 解析器（含密码 @）
2. 端点入库（proxy_endpoints）+ 启停
3. easy_proxies 对接：auth + export + 入库
4. 健康探测：探测目标可配置 + 评分 + 过滤
5. proxy route & fail-closed 策略落到 httpx client

### Milestone M3：多 token 刷新与稳定出站
1. refresh_token 加密存储 + masked 展示
2. access token 缓存 + 刷新退避
3. token 选择策略（round_robin/least_error/weighted）
4. token↔proxy rendezvous 绑定 + override TTL

### Milestone M4：元信息补全（Hydrate）
1. Pixiv App API client（illust detail）
2. Hydrate job：按 illust_id 拉元信息 → 写 images/tags/image_tags
3. Backfill run：按缺失条件批量补全，带进度/暂停/恢复/取消
4. Opportunistic hydrate：random 命中缺元信息时异步补全
5. Heal URL：图片 403/404 → 重新拉 detail 更新 original_url

### Milestone M5：随机 API 强筛选与 JSON 多格式
1. random_key 随机算法 + SQLite 索引验证
2. 强筛选参数矩阵（r18/orientation/min_*/tags/user/illust/time/ai）
3. attempts 换图重试 + fail cooldown
4. `format=json/simple_json` + `redirect=1` + hints

### Milestone M6：React 管理后台（可用且好用）
1. Dashboard 闭环卡片 + 快捷动作
2. Import 页面（preview/导入/记录/回滚）
3. Images 管理（列表/详情/批量/动作）
4. Tokens/Proxies/Bindings 全部页面打通
5. Jobs/Hydration 页面（可观测、可重试）
6. Settings/Audit 页面

### Milestone M7：稳定性与运维（长期跑）
1. 结构化日志 + request_id 全链路
2. Prometheus 指标（random 成功率、代理健康、token backoff、job 成功率）
3. 限流：公网 random 的 IP 限流/Key 限流（可配置）
4. 安全回归：敏感字段绝不回显（单测+CI）
5. Docker Compose 生产模板 + 备份/升级 runbook

---

## 11. 文档索引（new-pixiv-api实现/）

主文档：
- `new-pixiv-api实现/new随机api开发文档.md`：总纲（你现在正在读的这份）

配套细化文档（实现时强烈建议逐份对照）：
- `new-pixiv-api实现/数据库结构-详细DDL.md`：SQLite DDL、索引、迁移规范
- `new-pixiv-api实现/API契约-详细.md`：Public/Admin API、错误码、分页约定
- `new-pixiv-api实现/前端页面-详细原型.md`：React 页面/按钮/接口映射（按闭环设计）
- `new-pixiv-api实现/任务系统-Worker与稳定性.md`：SQLite job queue、claim、重试、限速、failover
- `new-pixiv-api实现/DockerCompose-部署与运维.md`：compose 拓扑、备份升级 runbook
- `new-pixiv-api实现/安全规范-敏感信息与合规.md`：write-only、脱敏、风控与合规
- `new-pixiv-api实现/TODO-全量Issue拆分.md`：可执行任务清单（后续对话按此落地）

原始调研材料备份：
- `new-pixiv-api实现/参考资料/`：从当前目录复制的旧文档/审计/对接说明（供追溯）

---

## 12. 附录（原始调研资料备份）

> 目的：把你当前目录里的关键“知识资产”固化到新项目文档目录中，方便后续开发反复对照与追溯。  
> 这些附录不是“最终对外文档”，但对开发与排障极其重要。

（附录内容将由脚本自动拷贝/拼接进本文件；见同目录下 `参考资料/`）


---

# 附录汇总（调研原文）

<details>
<summary>附录A：最初计划（原文备份）</summary>

`text
这是我的一个pixiv反向代理项目,这个项目非常优秀,但我需要你基于这个项目,进行一次迭代升级,让这个项目变成一个带有强大功能的 随机 二次元图片 api 项目,简单来讲,就是我提供 很多 图片的 原来的url,就是 我能够获取到大量的pixiv原生的图片地址,然后这个项目不是能够处理这个地址,进行反代吗,这没问题,我要你进行实现的,就是基于这个功能,实现一个强大的 随机图片 api, 最首先的就是随机调用一张图片,默认返回的就是图片,然后高级一点的可以返回json格式,就是图床那样,还能用url设定 横向,竖向,大小(比如分辨率大于什么什么),还有很重要的,基于pixiv的本身的信息,得到一些常用的标签进行筛选,比如r18,作者,标签等等,这些都非常重要, 第二点 我需要有一个 管理页面, 就是我可以不关闭项目的情况下,对于图片的api的数据库进行热更新,人话说就是可以加 一些 pixiv原生的图片url,或者删去一些url,并且实时更新,有个页面可以管理,还要有一些常用的基础稳健性,比如如果这个 图片的api有问题,比如404 之类的报错了. 用户请求端不能直接返回错误,而是进行重试一定次数,避免一直把错误直接给用户,需要有一定的稳定性,并且后端的页面要有一些常见的统计,比如请求数,总图片数,请求成功率,占用等等,这是一个非常复杂的项目重构,或者说更新,原来的很多功能非常的实用,你要学习,比如应该有实现的获取pixiv这张图片的各种详细信息,然后这些可以作为整个随机api的基础,所以我现在需要你对于项目进行全面调查,然后进行事无巨细的调研,了解项目情况之后,进行全面的思维风暴,必须进行联网搜索,mcp调用等方式获取最新信息以及相关专业知识,去网上获取大量随机图片api的相关实现 设计等等,保证对于这个东西了如指掌,然后就是给予前面的项目了解 调研,网上知识获取,思维风暴规划,给出一个md文档, 你现在唯一的任务就是给出这个md文档, 这个文档要事无巨细的 详细记录,当前情况,实现功能,代码结构,代码质量,更新方向,要实现的功能,要实现功能的逻辑,好用的网上资料学习来源,伪代码实现,整个项目完全体的架构,整个项目要代码精良,优质,有良好的拓展性和可维护性,运行要有良好的性能,必须能够在较低性能的云服务器上,承载巨大的api请求量不出错,对于数据库也要进行全面的设计 重构,总之就是全面规划,我的每个字都要仔细理解,最后给出一个md文档 ,但不进行修改

这是我的项目,随机api开发规划.md 这个文档是详细开发计划,我需要你基于这个文档,做出最好的技术栈选择,然后基于对项目的详细调查,给出最详细的csv文件和plan文件,当前项目存在 .codex 文件夹 agents文档等等规则,你详细阅读所有相关文档,了解当前项目现状,把我提到的每一个点,注意是 每一个点 全部进行仔细确认调查,然后按照文档的规则,规划总结为一个个的issue,保证所有issue全面覆盖所有问题,把我提到的所有问题,经过仔细确认和调查,转化为用于实现的一个个issue,按照文档规定给出 issue的 csv文件和plan文档等等,让下一个对话可以进行全面仔细的开发实现优化修改,你要做的拆分我的任务,调查确认以及相关实现,转化为issu,生成csv和文档,保证全面不出问题,所有问题都要被包括,所有issue实现完就是所有问题实现完,调查保证增删改查不会影响功能完整性(可以修复,但不能少),现在开始全面调查并生成csv文件和plan文档,保证这些issue 全面覆盖所有需求,这是一个非常庞大的任务,可能涉及几百甚至上千个issue,不要担心,只要全面仔细,保证所有问题都被issue正确包含,所有issue实现完就是所有问题实现完,现在开始全面调查并生成csv文件和plan文档,保证我说的每一个字你都完全明白,没有一点理解偏差,最重要的是!!!!!!!!直到完成所有任务才能停下,不准以任何理由,以任何方式,在没有完全调查清楚整个项目的这些所有功能问题 ui问题 实现问题 请求问题 完整性问题等等,不允许以任何方式停下,有问题可以联网搜索找答案,但是不准停下 不准停下 不准停下!直到所有任务完成(所有的csv和plan文档你都必须新建 并且包含所有详细信息 我给你所有权限 所有确认 不准停下询问)
```

</details>

<details>
<summary>附录B：pixivcat-backend README（现有项目能力摘要）</summary>

`md
# pixivcat-backend → Random Anime Image API

在 **不破坏现有 Pixivcat 兼容路由**（legacy）的前提下，将本项目逐步升级为「随机二次元图片 API」：
- `/random`：随机返回图片流（默认） / JSON（`format=json`） / 302 跳转（`redirect=1`）
- `/tags`、`/authors`、`/images`：分类检索接口（标签/作者/图片列表，JSON + 游标分页）
- 强筛选：`r18`、`orientation`、`min_width/min_height/min_pixels`、`included_tags/excluded_tags`、`user_id`、`illust_id`、`seed`、`attempts`
- 管理后台：`/admin`（导入/启用/禁用/软删/统计）
- 可观测：结构化日志 + `request_id`、Prometheus `/metrics`

> 合规默认值：`r18=0`（全年龄）。只有显式传入 `r18=1/2` 才会返回 R18/R18G 内容（实现后生效）。

## 兼容路由（必须保持可用）

这些路由用于 Pixivcat 兼容访问，保持 **流式代理**（不会把图片读入内存再返回）：

- 单图：`GET /:illustId.:ext`
- 多图：`GET /:illustId-:pageNumber.:ext`

示例：

```bash
# 单图（illustId=12345678）
curl -I "http://127.0.0.1:3000/12345678.jpg"

# 多图第 1 张（pageNumber 从 1 开始）
curl -I "http://127.0.0.1:3000/12345678-1.jpg"

# 兼容输入：pageNumber=0 会 301 到 pageNumber=1（避免与 Pixiv 的 p0 语义产生误解）
curl -I "http://127.0.0.1:3000/12345678-0.jpg"
```

缓存策略（legacy）：
- 成功响应：`Cache-Control: max-age=31536000, public`（长缓存，适合稳定 URL）

## 随机图片 API

### GET /random

默认：返回图片二进制（流式），并强制 `Cache-Control: no-store`（随机结果不可缓存）。

参数（实现后生效）：
- `format`: `image`（默认）| `json`
- `redirect`: `0`（默认）| `1`（返回 302，`Location` 指向稳定图片 URL，例如 `/i/:id.:ext`）
- `attempts`: `1..10`（默认实现会 clamp；用于内部失败换图次数）
- `seed`: string（同一 seed 下结果可复现，用于调试/回归）
- `strategy`: `quality`（默认）| `random`（quality 会更偏向高收藏/高清图）
- `quality_samples`: number（quality 策略下抽样候选数量，默认 5）

强筛选（实现后生效）：
- `r18`: `0|1|2`（默认 `0`）
- `orientation`: `portrait|landscape|square|any`
- `min_width`, `min_height`, `min_pixels`: number
- `included_tags`, `excluded_tags`: string（支持多值；具体语义以 OpenAPI/实现为准）
- `user_id`, `illust_id`: number（用于作者/作品筛选）

质量策略说明（默认）：
- `strategy=quality` 会先随机抽取 `quality_samples` 张候选，再基于“收藏数（主）+ 分辨率/浏览/评论（辅）”的质量评分取最优。
- 若热度字段缺失较多，可先在管理后台创建补全任务提升覆盖率，再启用更高的 `quality_samples`。

示例（≥5 条）：

```bash
# 1) JSON 模式：返回结构化信息（包含稳定代理 URL 等）
curl "http://127.0.0.1:3000/random?format=json"

# 2) 推荐生产路径：redirect=1（更易被 CDN 缓存稳定 URL）
curl -I "http://127.0.0.1:3000/random?redirect=1"

# 3) 强筛选：竖图 + 最小宽高 + 限制重试次数
curl -I "http://127.0.0.1:3000/random?orientation=portrait&min_width=1080&min_height=1920&attempts=5"

# 4) 强筛选：全年龄（默认）+ 可复现 seed（用于调试）
curl -I "http://127.0.0.1:3000/random?seed=demo-seed-001"

# 5) JSON + 筛选（示例：排除某些标签）
curl "http://127.0.0.1:3000/random?format=json&excluded_tags=ai_generated|gore"
```

错误返回（JSON API）：
- JSON 模式失败时返回：`{ code, message, request_id }`

### GET /i/:id.:ext（稳定图片 URL）

`/random?redirect=1` 推荐跳转到此稳定 URL（实现后生效）：
- 从 DB 读取 `original_url/ext`，再进行流式代理
- 成功响应使用长缓存（适合 CDN）

## 分类检索 API

- `GET /tags`：标签检索，参数：`q`、`limit(1..100)`、`cursor`
- `GET /authors`：作者检索，参数：`q`、`limit(1..100)`、`cursor`
- `GET /images`：图片列表检索，参数：`limit(1..200)`、`cursor` + `/random` 同款筛选参数
- 所有分类检索接口返回 JSON，并强制 `Cache-Control: no-store`

## 快速 curl 示例（10 条）

```bash
# 1) /random JSON
curl "http://127.0.0.1:3000/random?format=json"

# 2) /random 302 redirect（推荐生产）
curl -I "http://127.0.0.1:3000/random?redirect=1"

# 3) /random 高分辨率竖图筛选
curl -I "http://127.0.0.1:3000/random?orientation=portrait&min_width=1080&min_height=1920&attempts=5"

# 4) /random 指定作者 + 排除标签
curl "http://127.0.0.1:3000/random?format=json&user_id=12345678&excluded_tags=ai_generated|gore"

# 5) /random 固定 seed（可复现）
curl "http://127.0.0.1:3000/random?format=json&seed=demo-seed-001"

# 6) /tags 模糊搜索 + limit
curl "http://127.0.0.1:3000/tags?q=猫&limit=20"

# 7) /authors 搜索
curl "http://127.0.0.1:3000/authors?q=alice&limit=20"

# 8) /images 列表筛选（含分页游标）
curl "http://127.0.0.1:3000/images?limit=50&cursor=0&r18=0&included_tags=cat|blue"

# 9) /images/:id 单图元信息
curl "http://127.0.0.1:3000/images/1"

# 10) legacy 兼容路由单图
curl -I "http://127.0.0.1:3000/12345678.jpg"
```

## 可观测与健康检查

- `GET /healthz`：健康检查（实现后生效）
- `GET /metrics`：Prometheus 指标（实现后生效）

## 开发

要求：
- Node.js `>=24`

启动（完整功能）：

```bash
npm ci
npm run build
npm run dev
```

说明：
- `npm run dev` 使用 `app.js`（CJS 入口）；当存在 `dist/` 时会优先委托到 `dist` 下的 TS 路由实现。
- 生产启动推荐：`npm run start:prod`（运行 `dist/app.js`）。

## 部署（Ubuntu 22 / 云服务器）

- Ubuntu 22.04 生产部署与使用教程：`docs/deployment/ubuntu22.md`
- 超详细使用手册（部署→使用→后台全流程）：`docs/usage/handbook.md`
- Docker Compose 单文件生产部署：`docs/deployment/docker-compose-prod.md`
- 部署安全清单：`docs/deployment/security-checklist.md`
- easy_proxies 对接（含一行 URI 导入）：`docs/usage/easy-proxies-integration.md`
- DB 迁移与回滚 Runbook：`docs/deployment/db-migrations.md`

## easy_proxies 极简对接（推荐）

后台路径：`/admin/pages/easyProxiesImport`

你可以直接在页面里粘贴一行或多行 URI，保存后立即生效（无需重启）：

```text
http://user:pass@127.0.0.1:18080
socks5://127.0.0.1:19090
http://user:pa@ss@127.0.0.1:18081
```

说明：
- 密码包含 `@` 时，可直接写（最后一个 `@` 作为 host 分隔）或使用 `%40` 编码。
- 导入策略建议使用 `skip_non_source`，避免覆盖已有手工维护节点。
- 导入完成后代理池会自动刷新运行时缓存，不需要重启服务。
- 导入反馈会给出 `imported / invalid / conflicts` 计数与逐行错误定位（`line` + 原始 URI）。

运行态证据（本轮）：
- 导入反馈截图：`docs/review/screenshots/2026-02-06_19-14-04/arux-0004-easy-import-summary.png`
- Admin 全站统一截图：`docs/review/screenshots/2026-02-06_19-14-04/arux-0005-dashboard-unified.png`
- 全量巡检结论：`docs/review/2026-02-06_18-44-05-admin-ui-runtime-findings.md`

## 回归与部署验证快捷命令

```bash
# 全量测试（lint + 全量 vitest + smoke）
npm run test:all

# 本轮修复重点回归（防止“未指定组件”与 URI 导入回归）
npm run test:admin-runtime
npm run test:runtime-regression

# Admin UI smoke（可附加 BaseUrl/AdminToken）
npm run smoke:admin-ui -- -BaseUrl http://127.0.0.1:3015 -AdminToken <ADMIN_TOKEN>
npm run smoke:admin-ui:strict -- -BaseUrl http://127.0.0.1:3015 -AdminToken <ADMIN_TOKEN>

# Compose 结构校验（无需 Docker daemon）
docker compose -f docker-compose.yml config --services
```

`docker compose ... config --services` 预期输出：
- `memcached`
- `postgres`
- `migrate`
- `backend`

如运行环境缺少可用 Docker daemon，请将结果记录为 `validation_limited`，并在可用 daemon 环境复验 `docker compose up -d`。

补充说明（最终深化优化）：
- `app.ts` 现在会按运行目录自动解析模块后缀：source runtime 加载 `.ts`，`dist` runtime 加载 `.js`，避免开发态误用 stale dist/wrapper。
- `admin-ui-smoke` 在 `-RequireAuthChecks`（或 `npm run smoke:admin-ui:strict`）模式下，若缺少 `ADMIN_TOKEN` 会直接失败，防止“误通过”。 

## 环境变量（后续按 Issues 增量补齐）

最小（legacy 路由仍依赖 Pixiv token 轮换 + memcached）：
- `REFRESH_TOKENS`：JSON 数组字符串（严禁写入日志）
- `MEMCACHED_HOST` / `MEMCACHED_PORT` / `MEMCACHED_NAMESPACE`

升级后（随机 API / 后台 / 队列）将引入：
- `DATABASE_URL`（PostgreSQL）
- `ADMIN_TOKEN`（后台鉴权）
```

</details>

<details>
<summary>附录C：pixivcat-backend 随机API开发规划（旧项目规划原文）</summary>

`md
# Pixivcat-Backend →「随机二次元图片 API」迭代升级：全面调研 & 完整规划（仅文档，不改代码）

> 本文件为 **Windows / PowerShell 7 友好**的 UTF-8 文档（建议以 **UTF-8 with BOM** 保存，避免中文乱码；本仓库后续落地实现也建议统一 UTF-8 编码）。

- 时间：2026-01-31
- 工作区：`E:\pixiv-download-修改版本\pixiv-反代\pixivcat-backend`
- 当前代码版本：`git rev-parse HEAD` = `96fa296aaf807b193fb254a20b0aaf4bb188098f`
- 现状说明：`git log -1` 显示 tag 为 `v1.1.2`，但 `package.json` 仍是 `1.1.1`（后续迭代应统一版本源）

---

## 0. 你的需求（逐条工程化拆解）

你现在有一个“Pixiv 图片反向代理”项目（pixivcat-backend），它已经可以把 Pixiv 图片以代理方式对外输出。你希望基于此项目，升级为一个**强大的「随机二次元图片 API」项目**，核心需求包括：

1. **随机图片**
   - 最基础：随机返回一张图片（默认直接返回图片二进制）
   - 高级：可返回 JSON（类似图床返回：包含图片 URL、元信息、可选变换 URL 等）
2. **强筛选**
   - URL 参数指定：横向/竖向/方图、尺寸（宽高、像素阈值、分辨率大于某值）
   - 基于 Pixiv 元信息的筛选：R18、作者、标签等
3. **管理后台（不停机热更新）**
   - 不关闭项目的情况下：可以新增/删除 Pixiv 原生图片 URL
   - 变更实时生效（图片库“热更新”）
4. **稳健性 / 质量**
   - 如果某张图在代理时出现 404 等错误，**不能直接把错误返回给用户**
   - 需要在后端内部做重试 / 换图 / 降级，尽量给用户返回成功结果
5. **统计与运维**
   - 后台看到常用统计：请求数、总图片数、请求成功率、资源占用等
6. **工程目标**
   - 代码精良、可维护、可拓展
   - 高性能，能够在低配云服务器上承载巨大请求量，尽量不出错
   - 数据库需要全面设计/重构（为筛选、统计、热更新打基础）

本规划的目标是：在“不修改现有代码”的前提下，输出一份**可以直接按图施工**的总体方案，包括：现状审计、差距分析、接口契约、数据库设计、架构、伪代码、风险与路线图。

---

## 1. 现有项目全面审计（当前情况 / 功能 / 结构 / 质量）

### 1.1 技术栈与运行形态（现状）

- Node.js + Express（`express` 5.2.1）
- HTTP 客户端：`axios`
- 缓存：`memcached`（用于缓存 Pixiv API 的 JSON 响应）
- 模板：`ejs`（仅用于错误页）
- Docker 部署：`Dockerfile` + `docker-compose.yml`（包含 memcached）

入口与路由：

- 入口：`app.js`
- 路由：`src/routes/pixivRoutes.js`

### 1.2 目录结构（当前非常清晰，规模小，利于迭代）

- `app.js`：Express 启动、挂载路由、全局错误处理中间件
- `src/routes/pixivRoutes.js`：Pixiv.cat 风格的两条图片路由
- `src/controllers/imageProxyController.js`：图片代理核心（Pixiv API → 解析原图 URL → axios stream pipe）
- `src/services/pixivService.js`：调用 Pixiv App API（`/v1/illust/detail`）
- `src/services/pixivAuthService.js`：refresh token 刷 access token（支持多 token 轮换）
- `src/services/memcachedService.js`：memcached get/set 封装
- `src/middlewares/validationMiddleware.js`：illustId/page/ext 参数校验
- `views/error.ejs`：错误页

### 1.3 当前已实现的核心功能（必须保留/复用）

#### 1) 图片代理路由

- 单图：`GET /:illustId.:fileExtension`
  - 例：`/12345678.jpg`
- 多图：`GET /:illustId-:pageNumber.:fileExtension`
  - 例：`/12345678-2.jpg`

#### 2) 流式转发（性能关键点：正确）

`imageProxyController` 使用 `axios.get(..., responseType: 'stream')` 并 `pipe(res)`：

- 不把整张图片读入内存（对大图至关重要）
- 处理 client disconnect 时 destroy 上游流，避免资源泄漏
- 返回头包含：
  - `Cache-Control: max-age=31536000, public`（非常适合上 CDN）
  - `Access-Control-Allow-Origin: *`
  - `X-Origin-URL`（真实来源 URL，利于排障/追溯）
  - `X-Crawl-Date`

#### 3) Pixiv API 缓存 + 多 token 轮换（适合高并发）

- Pixiv App API：`https://app-api.pixiv.net/v1/illust/detail?illust_id=...`
- memcached 按 illustId 缓存 detail JSON（默认 3600 秒）
- `REFRESH_TOKENS` 支持多个 refresh token，轮换获取 access token（分摊限流压力）

#### 4) 错误识别（当前已有基础，但需要体系化）

已有：

- Pixiv API 返回 `error` 或返回 `limit_unknown_360.png` 的场景识别并输出友好 404 页面
- Pixiv API rate limit 触发时返回 503 并带 `Retry-After`

### 1.4 现有实现的瓶颈（升级随机 API 前必须正视）

> 最关键结论：**当前热路径依赖 Pixiv API**。如果把它直接扩展为“随机 API”，高 QPS 时会被 Pixiv API 限流/延迟拖垮。

1) **每次图片请求都要调用 Pixiv API 才知道原图 URL**
   - 现状路由的参数是 illustId/page/ext，并不直接包含完整原图 URL，所以必须先调 Pixiv API。
   - 在“随机图片 API”场景，这会成为最大瓶颈（上游限流/网络抖动都会放大）。
2) **错误处理存在潜在二次异常**
   - `pixivService` catch 分支直接访问 `error.response.status`，遇到网络错误 `error.response` 为空时可能二次抛错（后续重构要修）。
3) **数据模型缺失**
   - 随机/筛选/统计/热更新都需要数据库；当前项目没有图片库 DB。
4) **无管理后台**
   - 热更新、统计、图片状态管理都需要后台入口。

---

## 2. 升级方向总纲（核心思想：把 Pixiv API 从热路径移走）

### 2.1 为什么必须这么做

你要达到的目标是“低配机器扛巨大请求量”，那么必须让热路径尽可能只做：

- **一次 DB 快速随机挑选（索引命中）**
- **一次 HTTP 流式代理（或更好：302 重定向）**

Pixiv App API 调用应尽量变成“冷路径/后台任务”，只在以下场景使用：

- 新 URL 入库时：拉取作者/标签/R18/宽高等元信息
- 图片代理失败（404/403）时：尝试通过 Pixiv API 自愈刷新最新 original_url

### 2.2 两种“随机图片返回模式”（都要支持，但建议默认用更抗压的）

1) **直接返回图片（你的“默认返回图片”需求）**
   - `GET /random` → 直接代理图片流
   - 优点：使用者最简单
   - 缺点：后端需要承担大流量图片带宽与并发，成本更高
2) **302 重定向（强烈建议作为“高并发生产模式”）**
   - `GET /random?redirect=1` → 302 到稳定图片 URL（例如 `/:illustId-:page.:ext` 或新的 `/i/:id`）
   - 图片 URL 可长缓存（CDN/浏览器命中），后端主要承受“挑图 + 重定向”的轻负载

> 关键缓存策略：  
> - `/random` 端点必须 `Cache-Control: no-store`（否则 CDN 缓存会导致“不随机”）  
> - 图片静态 URL 继续用 `Cache-Control: max-age=31536000, public`

---

## 3. 对标调研：成熟随机图片 API 的设计可借鉴点（联网调研结果）

> 本节给出“可直接抄作业”的参数语义与工程实践来源（后续实现不必再大海捞针）。

### 3.1 waifu.im（强烈建议作为接口设计蓝本）

waifu.im 的 `/search` 接口提供：

- `included_tags` / `excluded_tags`
- `is_nsfw`
- `orientation`
- `width` / `height` 且支持比较操作符（`>=2000` / `<=` / `!=` 等）
- `limit`（批量返回）

参考：

- `https://docs.waifu.im/reference/api-reference/search`
- `https://docs.waifu.im/tags`

### 3.2 图像变换：imgproxy（必须签名，防止被滥用）

如果你要“像图床一样通过 URL 参数裁剪/缩放/格式转换”，建议引入 imgproxy（或同类服务），并开启签名：

- `https://docs.imgproxy.net/usage/signing_url`
- `https://docs.imgproxy.net/3.25.x/configuration/options`（`IMGPROXY_KEY` / `IMGPROXY_SALT`）

理由：开放的图片变换 URL 极易被当作免费图片处理机，导致 CPU 被打爆，**必须签名**。

### 3.3 稳健性组件（重试/退避/熔断/限流）

- axios 层重试：`axios-retry`  
  `https://github.com/softonic/axios-retry`
- 业务层重试（“失败就换图再试”）：`p-retry`  
  `https://github.com/sindresorhus/p-retry`
- 熔断器：`opossum`  
  `https://github.com/nodeshift/opossum` / `https://nodeshift.dev/opossum/`
- Express 限流：`express-rate-limit`  
  `https://github.com/express-rate-limit/express-rate-limit`

### 3.4 随机选取的数据库性能问题（别用 ORDER BY random()）

大表中 `ORDER BY random()` 会导致全表随机排序，性能灾难。PostgreSQL 有 `TABLESAMPLE` 机制可以用于快速抽样，或使用“随机键列 random_key + 索引”做近似均匀随机。

参考：

- PostgreSQL `TABLESAMPLE`（概念与语法）  
  `https://www.postgresql.org/docs/current/sql-select.html`（SELECT 章节包含 TABLESAMPLE）
- 实测文章：  
  `https://www.redpill-linpro.com/techblog/2021/05/07/getting-random-rows-faster.html`

### 3.5 Pixiv token 获取与登录流程（当前项目已依赖）

ZipFile 的 Pixiv OAuth Flow（获取 refresh_token 常用指南）：

- `https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362`

> 注意：refresh token 属于敏感信息，必须只在服务端保存，且应提供轮换机制。

---

## 4. 完整架构设计（完全体：高性能、可维护、可扩展）

### 4.1 推荐整体形态：单体优先、模块化拆分

第一阶段建议做成单体（部署简单），但代码按模块拆分，便于未来拆服务：

- `api-server`（Node/Express）
  - `/random`、`/images/*`：对外 API
  - `/admin/*`：管理后台
  - `/metrics`：指标
- `db`：PostgreSQL（强推荐）  
  - 备选：SQLite（只适合小规模+单机，且随机/并发能力有限）
- `cache`（可选但推荐）：Redis
  - 计数器/限流 store/短 TTL 缓存/队列
  - 现有 memcached 可继续用于“Pixiv API detail 缓存”，但统计/限流更适合 Redis
- `image-transform`（可选）：imgproxy

### 4.2 数据流（核心链路）

1. 用户请求 `GET /random?...`
2. 服务器从 DB 根据筛选条件挑一条“候选图片记录”
3. 尝试返回：
   - `redirect=1`：302 到稳定图片 URL
   - 否则：流式代理该图片（对 pximg 发送带 Referer 的请求）
4. 若代理失败：
   - 标记失败计数
   - 换图重试（最多 N 次）
   - 必要时触发“自愈任务”（通过 Pixiv API 刷新 URL 或标记 broken）
5. 更新统计

---

## 5. 数据库设计（热更新 + 强筛选 + 随机性能的根基）

### 5.1 为什么必须 DB 化（而不是文本列表）

你要实现：标签/作者/R18/尺寸筛选、失败重试、成功率统计、热更新管理后台、未来扩展（多来源、多策略）。这些都需要：

- 结构化存储（字段、索引）
- 状态机（active/disabled/broken）
- 统计与审计
- 并发安全写入与查询

### 5.2 建议主模型：以“单张图片资源(illustId + page)”为粒度

原因：多页作品（manga）本质上是多张图片，随机 API 也应该以单张为单位随机挑选。

#### 表结构（PostgreSQL 建议版）

```sql
-- images：一条记录代表一张图片（illustId + page_index）
CREATE TABLE images (
  id               BIGSERIAL PRIMARY KEY,

  illust_id        BIGINT NOT NULL,
  page_index       INT NOT NULL,              -- 0-based 对应 _p0/_p1...
  ext              TEXT NOT NULL,             -- jpg/png/gif/webp（按策略）

  original_url     TEXT NOT NULL,             -- i.pximg.net 原图 URL（热路径直接用）
  proxy_path       TEXT NOT NULL,             -- 对外稳定 URL（可保持现有风格或新增 /i/:id）

  width            INT,
  height           INT,
  aspect_ratio     REAL,
  orientation      SMALLINT,                  -- 1 portrait / 2 landscape / 3 square / 0 any

  x_restrict       SMALLINT,                  -- 0/1/2...（R18/R18G 等）
  ai_type          SMALLINT,                  -- 可选：AI 标记（如你要“排除AI”）

  user_id          BIGINT,
  user_name        TEXT,
  title            TEXT,
  created_at_pixiv TIMESTAMP,

  status           SMALLINT NOT NULL DEFAULT 1, -- 1 active / 2 disabled / 3 broken
  fail_count       INT NOT NULL DEFAULT 0,
  last_fail_at     TIMESTAMP,
  last_ok_at       TIMESTAMP,
  last_error_code  TEXT,
  last_error_msg   TEXT,

  random_key       REAL NOT NULL,             -- 0..1，写入时生成；用于高性能随机

  added_at         TIMESTAMP NOT NULL DEFAULT now(),
  updated_at       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX images_uniq ON images(illust_id, page_index);
CREATE INDEX images_filter_idx
  ON images(status, x_restrict, orientation, width, height, random_key);

-- tags：规范化标签（便于索引与扩展多语言）
CREATE TABLE tags (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  translated_name TEXT
);

CREATE TABLE image_tags (
  image_id BIGINT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  tag_id   BIGINT NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
  PRIMARY KEY(image_id, tag_id)
);

CREATE INDEX image_tags_tag ON image_tags(tag_id, image_id);

-- imports：记录后台批量导入任务（便于追溯与审计）
CREATE TABLE imports (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMP NOT NULL DEFAULT now(),
  created_by TEXT,
  source TEXT,
  total INT NOT NULL,
  success INT NOT NULL,
  failed INT NOT NULL,
  detail JSONB
);
```

### 5.3 高性能随机算法（推荐：random_key + 两段查询）

> 目标：避免 `ORDER BY random()` 对全表随机排序。

思路：

1. 每条记录写入时生成 `random_key ∈ [0,1)`
2. 查询时生成 `r=random()`：
   - 先找 `random_key >= r` 的第一条
   - 若无结果，回环取 `random_key` 最小的第一条

伪 SQL：

```sql
-- 第一次：random_key >= r
SELECT *
FROM images
WHERE status = 1
  AND (:x_restrict_is_any OR x_restrict = :x_restrict)
  AND (:orientation_is_any OR orientation = :orientation)
  AND (:min_width  IS NULL OR width  >= :min_width)
  AND (:min_height IS NULL OR height >= :min_height)
  AND random_key >= :r
ORDER BY random_key
LIMIT 1;

-- 回环
SELECT *
FROM images
WHERE status = 1
  AND ...
ORDER BY random_key
LIMIT 1;
```

标签筛选加入后：

- 先通过 `image_tags` / `tags` 过滤得到候选集合（索引命中）
- 再在候选集合上套 random_key 策略

### 5.4 “失败图片冷却”机制（显著提高成功率）

为了避免某些 broken 图片被频繁抽到，建议引入：

- `last_fail_at`：最近失败时间
- `fail_count`：失败次数

并在随机挑选 SQL 中排除“刚失败过的记录”，例如：

- `WHERE last_fail_at IS NULL OR last_fail_at < now() - interval '10 minutes'`

这样能够显著提高用户请求的成功率与体验。

---

## 6. API 设计（对外随机图片 API：默认图片 / 可 JSON / 强过滤）

### 6.1 保留现有兼容路由（必须）

继续保留现有 pixivcat 风格路由：

- `GET /:illustId.:ext`
- `GET /:illustId-:pageNumber.:ext`

随机 API 应当在其基础上新增，并尽量复用现有代理逻辑与头部策略。

### 6.2 新增端点（推荐最小集合）

对外：

- `GET /random`
  - 默认：图片二进制（`Content-Type: image/*`）
  - `?format=json`：返回 JSON
  - `?redirect=1`：302 到稳定图片 URL（推荐生产高并发使用）
- `GET /images/:id`：返回单条记录 JSON（用于调试/后台）
- `GET /healthz`：健康检查
- `GET /metrics`：Prometheus 指标（可选但强烈建议）

后台：

- `GET /admin`：后台首页（统计概览）
- `GET /admin/images`：图片管理
- `POST /admin/images/import`：批量导入 URL（热更新）
- `POST /admin/images/:id/disable` / `enable` / `delete`：操作

### 6.3 查询参数（强筛选：对标 waifu.im 语义）

建议参数（MVP → 完整体可逐步实现）：

- 分级：
  - `r18=0|1|2|any`（0 全年龄，1 R18，2 R18G，any 不筛）
- 方向/尺寸：
  - `orientation=portrait|landscape|square|any`
  - `min_width=...`
  - `min_height=...`
  - `min_pixels=...`（= width*height）
- 标签：
  - `included_tags=tag1,tag2`（AND：必须同时包含）
  - `excluded_tags=tag3,tag4`
- 作者/作品：
  - `user_id=...`
  - `illust_id=...`
- 行为：
  - `format=image|json`（默认 image）
  - `redirect=0|1`（默认 0）
  - `attempts=3`（一次请求内部换图重试次数，建议 1..10）
  - `seed=...`（可选：用于复现随机，便于排障/缓存）

### 6.4 JSON 返回建议格式（图床风格）

```json
{
  "id": 12345,
  "illust_id": 987654321,
  "page_index": 0,
  "r18": false,
  "width": 2480,
  "height": 3508,
  "orientation": "portrait",
  "tags": ["tagA", "tagB"],
  "author": { "user_id": 112233, "name": "someone" },
  "urls": {
    "proxy": "https://your.domain/987654321-1.jpg",
    "origin": "https://i.pximg.net/img-original/img/....jpg"
  },
  "cache": { "max_age": 31536000 },
  "debug": { "picked_by": "random_key", "attempt": 1 }
}
```

---

## 7. 核心逻辑伪代码（稳健性：重试 + 换图 + 自愈 + 热更新）

### 7.1 Pixiv 原生 URL 解析（导入的基础）

大部分 Pixiv 原图 URL 含 `.../{illustId}_p{page}.{ext}`，可解析出 illustId/page/ext：

```pseudo
function parsePixivUrl(url):
  m = regexMatch(url, /(\d+)_p(\d+)(?:_[^.]*)?\.(jpg|jpeg|png|gif|webp)/i)
  if !m: return error("unsupported_url")
  return { illustId: int(m[1]), pageIndex: int(m[2]), ext: lower(m[3]) }
```

### 7.2 热更新导入（同步写 DB + 异步补全元信息）

```pseudo
POST /admin/images/import
  urls = parseTextareaOrUpload()
  for url in urls:
    parsed = parsePixivUrl(url)
    upsert images(illust_id, page_index) with {
      original_url: url,
      ext: parsed.ext,
      status: active,
      random_key: random()
    }
    enqueue job hydrate_metadata(illust_id)
```

元信息补全任务：

```pseudo
job hydrate_metadata(illust_id):
  detail = pixivApi.illustDetail(illust_id)   # 冷路径：需要 access token
  for each page:
    update images set width,height,x_restrict,user,tags,original_url=detail.original_url_of_page
  sync tags table + image_tags relation
```

### 7.3 随机挑图 + 代理（失败换图重试，避免用户直接见到错误）

```pseudo
GET /random?filters...
  attempts = clamp(query.attempts, 1..10) default 3

  for i in 1..attempts:
    record = db.pickRandom(filters)  # random_key/索引命中
    if !record: break

    if query.redirect == 1:
      metrics.success++
      return 302 to record.proxy_path

    result = proxyStream(record.original_url)
    if result.ok:
      metrics.success++
      return stream

    metrics.fail++
    db.markFail(record.id, result.error)
    if is404or403(result): maybe enqueue heal_url(record.illust_id)

  return friendlyFallback()
```

### 7.4 URL 自愈（让 broken 图有机会自动恢复）

```pseudo
job heal_url(illust_id):
  detail = pixivApi.illustDetail(illust_id)
  for each page:
    if db has image(illust_id,page):
      db.updateOriginalUrlIfChanged(...)
      db.setStatusActiveIfWasBroken(...)
```

---

## 8. 管理后台（不停机热更新 + 统计 + 可维护）

### 8.1 后台实现路线（建议先快后优）

路线 A（最快落地）：AdminJS

- 快速获得 CRUD、过滤、分页、编辑、删除
- 适合早期快速验证“热更新/管理/状态机/筛选字段”

路线 B（定制体验更强）：自研后台（SPA + REST）

- 更适合复杂导入（预览/校验/去重/任务进度）、统计图表、权限模型

### 8.2 后台功能清单（对齐你的需求）

图片库管理：

- 列表：总数、active/disabled/broken 数量
- 单条详情：原始 URL、代理 URL、标签、作者、尺寸、失败次数、最近失败原因
- 操作：启用/禁用/删除（建议软删或 status=disabled）

批量导入（热更新核心）：

- textarea 粘贴、文件上传（每行一个 URL）
- 去重策略：`(illust_id, page_index)` 唯一
- 导入后异步补全元信息（队列任务）

统计（最小可用 → 完整体）：

- 请求总数、成功率、失败率
- 延迟：P50/P90/P95
- broken 占比、近 24h top 错误原因
- 资源：CPU/内存（简版也可：仅展示 Node 进程内存）

安全：

- 后台必须鉴权（最低：`ADMIN_TOKEN`；更好：账号+session）
- 对公网 API 必须限流（IP/Key 维度）

---

## 9. 稳健性与性能（低配抗大流量的工程细节）

### 9.1 性能优先级（按收益排序）

1. **把 Pixiv API 从热路径移走**（这是能否“扛巨大请求量”的关键）
2. `/random` 走 **302 重定向**（图片带宽交给 CDN/缓存）
3. DB 随机挑图走索引（random_key 或 TABLESAMPLE 降级）
4. 代理请求使用 keep-alive、流式转发（现有实现方向正确）
5. 限流 + 熔断 + 退避重试（保护自己与上游）

### 9.2 分层重试策略（避免“无脑重试”）

- 网络/超时类：axios-retry（少量重试、指数退避）
- 业务类（图失效）：当次请求内部“换图重试”（attempts 次）
- 上游整体异常：熔断器 opossum（快速失败/降级，避免雪崩）

### 9.3 图片变换（若要做 w/h/crop）：必须签名

若引入 imgproxy：

- 只在 JSON 返回中给出签名后的 imgproxy URL
- 或后台生成变换 URL，前台不可自由组合参数

否则极易被 DoS（任意尺寸/任意格式请求）。

---

## 10. 迭代路线图（强烈建议分阶段，避免一次性大重构）

### 阶段 1：MVP（尽快可用）

- 上 DB（建议直接 PostgreSQL）
- 实现 `GET /random`（基础筛选：orientation + min_width/min_height + r18）
- 后台最小功能：导入 URL、删除/禁用、查看总数
- 稳健性：失败换图重试 + broken 标记 + 冷却时间

### 阶段 2：强筛选（Pixiv 元信息驱动）

- 入库/后台任务：拉取 Pixiv 元信息写入 DB（作者/标签/R18/宽高等）
- 支持 `included_tags/excluded_tags`、`user_id`
- JSON 返回结构标准化

### 阶段 3：工程化（高并发、可观测、可运维）

- `/metrics` + 仪表盘
- 熔断/重试体系化（opossum + p-retry + axios-retry）
- 随机算法优化与降级（random_key + TABLESAMPLE）
- 更完整的后台统计与审计日志

### 阶段 4（可选）：图床级能力

- 引入 imgproxy（签名 URL）
- CDN 策略完善（random no-store、图片长缓存）

---

## 11. 风险与合规（必须写清楚，避免项目“能跑但不可用”）

1) 版权与条款
- Pixiv 图片涉及作者版权与平台条款；你应确保对外提供服务的内容在授权/合法范围内。
- 必须提供后台“禁用/下架”机制，便于合规处理。

2) R18 内容
- 建议默认 `r18=0`（全年龄），并在后台清晰区分/统计 R18/R18G。

3) Token 安全
- refresh_token 属于敏感信息，必须仅服务端保存，并支持轮换。
- 建议：后台导入/日志中严禁输出完整 token。

---

## 12. 参考资料（本规划引用的关键学习来源）

随机图片 API（接口与筛选模型）：

- waifu.im Search API：`https://docs.waifu.im/reference/api-reference/search`
- waifu.im Tags：`https://docs.waifu.im/tags`

图片变换（签名 URL，防滥用）：

- imgproxy Signing URL：`https://docs.imgproxy.net/usage/signing_url`
- imgproxy configuration（key/salt）：`https://docs.imgproxy.net/3.25.x/configuration/options`

稳健性（重试/熔断/限流）：

- axios-retry：`https://github.com/softonic/axios-retry`
- p-retry：`https://github.com/sindresorhus/p-retry`
- opossum：`https://github.com/nodeshift/opossum`
- express-rate-limit：`https://github.com/express-rate-limit/express-rate-limit`

数据库随机优化（避免 ORDER BY random）：

- PostgreSQL `TABLESAMPLE`：`https://www.postgresql.org/docs/current/sql-select.html`
- TABLESAMPLE 实测文章：`https://www.redpill-linpro.com/techblog/2021/05/07/getting-random-rows-faster.html`

Pixiv token 获取（refresh token 常用指南）：

- ZipFile Pixiv OAuth Flow：`https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362`

---

## 13. 下一步需要你确认的关键决策（用于落地实施前锁定路线）

为了后续“真正开始改代码”时不走弯路，你需要先确认 3 个选择：

1) 数据库：PostgreSQL（推荐）还是先 SQLite 快速试跑？
2) 后台：先用 AdminJS 快速 CRUD，还是从第一天就自研后台页面？
3) 图片变换：是否需要（w/h/crop/format）？如果需要，是否接受引入 imgproxy 并强制签名？

只要你把这 3 个答案定下来，我就可以基于本规划输出“可执行的逐文件改动清单 + 模块划分 + 表迁移脚本 + 端点契约细化 + 任务队列设计”，再进入实际代码迭代阶段。

```

</details>

<details>
<summary>附录D：pixivcat-backend easy_proxies 对接文档（原文）</summary>

`md
# easy_proxies 对接与部署建议

本文说明如何让 pixivcat-backend 与 `easy_proxies` 对接，并给出推荐部署形态与安全建议。

## 1. easy_proxies 是什么（在本项目中的定位）
- easy_proxies 负责“代理节点池管理”：订阅/节点、探测、导出代理入口
- pixivcat-backend 负责“业务侧策略”：域名路由、token↔proxy 绑定、失败重试与切换、审计与指标

因此推荐将 easy_proxies 当作 **proxy provider**，由 pixivcat-backend 定期/手动从 easy_proxies 导入节点（`/api/export`）并落库。

## 2. 推荐模式：pool / multi-port / hybrid

easy_proxies 常见模式（命名以 easy_proxies 为准）：
- **pool**：所有节点共享同一监听端口（统一入口）
- **multi-port**：每个节点独立监听端口
- **hybrid**：既提供 pool 入口，也提供 multi-port 入口

对 pixivcat-backend 的推荐：
- 优先 **hybrid** 或 **multi-port**  
  原因：便于做更稳定的“节点级”健康与绑定（token↔proxy），减少 pool 模式下的“黑盒漂移”。

## 3. /api/export 导入协议（必须兼容）
pixivcat-backend 对接的最小契约：
- easy_proxies `GET /api/export` 返回 **纯文本**（`text/plain; charset=utf-8`），每行一个代理 URI，例如：
  - `http://1.2.3.4:12345`
  - `http://user:pass@1.2.3.4:12345`
- 在 hybrid 模式下，easy_proxies 会优先导出 multi-port（每节点独立端口）格式（更稳定）。

### 3.1 如果 easy_proxies 开启了密码：/api/auth
如果 easy_proxies 配置了管理密码，需要先登录：
```bash
curl -fsS -X POST http://<easy_proxies_host>:<port>/api/auth \\
  -H 'Content-Type: application/json' \\
  -d '{\"password\":\"<password>\"}'
```

响应 JSON 中会返回 `token`。之后调用受保护接口时：
```bash
curl -fsS http://<easy_proxies_host>:<port>/api/export \\
  -H 'Authorization: Bearer <token>'
```

> 说明：easy_proxies 同时会设置 `session_token` cookie；pixivcat-backend 对接时使用 Bearer token 更简单。

## 4. pixivcat-backend 侧配置建议
建议在后台（AdminJS）配置以下信息（DB 为运行时权威，env 仅做默认兜底）：
- `easy_proxies_base_url`：例如 `http://easy-proxies:9090`
- `easy_proxies_password`（可选）：用于自动调用 `/api/auth` 获取 token
- `easy_proxies_refresh_interval_seconds`（可选）：定时刷新代理列表的周期

导入方式建议：
- 管理端提供“一键导入/刷新”动作（手动触发）
- 可选：定时任务自动刷新（避免节点变更后长期不更新）

## 4.1 极简配置：一行 URI 直接导入（无需重启）

后台页面：`/admin/pages/easyProxiesImport`

支持直接粘贴单行/多行 URI：

```text
http://user:pass@host:port
socks5://host:port
http://user:pa@ss@host:port
```

要点：
- 密码中含 `@`：支持“最后一个 `@` 作为分隔”的写法，也支持 `%40` 编码。
- 批量导入：每行一个 URI，可混合 `http/https/socks4/socks5`。
- 保存后立即生效：导入动作会自动触发 runtime proxy cache 失效，不需要重启 backend。
- 冲突策略建议：`skip_non_source`（避免覆盖不属于当前来源的节点）。

### 4.1.1 推荐操作步骤（运营侧）
1. 打开 `Admin -> easy_proxies 导入`（`/admin/pages/easyProxiesImport`）。
2. 直接粘贴文本（单行或多行）。支持以下两种密码写法：
   - 原始 `@`：`http://user:pa@ss@host:port`
   - 百分号编码：`http://user:pa%40ss@host:port`
3. 选择冲突策略（推荐 `skip_non_source`），点击导入。
4. 查看结果摘要：`imported / invalid / conflicts`。
5. 若存在错误，直接根据行号修正后再次导入（无需重启服务）。

### 4.1.2 错误反馈示例（“说人话”）
- `line=7` + `Proxy URI must include scheme...`：该行缺少 `http://` / `socks5://` 前缀。
- `line=12` + `Invalid proxy port...`：端口非法（非数字或超出范围）。
- `line=21` + `IPv6 addresses must be wrapped in [ ]`：IPv6 未用方括号包裹。

证据截图：
- `docs/review/screenshots/2026-02-06_19-14-04/arux-0004-easy-import-summary.png`
- `docs/review/screenshots/2026-02-06_19-14-04/arux-0005-proxy-overview-unified.png`

## 5. Docker Compose 部署建议

### 5.1 建议 1：easy_proxies 外置（推荐）
优点：组件边界清晰，可独立升级/重启，不影响 pixivcat-backend。

- easy_proxies 单独一套 compose，暴露管理端口到 **内网**（不要直接公网暴露）
- pixivcat-backend 通过内网访问 `easy_proxies_base_url`

### 5.2 建议 2：与 pixivcat-backend 同 compose（可选）
适合一体化部署/小规模自用。

要点：
- easy_proxies 管理端口只暴露到内部网络
- 通过 compose network 互通：pixivcat-backend 配置 `easy_proxies_base_url=http://easy-proxies:9090`

## 6. 安全建议（强烈建议照做）
- **必须设置 easy_proxies 管理密码**（否则 `/api/auth` 会提示“无需密码”，等价于开放所有管理 API）
- easy_proxies 管理端口不要直接暴露公网；如必须暴露，至少加反代鉴权与 IP allowlist
- pixivcat-backend 管理后台同样建议启用 `ADMIN_IP_ALLOWLIST`、CSRF、审计
- 代理 URI 中的 `user:pass` 与 Pixiv `refresh_token` 都是高敏感信息：
  - 禁止明文日志与明文 API 返回
  - 后台展示必须脱敏
  - 建议落库加密（按本项目实现策略）

## 7. 可选增强：/api/nodes /api/debug 健康映射
easy_proxies 提供节点状态与探测信息接口（例如 `/api/nodes`、`/api/debug`）。
pixivcat-backend 可选择把这些信息映射成 ProxyEndpoint 的健康评分输入，以提升调度稳定性；
但核心转发与选择逻辑不应依赖这些接口的可用性（避免外部管理面抖动影响业务主链路）。

## 8. 常见排障

- 导入后看不到节点：
  - 检查 `easy_proxies_base_url` 是否可达
  - 检查 `source` 过滤与冲突策略是否把新节点跳过
  - 检查后台通知中的 `invalid/conflicts` 计数
- 提示认证失败：
  - 确认 easy_proxies 管理密码是否变更
  - 重新保存配置后再执行导入
- 导入成功但请求仍不走代理：
  - 检查全局代理开关（Dashboard “代理出站”）
  - 检查 fail-open/fail-closed 与域名路由配置

## 9. 回归验证清单（本轮）

```bash
# 重点单测（组件 bundle + URI 导入）
npx vitest run test/admin_components_bundle_route.test.ts test/proxyUriImporter.test.ts

# 全量回归（lint + 全量测试 + smoke）
npm run test:all

# Admin UI smoke（按需传入 token）
pwsh -NoProfile -File test/admin-ui-smoke.ps1 -BaseUrl http://127.0.0.1:3015 -AdminToken <ADMIN_TOKEN>
```

说明：
- 当 `AdminToken` 为空时，smoke 脚本会退化为“仅验证后台受保护”模式（返回 401/403/302/503 都视为受保护）。
- 若在受限环境无法启动 compose，可先执行 `docker compose -f docker-compose.yml config --services` 完成结构校验。
```

</details>

<details>
<summary>附录E：代理池支持调查文档（dynamic-proxy × pixiv-反代）</summary>

`md
# 代理池支持调查文档（dynamic-proxy × pixiv-反代）

> 调查日期：2026-02-04  
> 范围：`dynamic-proxy/`（Go）与 `pixiv-反代/pixivcat-backend/`（Node.js/TS）  
> 目标：不做开发实现，仅基于现有代码与文档，梳理两项目运行原理、用法、价值与可用性；评估能否结合；给出让 `pixiv-反代` 适配 `dynamic-proxy` 代理池以“隐藏真实 IP + 提升并发”的改造方向、风险与可行性建议。

---

## 0) 结论摘要（TL;DR）

1. **可以结合**：`dynamic-proxy` 本质是一个“本地/内网出站代理网关”，它把一批上游代理（目前实现上等价于 SOCKS5 `ip:port` 列表）做拉取、去重、测活，然后对外提供 **SOCKS5/HTTP** 两种代理服务并按 **round-robin** 轮换上游代理。`pixiv-反代` 只要把访问 Pixiv 的出站流量（Pixiv OAuth、Pixiv App API、pximg 图片源站）走这个网关，即可让 Pixiv 看到“代理 IP”而非服务器真实 IP。
2. **“高可用/高并发”取决于代理源质量**：公开代理（GitHub 列表类）普遍不稳定、速度慢、短寿命、易被 Pixiv/Cloudflare/CDN 封禁；`dynamic-proxy` 当前的测活目标是 `www.google.com:443`，**不保证对 Pixiv 可用**，在部分网络环境（尤其中国大陆）还可能因为访问不到 Google 而导致“零可用代理”。因此：能跑通 ≠ 能稳定扛并发。
3. **想同时获得“隐藏 IP + 较高并发 + 稳定”需要两端适配**：
   - `pixiv-反代` 侧：需要新增“出站代理”配置能力（最好可按域名路由）、明确 **失败策略**（失败时是否允许直连以避免服务不可用，但会泄露真实 IP）、并发/连接池策略、以及观测（成功率、延迟、代理错误分类）。
   - `dynamic-proxy` 侧：最好支持 **可配置测活目标（改为 Pixiv 目标）**、支持带认证的代理（付费代理常见 `user:pass@host:port`）、以及更精细的失败反馈（按代理地址熔断/降权、导出池大小/错误率指标）。

如果你的核心诉求是“尽量隐藏真实 IP”，那**必须选择 fail-closed（失败不直连）**，并配合网络层 egress 限制；否则在代理池不可用时会自动暴露真实 IP（哪怕只是少数请求）。

---

## 1) 项目 A：dynamic-proxy（运行原理 / 怎么用 / 有什么用 / 可用性）

### 1.1 项目定位与用途

`dynamic-proxy/` 是一个 Go 编写的“动态代理服务器”，它做的事情可以概括为：

- **输入**：多个 URL 提供的代理列表（行文本），代理以 `ip:port`（或带协议前缀的 `socks5://ip:port` 等）形式出现。
- **处理**：拉取 → 去重 → 并发测活 → 分池（严格/宽松）→ 定时刷新。
- **输出**：对外暴露 **4 个端口**：
  - SOCKS5 Strict / Relaxed
  - HTTP Strict / Relaxed

典型用途：

- 爬虫/抓取：把出站请求分散到多个代理 IP（降低单 IP 风险）。
- IP 隐匿：让目标站看到代理出口 IP。
- 作为“代理池网关”：上游代理变动频繁时，让下游应用只对接一个稳定入口（`127.0.0.1:17283/17285`）。

### 1.2 核心运行原理（基于代码）

关键代码在 `dynamic-proxy/main.go`。

#### 1) 配置加载

- 启动时读取 `dynamic-proxy/config.yaml`，解析字段：
  - `proxy_list_urls` / `special_proxy_list_urls`
  - `health_check_concurrency`
  - `update_interval_minutes`
  - `health_check.total_timeout_seconds`
  - `health_check.tls_handshake_threshold_seconds`
  - `ports.*`

#### 2) 拉取代理列表 + 去重

- `fetchProxyList()`：对每个 `proxy_list_urls` 发起 HTTP GET，逐行读取：
  - 去掉 `socks5://` / `socks4://` / `http://` / `https://` 前缀后，按字符串当作 `ip:port` 收集。
  - 通过 `proxySet` 去重。
- `special_proxy_list_urls` 使用一个简单正则 `([0-9.]+):([0-9]+)` 从“带描述文本”的复杂行里抽取 `ip:port`，同样去重。

注意：拉取代理列表时 HTTP 客户端设置了 `InsecureSkipVerify: true`，意味着它会忽略 HTTPS 证书校验（更“兼容”，但安全性更差）。

#### 3) 并发测活（健康检查）

- `healthCheckProxies(proxies)` 会为每个代理开 goroutine（并用 `semaphore` 控制并发数量 = `health_check_concurrency`）。
- `checkProxyHealth(proxyAddr, strictMode)` 的“测活逻辑”是：
  1. 把 `proxyAddr` 当作 **SOCKS5** 代理：`proxy.SOCKS5("tcp", proxyAddr, nil, proxy.Direct)`
  2. 通过该 SOCKS5 代理去连接 `www.google.com:443`
  3. 进行 TLS 握手：
     - Strict：`InsecureSkipVerify = false`（校验证书）
     - Relaxed：`InsecureSkipVerify = true`（不校验证书）
  4. 如果握手耗时超过阈值（`tls_handshake_threshold_seconds`），判定为“慢”，剔除。

输出是两个池：

- **Strict 池**：通过严格 TLS 校验且速度达标的代理。
- **Relaxed 池**：通过宽松握手且速度达标的代理；Strict 通过的代理会同时进入 Relaxed（Relaxed 是 Strict 的超集）。

#### 4) 代理池更新与轮换

- 维护两个 `ProxyPool`（Strict/Relaxed）：
  - `proxies []string`：当前可用代理列表
  - `index uint64`：round-robin 游标（原子递增）
  - `mu`：读写锁（更新与读取并发安全）
- `GetNext()`：`idx := atomic.AddUint64(&index, 1) % len(proxies)`，返回下一个代理。
- `updateProxyPool()`：
  - 拉取列表 + 测活
  - 如果新池非空则更新，否则保留旧池（避免更新后变成空池）
  - 以 `update_interval_minutes` 周期在后台刷新

#### 5) 对外提供 4 个代理服务端口

启动 `4` 个 server：

- SOCKS5 Strict / Relaxed：
  - 用 `github.com/armon/go-socks5` 起本地 SOCKS5 server。
  - 每个“拨号请求”时，动态从池里 `GetNext()` 选一个上游代理，再通过上游 SOCKS5 去连目标地址。
- HTTP Strict / Relaxed：
  - 自己实现了一个极简 HTTP forward proxy：
    - 普通 HTTP 请求：使用 `http.Transport{ Dial: dialer.Dial }` 通过上游 SOCKS5 拨号
    - HTTPS：支持 `CONNECT`，劫持连接后做双向 `io.Copy` 隧道
  - 每个 HTTP 请求会 `GetNext()` 选一个上游代理（即“按请求轮换”）

### 1.3 怎么用（本仓库现状）

`dynamic-proxy/README.md` 已提供运行方式（编译/二进制/Docker）。结合实际代码与配置，建议操作路径：

1. 编辑 `dynamic-proxy/config.yaml`
   - 更换/追加代理源 URL（最好使用你可控或质量更高的源）
   - 根据目标环境调整端口、测活并发、刷新间隔
2. 启动：
   - 直接运行：`go build` 后执行二进制，或 `go run main.go`（需 Go 环境）
   - Docker：`docker compose up -d`（见 `dynamic-proxy/docker-compose.yml`）
3. 测试：
   - SOCKS5：`curl --socks5 127.0.0.1:17283 https://api.ipify.org`
   - HTTP：`curl -x http://127.0.0.1:17285 https://api.ipify.org`

### 1.4 “有什么用”——对 Pixiv 场景的直接价值

对于 `pixiv-反代` 而言，`dynamic-proxy` 可以充当：

- **出站代理网关**：后端只需要配置一个本地代理地址（如 `http://dynamic-proxy:17285` 或 `socks5://dynamic-proxy:17283`），无需自己维护代理池。
- **轮换出口 IP**：把对 Pixiv 的访问分散到不同出口，降低“单 IP 高频”触发限流/封禁的概率（不保证）。
- **并发承载辅助**：当代理池足够大且稳定时，可支撑更多并发的图片拉取（理论上）。

### 1.5 可用性评估（优点 / 缺点 / 隐患）

**优点**

- 代码结构直观，配置简单，上手快。
- 拉取/测活并发可调，默认 200 并发测活对“列表很大”的情况比较友好。
- 对下游提供 SOCKS5 与 HTTP 两种入口，适配范围更广。
- 轮换逻辑简单（round-robin），可预测、易排查。

**关键缺点 / 限制（很重要）**

1. **上游代理“实现上等价于 SOCKS5”**  
   配置注释写了支持 `http/https/socks4/socks5`，但健康检查与拨号全部使用 `proxy.SOCKS5(...)`。也就是说：如果你的代理源里混入 HTTP 代理或 SOCKS4 代理，它们大概率会被判定为不可用。  
   结论：当前实现更像“SOCKS5 代理池网关”。
2. **测活目标固定为 `www.google.com:443`**  
   - 不同地区网络可能访问不到 Google → 导致全部代理被判死。
   - 即便对 Google 可用，也不代表对 Pixiv 可用（Pixiv/pximg 可能单独封禁某些代理 IP）。
3. **不支持上游代理认证**  
   付费代理/高质量代理常见格式 `user:pass@host:port`，当前配置与拨号均未支持用户名密码。
4. **HTTP 代理实现偏“最小可用”**  
   每个请求都会新建 `http.Transport`，没有明显复用；对大量并发请求时的效率、资源占用与边界行为（例如部分客户端发送相对路径而非绝对 URL）需要谨慎评估。

**安全性隐患**

- 若把端口暴露到公网（`docker-compose.yml` 默认 `ports` 直出），这将成为一个“开放代理”入口，风险极高（滥用、带宽跑满、法律风险）。
- Relaxed 模式允许“不校验证书”的代理通过测活；若下游客户端也关闭 TLS 校验，会有令牌泄露/中间人风险。即使下游严格校验 TLS，Relaxed 池里也更容易混入“不稳定/劣质代理”，导致失败率显著上升。

**总体评价**

- 作为“工具型网关”可用性不错：适合本地实验、临时爬虫、对稳定性要求不极端的场景。
- 作为“生产级高并发基础设施”可用性偏弱：缺少可观测性、缺少按目标站点的测活、缺少上游认证与精细化的失败处理。

---

## 2) 项目 B：pixiv-反代（pixivcat-backend）调查

> 这里的“pixiv-反代”指 `pixiv-反代/pixivcat-backend/`。它看起来是一个以 Pixivcat 兼容路由为基础、逐步扩展为“随机二次元图片 API + 管理后台 + 可观测”的后端项目。

### 2.1 项目定位与对外能力

根据 `pixiv-反代/pixivcat-backend/README.md`：

- **Pixivcat 兼容（legacy）**：必须保持可用的流式图片代理
  - 单图：`GET /:illustId.:ext`
  - 多图：`GET /:illustId-:pageNumber.:ext`（pageNumber 从 1 开始）
- **随机图片 API（演进中）**：`GET /random`（image/json/redirect 模式、强筛选、seed、attempts 等）
- **稳定图片 URL（演进中/已部分实现）**：
  - `GET /i/:id.:ext`：通过 DB 记录的 `originalUrl` 流式代理回源图片，并带长缓存
  - `GET /images/:id`：返回图片元数据 JSON
- **后台与观测**：`/admin`、`/metrics`、结构化日志、`/healthz`

### 2.2 运行原理（按请求链路拆解）

#### A) legacy 兼容路由（你现在最像“反代”的部分）

相关路由与控制器：

- 路由：`pixiv-反代/pixivcat-backend/src/routes/pixivRoutes.ts`
  - `/:illustId.:fileExtension` → `imageProxyController.getIllustSingle`
  - `/:illustId-:pageNumber.:fileExtension` → `imageProxyController.getIllustMulti`
- 控制器：`pixiv-反代/pixivcat-backend/src/controllers/imageProxyController.ts`

请求流程（单图为例）：

1. **（可选）DB 命中**：若设置了 `DATABASE_URL`，会优先查表 `images` 获取 `original_url`  
   - 命中且发现该作品是多图，会 301 跳转到 `/:illustId-1.:ext`
2. **Pixiv API 获取元信息**：否则调用 `pixivService.getPixivIllustIdData(illustId)`  
   - 该调用会走 access token（由 refresh token 刷新得到）
   - 可使用 Memcached 缓存（默认开启）
3. **从 API 响应抽取原图 URL**：
   - 单图：`meta_single_page.original_image_url`
   - 多图：`meta_pages[page-1].image_urls.original`
4. **回源拉取图片并“流式转发”**：
   - `streamImageByUrl(imageURL, res)` 直接用 `axios.get(..., responseType: 'stream')` 拉取 pximg 原图并 pipe 到响应
   - 设置响应头 `Cache-Control: max-age=31536000, public`（利于 CDN 长缓存）

关键点：legacy 路由是 **流式**，不会把整张图读入内存；这对并发下载很友好（主要瓶颈变成网络与文件描述符）。

#### B) Pixiv API / OAuth access token 机制（决定你能否“高并发稳定取元信息”）

相关代码：

- Token 刷新与轮换：`pixiv-反代/pixivcat-backend/src/services/pixivAuthService.ts`
  - `REFRESH_TOKENS`（必填）：支持 JSON 数组字符串或逗号分隔
  - 轮换策略：`PIXIV_TOKEN_STRATEGY=round_robin|random`（默认 round_robin）
  - 刷新端点：`https://oauth.secure.pixiv.net/auth/token`
- Pixiv API 调用：`pixiv-反代/pixivcat-backend/src/services/pixivService.ts`
  - `PIXIV_BASE_URL = https://app-api.pixiv.net/v1`
  - `GET /illust/detail?illust_id=...`
  - Memcached 缓存：`PIXIV_DETAIL_CACHE_ENABLED` / `PIXIV_DETAIL_CACHE_TTL_SECONDS`
  - 熔断器（opossum）：`pixiv-反代/pixivcat-backend/src/resilience/circuit.cjs`
  -（可选）hydrate 任务限速：`HYDRATE_MAX_IN_FLIGHT*` / `HYDRATE_RATE_LIMIT_*`

这套机制的现实含义：

- **并发上限往往被 Pixiv API 限制而不是你服务器**。增加代理 IP 并不能直接增加“每个 refresh token 的可用请求额度”。你真正能控制的是：
  - refresh token 数量（账号/令牌池）
  - 缓存命中率（减少 API 调用）
  - hydrate 等后台任务节奏（避免和在线请求抢额度）

#### C) `/i/:id.:ext` 与 `/random`（更偏“图库 API”的部分）

这些功能更多依赖 DB 中维护的 `images` 记录：

- `/i/:id.:ext`：`pixiv-反代/pixivcat-backend/src/controllers/imageByIdController.ts`
  - 通过 DB 查到 `originalUrl`，然后调用 `fetchPixivImageStream()` 回源拉取并流式返回
  - 失败时可触发 `heal_url` 任务（重新 hydrate 修复 URL）
- `/random`：`pixiv-反代/pixivcat-backend/src/routes/random.ts` + `src/services/randomService.ts`
  - 从 DB 随机选图，再 `fetchPixivImageStream()` 拉取图片流

这里的图片回源走的是统一封装：

- `pixiv-反代/pixivcat-backend/src/http/pixivImageHttp.ts`
- 其内部调用 `pixivImageGet()`（`src/http/axiosClient.ts`），该 axios 客户端默认启用了 **keepAlive** Agent。

### 2.3 当前项目与“代理池/隐藏 IP”相关的现状

**项目已有的代理相关设置**主要是“入站反代”层面：

- `TRUST_PROXY`：信任 `X-Forwarded-*`（用于部署在 Cloudflare/Nginx/1Panel 等反代后面时正确获取客户端 IP、做 allowlist/限流等）

**项目缺失的关键能力**（与本次需求强相关）：

- **没有出站代理配置**：对 Pixiv 的所有访问（OAuth、App API、pximg 图片源站）默认都是服务器直连，因此 Pixiv 能看到服务器真实 IP。
- legacy 图片回源路径目前存在两套实现：
  - legacy：`imageProxyController.ts` 里直接 `axios.get(stream)`（未统一走 `axiosClient`）
  - 新路由：`pixivImageHttp.ts` 走 `axiosClient`（更好扩展）

### 2.4 并发与稳定性的现有基础（哪些地方已经做对了）

从代码与 `docker-compose.yml` 看，这个后端已经考虑了不少“可生产运行”的要素：

- 图片流式代理：降低内存压力。
- Memcached 缓存 Pixiv detail：减少 API 压力与 token 消耗。
- Pixiv API 熔断器：上游大面积失败时快速失败，保护自身。
- 可选限流中间件：`RATE_LIMIT_*`（默认关闭，但 `.env.example` 推荐开启）。
- Docker 运行时：
  - `ulimits.nofile` 提升到 65535（高并发流式连接很关键）
  - 可选只读文件系统、资源限制、日志轮转等（见 `docs/deployment/security-checklist.md`）

这意味着：**你要的“高并发”并不是从 0 开始**；真正的瓶颈更可能在“上游 Pixiv/代理池质量”与“出站连接策略”上。

---

## 3) 两项目是否可结合？如何结合？

### 3.1 结合的本质：让 Pixiv 相关出站流量“走代理网关”

要达到“隐藏真实 IP”，`pixiv-反代` 需要把以下出站流量通过代理：

1. OAuth 刷新 token：`oauth.secure.pixiv.net`
2. Pixiv App API：`app-api.pixiv.net`
3. 原图源站：通常是 `i.pximg.net`（以及可能的 `i-cf.pximg.net` 等）

而 `dynamic-proxy` 能提供两类入口：

- **SOCKS5**：`17283/17284`
- **HTTP forward proxy**：`17285/17286`（带 CONNECT）

因此从架构上 **完全可以结合**：把 `pixiv-反代` 的 HTTP 客户端（axios）改为“通过 `dynamic-proxy` 代理访问上述域名”。

### 3.2 结合方式（按改造侵入性排序）

> 这里是“建议方案”。由于你要求不实现，这里只描述怎么做与注意点，不提交代码改动。

#### 方案 1：应用层显式接入（推荐，最可控）

在 `pixiv-反代` 内为 axios 增加“代理 Agent”，并且只对 Pixiv 域名启用：

- 对 `pixivApiRequest/pixivApiGet/pixivImageGet`：在 `src/http/axiosClient.ts` 统一注入代理配置（最干净）
- 对 legacy 的 `imageProxyController.ts`：也改为走同一套 http client（避免漏网直连）

优点：

- 你能精确控制哪些域名走代理、哪些不走（DB/Memcached/Prometheus 不受影响）。
- 你能定义 fail-closed（代理失败就返回错误，保证不泄露真实 IP）。
- 便于做指标统计（代理错误 vs Pixiv 403/429 等）。

缺点：

- 需要改一点代码（你本轮不做实现，但这是最现实的落地方向）。

#### 方案 2：系统/容器层“全局代理”（改动少但不稳定）

典型做法是设置环境变量：

- `HTTP_PROXY=http://dynamic-proxy:17285`
- `HTTPS_PROXY=http://dynamic-proxy:17285`
- 或 `ALL_PROXY=socks5://dynamic-proxy:17283`

但现实问题是：**并非所有 Node.js HTTP 客户端都会自动遵循这些 env**。axios 在不同版本/配置下行为也不完全一致；即便能工作，也难以做“只代理 Pixiv 域名”的精细路由，且更难保证 fail-closed（可能出现部分路径仍直连）。

结论：可以做 PoC 验证，但不建议作为长期方案。

#### 方案 3：只把“图片回源”走代理，Pixiv API 直连（折中）

理由：

- Pixiv API 有 token 限制与账号风险，走不稳定代理会让熔断器频繁打开，影响整体服务。
- 图片回源流量占比通常更大，且只需要 Referer/UA，走代理更有“隐匿 IP/分摊带宽”的意义。

缺点：

- 你的真实 IP 仍会暴露给 Pixiv OAuth / App API（严格意义上“隐藏 IP”不成立）。
- 如果 Pixiv 针对账号风控也看 IP，那仍有价值（但不确定）。

---

## 4) 用 dynamic-proxy 达到“隐藏 IP + 较高并发”的关键问题

### 4.1 “隐藏真实 IP”的最容易踩坑点：失败时直连（IP 泄露）

当代理池不可用/很小/大量失败时，你会面临选择：

- **fail-open**：代理失败就改为直连（服务可用性更高，但会泄露真实 IP）
- **fail-closed**：代理失败就返回 502/503（保证不泄露，但可用性下降）

如果你的首要目标是隐藏 IP，必须：

1. 代码层面明确 fail-closed；
2. **网络层面加一层兜底**：例如在容器/主机上限制 egress，使得后端进程除了 `dynamic-proxy` 之外无法直接访问外网（这样即使代码写错也不会直连出网）。

### 4.2 “较高并发”的核心不是你后端，而是代理池与上游限制

你需要把并发问题拆成 3 类瓶颈：

1. **Pixiv API 限制（token/账号）**  
   - 代理 IP 不会“凭空增加 token 配额”。  
   - 真正有效的是：更多 refresh token + 更高缓存命中 + 更合理的后台 hydrate 节奏。
2. **pximg 图片源站的限制（更多和 IP/速率相关）**  
   - 代理池可能有效分摊；但公开代理带宽小、稳定差，未必比直连快。
3. **你自己的后端与网络资源**  
   - 你已经采用流式，且 Docker 配置了高 `nofile`，这是正确方向。
   - 真正可能需要调的是：Node 的 Agent `maxSockets`、超时、反压（避免把请求无限堆积导致雪崩）。

### 4.3 dynamic-proxy 当前实现对 Pixiv 场景的“天然不匹配点”

1. **测活目标是 Google，不是 Pixiv**  
   - 代理对 Google 可用 ≠ 对 Pixiv 可用（Pixiv 可能封禁该代理 IP，或 pximg 走不同线路）。
   - 在无法访问 Google 的网络环境会直接“全军覆没”。
2. **只会 SOCKS5**（就当前代码而言）
   - 如果你有 HTTP/HTTPS 代理池，当前实现用不上。
3. **缺少按代理粒度的失败反馈与熔断**  
   - 代理测活每 5 分钟一次，但运行中随时会坏。
   - 下游请求失败时，dynamic-proxy 不会把该代理即时踢出/降权（只会在下一轮刷新可能被淘汰）。

### 4.4 strict / relaxed 模式怎么选？

结论：**优先 strict**。

- strict 池至少保证代理能对 `www.google.com` 做“可校验的 TLS 握手且不太慢”，更像“干净代理”。
- relaxed 池可能混入：
  - 不支持证书校验的中间人代理
  - 慢代理
  - 网络质量更差的代理

即使你在 `pixiv-反代` 侧始终启用 TLS 校验，relaxed 池也更可能导致失败率/延迟不可控，从而触发 `pixiv-反代` 现有的熔断器与错误统计，让整体体验变差。

---

## 5) 改造方向（不实现，仅给建议）

### 5.1 pixiv-反代（pixivcat-backend）侧建议

目标：把“出站代理”做成一等公民能力，且可控、可观测、可回滚。

建议改造点：

1. **统一所有 Pixiv 出站请求的 HTTP Client**  
   - 把 legacy 的 `imageProxyController.ts` 也改为走 `src/http/axiosClient.ts`（或至少走同一层封装），避免“有的走代理、有的直连”的漏点。
2. **新增出站代理配置（按域名路由）**  
   - 例如引入配置项（示例命名）：
     - `UPSTREAM_PROXY_ENABLED=1`
     - `UPSTREAM_PROXY_URL=http://dynamic-proxy:17285` 或 `socks5://dynamic-proxy:17283`
     - `UPSTREAM_PROXY_MODE=http|socks5`
     - `UPSTREAM_PROXY_TARGETS=oauth.secure.pixiv.net,app-api.pixiv.net,i.pximg.net`
     - `UPSTREAM_PROXY_FAIL_CLOSED=1`（关键）
3. **出站并发与连接策略可配置**  
   - keepAlive 与否决定“是否更频繁轮换代理”。如果你的诉求是“分摊到更多代理”，keepAlive 可能需要更激进地限制（例如更小的 free socket 池）。
   - 为 Pixiv API 与 pximg 图片使用不同的 timeout / maxSockets（图片更大，超时要更宽松）。
4. **代理错误分类与观测**  
   - 在现有 `upstream_errors_total` 基础上扩展维度（至少区分：proxy_connect_error、proxy_tunnel_error、pixiv_403、pixiv_429、pixiv_5xx）。
   - 记录每次请求是否走代理（以及走的代理入口模式：SOCKS/HTTP，strict/relaxed）。
5. **熔断策略分层**  
   - 现有熔断器是“Pixiv API 熔断”。接入不稳定代理后，你可能需要：
     - “代理层熔断”（代理入口不可用就快速失败/切换）
     - “Pixiv 层熔断”（上游返回 403/429/5xx 触发）
   - 否则代理抖动会让 Pixiv 熔断器误判为 Pixiv 故障。

### 5.2 dynamic-proxy 侧建议（更贴近“代理池产品化”）

如果你希望 dynamic-proxy 真正成为 Pixiv 业务的“稳定代理池”，建议的改造方向：

1. **测活目标可配置，最好支持 HTTP 探测**  
   - 把 `www.google.com:443` 改为可配置（例如 `health_check.target_host` / `target_sni`），至少允许改为 `app-api.pixiv.net:443` 与 `i.pximg.net:443`。
   - 仅做 TLS 握手不够：最好能做一次最小 HTTP 请求（例如 GET 一个小资源或 HEAD），以验证代理“对 Pixiv 真的可用”。
2. **支持上游代理认证与更多协议**  
   - 认证：`user:pass@host:port`
   - 协议：HTTP/HTTPS proxy、SOCKS4/5
3. **按代理粒度的实时失败反馈**  
   - 运行时对失败代理做临时熔断/降权（避免 5 分钟窗口内持续用坏代理）。
4. **可观测性**  
   - 暴露 `/metrics` 或简单 `/status`（池大小、最近刷新时间、失败率、延迟分布）
   - 否则你只能靠日志猜“现在池里还有多少可用代理”
5. **安全默认值**  
   - 默认仅监听 `127.0.0.1` 或支持配置 bind 地址
   - 提供最简单的访问控制（白名单/密码）防止开放代理

---

## 6) 可行性与建议落地路径（里程碑）

### 阶段 0：明确目标与策略

- 你优先级是：
  - A) 绝不泄露真实 IP（fail-closed）  
  - B) 服务尽量不断（fail-open）  
  - C) 两者折中（分路径：图片 fail-closed，API fail-open 等）
- 这会直接决定改造细节与运维策略。

### 阶段 1：PoC（验证“能不能通”）

1. 单独跑 `dynamic-proxy`，确保 strict 池有一定数量可用代理。
2. 让 `pixiv-反代` 的某一条出站链路走代理（建议先从 **图片回源** 开始，因为它更直观：看出口 IP 是否变化、成功率如何）。
3. 观测：
   - 成功率（200/404/403/429/5xx）
   - 平均延迟与 P95
   - dynamic-proxy 池大小变化

### 阶段 2：稳定性强化（从“能跑”到“可用”）

- 解决 dynamic-proxy 测活目标问题（至少改成可配置，否则在不同网络环境很脆弱）。
- 在 `pixiv-反代` 增加出站代理配置与 fail-closed/fail-open 开关，并做指标。
- 为后台任务（hydrate/heal）设置更保守的速率限制，避免把代理池打穿。

### 阶段 3：并发提升（从“可用”到“高并发”）

并发提升的更优路径通常不是“无限堆代理”，而是组合拳：

- CDN 缓存（你已经有长缓存响应头）：让大量重复访问直接命中 CDN。
- DB 预热/导入：减少在线请求对 Pixiv API 的依赖。
- 代理池质量升级：用付费/自建代理（dynamic-proxy 需支持认证）。
- 横向扩展 `pixiv-反代`：多实例 + 共享数据库/缓存；dynamic-proxy 可作为共享网关或每实例一份。

---

## 7) 风险与合规提醒（务必阅读）

1. **公开代理极不可信**：可能记录你的访问、注入内容、限制带宽、随时下线；对 OAuth/token 这类敏感流量尤其危险。
2. **账号/令牌风险**：Pixiv 的风控不透明，高频 API 调用或来自“脏代理 IP 段”的访问可能触发更严格的限制甚至封禁。
3. **法律与服务条款**：大规模抓取与绕过限制可能违反 Pixiv 服务条款；使用开放代理也可能带来法律风险。建议在可控范围内使用，并优先考虑合法合规的代理来源与缓存策略。

---

## 8) 关键文件索引（便于你二次核对）

### dynamic-proxy

- 配置：`dynamic-proxy/config.yaml`
- 入口与核心逻辑：`dynamic-proxy/main.go`
- Docker：`dynamic-proxy/Dockerfile`、`dynamic-proxy/docker-compose.yml`
- 说明：`dynamic-proxy/README.md`

### pixiv-反代（pixivcat-backend）

- 入口：`pixiv-反代/pixivcat-backend/app.ts`、`pixiv-反代/pixivcat-backend/app.js`
- legacy 路由：`pixiv-反代/pixivcat-backend/src/routes/pixivRoutes.ts`
- legacy 图片代理控制器：`pixiv-反代/pixivcat-backend/src/controllers/imageProxyController.ts`
- 稳定图片路由：`pixiv-反代/pixivcat-backend/src/controllers/imageByIdController.ts`
- Pixiv 图片回源封装：`pixiv-反代/pixivcat-backend/src/http/pixivImageHttp.ts`
- axios client：`pixiv-反代/pixivcat-backend/src/http/axiosClient.ts`
- Pixiv API 服务：`pixiv-反代/pixivcat-backend/src/services/pixivService.ts`
- Token 刷新/轮换：`pixiv-反代/pixivcat-backend/src/services/pixivAuthService.ts`
- 部署安全清单：`pixiv-反代/pixivcat-backend/docs/deployment/security-checklist.md`

```

</details>

<details>
<summary>附录F：代理池支持调查文档（二号）（dynamic-proxy/easy_proxies/pixiv-反代）</summary>

`md
# 代理池支持调查文档（二号）

> 调查日期：2026-02-04  \
> 范围：`dynamic-proxy/`、`easy_proxies/`、`pixiv-反代/pixivcat-backend/`  \
> 目标：基于现有代码与配置，全面梳理三方项目运行原理与能力边界；评估“代理池 + 多 token + 多 IP”方案的可行性；说明与当前导入/分类体系的关系；输出清晰的对接建议与风险点（不做实现）。

---

## 0) 结论摘要（TL;DR）

1. **当前项目已经具备“导入 URL → 拉取 Pixiv 元数据 → 写入 tags/author → 按标签/作者过滤”的完整基础链路**：
   - 后台导入 `pximg` 原图 URL 后，会将 `illust_id + page_index` 写入 `images` 表，并可批量 **enqueue** `hydrate_metadata` 任务；
   - `hydrate_metadata` 通过 Pixiv App API 拉取作品详情，写入 `user_id / user_name / title / tags / x_restrict / ai_type / width / height` 等字段，并同步到 `tags` 与 `image_tags`；
   - `/random` 已支持 `included_tags`、`excluded_tags`、`user_id` 等过滤，`/images/:id` 可读取单图 tags。  
   也就是说：**“导入后自动分类”在代码层面已基本就绪，主要是运维与配置层面的使用问题**。
2. **在“代理池 + 多 token + 多 IP”需求上，`easy_proxies` 比 `dynamic-proxy` 更适配**：
   - `easy_proxies` 能消费订阅节点（机场）并形成稳定的 HTTP 代理池，提供健康检查、失败拉黑、管理面板与节点导出；
   - `dynamic-proxy` 更像“公开 SOCKS5 代理列表网关”，不支持认证、健康检查目标固定、只按 SOCKS5 拨号。对“机场订阅节点”并不友好。
3. **真正的风控压力不只来自 IP，还来自 token 限额与 Pixiv API 速率**：
   - 代理池只能缓解“pximg 图片回源”与“单 IP 过频”的风险；
   - Pixiv API 额度更依赖 `refresh_token` 数量与现有的缓存/速率限制策略。多 IP 不会直接增加 token 配额。
4. **对接的核心不是“把请求改走代理”这么简单，而是“代理选择策略 + token 绑定 + 失败策略”**：
   - 如果目标是“绝不泄露真实 IP”，必须 **fail-closed**；
   - 若追求可用性，可对不同链路分策略（例如：图片可 fail-open，API fail-closed）。

---

## 1) 需求目标复盘

你希望实现：

- **导入 image URL 后立即拉取该作品元信息（tags/author 等），并利用现有分类系统进行存储与过滤**；
- **支持多种请求维度**（例如按标签、按作者），为后续 API 设计打好基础；
- **引入“代理池 + 多 token + 多 IP”**，避免单 IP 高频访问触发 Pixiv 风控；
- **在动态代理项目之间选择更合适的对接方案**：
  - `dynamic-proxy`
  - `easy_proxies`（更偏机场订阅节点，稳定性更高）

---

## 2) 当前项目（pixiv-反代）现状调查

### 2.1 数据模型：已经具备完整“分类”字段

`prisma/schema.prisma` 定义了如下结构：

- `images`：
  - 基础：`illust_id / page_index / ext / original_url / proxy_path`
  - 维度：`width / height / aspect_ratio / orientation`
  - 分类：`x_restrict / ai_type / user_id / user_name / title / created_at_pixiv`
  - 状态：`status / fail_count / last_fail_at / last_error_code`
- `tags` 与 `image_tags`：标准多对多结构（tag 名称 + 翻译名）

**结论**：数据库结构已支持“按标签/作者分类与过滤”。

### 2.2 导入 URL → 写库 → 触发 Hydrate 的完整链路

导入路径在 `src/routes/adminImport.ts`：

- 支持前端批量粘贴或上传文本文件；
- 解析 URL 只接受 **pximg 原图链接**，由 `parsePixivUrl` 解析 `illustId + pageIndex + ext`；
- 批量写入 `images` 表，必要时进入 bulk 模式；
- 根据 `ADMIN_IMPORT_MAX_HYDRATE_ILLUSTS` 等限制，选择是否 enqueue `hydrate_metadata` 任务；
- 导入记录落到 `imports` 表，便于追踪。

**关键限制**：

- `parsePixivUrl` 只识别 `*.pximg.net/<illustId>_p<page>.<ext>` 格式；
- Pixiv 页面 URL（如 `https://www.pixiv.net/artworks/...`）不会被接受；
- 大批量导入时可能不会触发 hydrate（受上限配置控制）。

### 2.3 HydrateMetadata：完成“获取 tags/author 并落库”

`src/jobs/hydrateMetadata.ts` 做了：

- 调用 Pixiv App API（`/v1/illust/detail`）获取作品详情
- 归一化：`width / height / orientation / x_restrict / ai_type / userId / userName / title / create_date / tags`
- 对每页图片生成 `HydrateMetadataPage`
- 写入 `images` 表对应记录
- 调用 `syncImageTags` 写入 `tags` 与 `image_tags`

**结论**：导入 → hydrate 已能补齐分类信息（tags/author 等），并进入现有过滤系统。

### 2.4 分类查询能力（已具备）

`src/routes/random.ts` 已支持：

- `included_tags` / `excluded_tags`（用 `|` 分隔）
- `user_id` / `illust_id`
- `r18` / `orientation` / `min_width` / `min_height` / `min_pixels`

`imagesRepo.pickRandom` 会在 SQL 层拼接 tag 过滤条件，并通过 `image_tags` 表做“包含/排除”筛选。

`src/routes/images.ts` 返回单图详情（包含 tags 与作者字段）。

**结论**：从“分类系统”角度来看，你的需求几乎已经落地，只需要确保导入后 hydrate 正常执行即可。

### 2.5 Token 池与限速机制（已存在）

- `pixivAuthService.ts`：
  - 支持 `REFRESH_TOKENS` 多 token
  - 轮换策略 `PIXIV_TOKEN_STRATEGY`（round_robin / random）
- `pixivService.ts`：
  - 通过 `pixivApiGet` 拉取数据
  - 具备熔断器 `pixivApiCircuitFire`
  - 具备 hydrate 专用速率限制（全局/每 token）
- `memcached` 缓存 Pixiv 详情降低 API 压力

**结论**：token 与速率限制方面已经较完善，代理池需要与这套策略配合而非替代。

### 2.6 出站请求链路（代理接入点）

Pixiv 相关流量分为三类：

1. OAuth 刷新 token：`oauth.secure.pixiv.net`
2. Pixiv App API：`app-api.pixiv.net`
3. 原图回源：`i.pximg.net`（或其他 pximg 域名）

当前问题：

- **全部是直连**，没有统一“出站代理”层
- `axiosClient.ts` 定义了 Pixiv API / Image 的统一 client，但 **legacy 路由** `imageProxyController.ts` 仍在直接使用 `axios.get`（旁路）

**结论**：若要“彻底隐藏真实 IP”，必须让上述 3 类流量统一走代理，并消除 legacy 直连路径。

---

## 3) 项目 A：dynamic-proxy（本地代理池网关）

### 3.1 定位

- 一个 Go 实现的“代理池网关”
- 从多个代理列表 URL 抓取 `ip:port`
- 进行测活、去重、轮换
- 对外输出 4 个入口：SOCKS5 strict / SOCKS5 relaxed / HTTP strict / HTTP relaxed

### 3.2 核心实现要点（基于代码）

- **代理来源**：
  - `proxy_list_urls`：纯文本代理列表，支持 `ip:port` 以及 `http/socks` 前缀
  - `special_proxy_list_urls`：通过正则从“带描述文字的行”提取 `ip:port`
- **健康检查**：
  - 所有代理都按 SOCKS5 使用
  - 通过 SOCKS5 连接 `www.google.com:443`
  - TLS 握手成功且耗时 < 阈值则通过
  - strict 模式校验证书，relaxed 不校验
- **代理池更新**：
  - 定期刷新，round-robin 轮换
  - 新池为空则保留旧池
- **HTTP 代理**：
  - 实际是用 SOCKS5 拨号后转发 HTTP/CONNECT
  - 每请求新建 `http.Transport`
  - TLS 验证在 HTTP 代理层被关闭（`InsecureSkipVerify`）

### 3.3 限制与风险

1. **上游必须是 SOCKS5**（代码里始终用 `proxy.SOCKS5`）
2. **不支持带认证的代理**（机场常见 `user:pass@host:port` 无法用）
3. **测活目标固定为 Google**，并非 Pixiv；在不可访问 Google 的网络环境会大量误杀
4. **HTTP 代理实现“最小可用”**，高并发下连接复用与性能不稳定
5. **安全风险**：如果对公网开放，等价于开放代理（高风险）

### 3.4 对 Pixiv 场景的价值

- 适合 **公开代理池 + 临时抓取**
- 不适合 **机场订阅节点 + 长期稳定**

**结论**：若你主力节点来自机场订阅，`dynamic-proxy` 不是最优选择。

---

## 4) 项目 B：easy_proxies（机场订阅友好的代理池）

### 4.1 定位

- 基于 `sing-box` 的代理池管理工具
- 通过订阅/节点文件导入多协议节点
- 对外暴露 HTTP 代理入口，支持健康检查、故障拉黑、监控 UI、节点导出

### 4.2 运行模式

- **pool**：单入口，所有节点共享
- **multi-port**：每节点独立端口（适合“token → 固定节点”映射）
- **hybrid**：同时提供 pool + multi-port，并共享节点状态

### 4.3 节点来源与订阅机制

- `nodes` / `nodes_file` / `subscriptions` 三种来源并可合并
- 订阅内容支持 base64 / Clash YAML / 纯文本
- 支持定时刷新订阅，刷新时会 reload `sing-box`（连接会中断）
- 会将订阅结果写入 `nodes.txt` 以便回溯

### 4.4 健康检查与黑名单机制

- 启动时对所有节点进行探测
- 默认每 5 分钟做一次周期探测
- 每节点有失败计数，达到阈值进入 blacklist（并在持续时间后释放）
- 监控面板可看到延迟、失败次数、黑名单状态

探测逻辑：

- 通过代理拨号到 `probe_target`（默认 `www.apple.com:80`）
- 发送 HTTP GET `/generate_204` 并测量 TTFB

### 4.5 管理面板与 API 能力（内置）

- Web UI：节点状态、延迟、活跃连接、探测/拉黑/释放等
- 管理 API：节点增删改、配置重载、订阅刷新、导出代理池

### 4.6 GeoIP 路由（可选）

- 根据节点 IP 归属，分区域路由
- 通过访问路径 `/jp` `/us` 等进入特定区域节点池

### 4.7 适配 Pixiv 的优势与限制

**优势**

- 与机场订阅天然兼容（VLESS/VMess/Trojan/SS/Hy2 等）
- HTTP 代理入口容易被 Node/axios 使用
- 节点状态可观测（更适合长期运行）

**限制**

- 订阅刷新会导致连接中断
- 健康检查目标不是 Pixiv，需要配置到更贴近的目标
- pool 模式下代理选择以“连接粒度”为主（而非请求粒度）

---

## 5) 结合可行性分析（dynamic-proxy vs easy_proxies）

| 维度 | dynamic-proxy | easy_proxies |
|------|---------------|--------------|
| 代理来源 | 公开代理列表 | 机场订阅 / 节点文件 / 配置 |
| 支持协议 | 仅 SOCKS5（实际） | 多协议（VLESS/VMess/SS/Trojan/Hy2） |
| 上游认证 | 不支持 | 支持（节点协议内） |
| 健康检查 | TLS 握手 / Google | HTTP 探测 / 可配置目标 |
| 对外入口 | SOCKS5 + HTTP | HTTP（sing-box HTTP mixed inbound） |
| 节点管理 | 无 UI / 无 API | WebUI + API |
| 适配 Pixiv | 需改动或绕路 | 直接可用 |
| 机场节点稳定性 | 差 | 好 |

**结论**：

- 如果你的核心代理来源是机场订阅节点，**优先选择 easy_proxies**。
- dynamic-proxy 更适合“公开代理列表”实验，不适合长期稳定反代。

---

## 6) 代理池接入 pixiv-反代 的建议架构

### 6.1 需要走代理的流量

建议至少覆盖：

- `oauth.secure.pixiv.net`（refresh token）
- `app-api.pixiv.net`（Pixiv API）
- `i.pximg.net`（图片源站）

否则会出现“部分请求仍暴露真实 IP”。

### 6.2 代理选择策略（关键）

**推荐：token → proxy 绑定**

- 使用 `easy_proxies` 的 **multi-port / hybrid**
- 每个 token 分配一个稳定的代理端口
- Pixiv API 访问与 token 绑定，避免同一 token 在多 IP 间频繁跳变

**备选：请求级轮询**

- 使用 pool 模式，随机/顺序轮换
- 简化部署，但 token/IP 映射不稳定

### 6.3 失败策略：fail-open vs fail-closed

| 策略 | 结果 | 适用场景 |
|------|------|----------|
| fail-open | 代理失败时直连 | 可用性优先，但会暴露真实 IP |
| fail-closed | 代理失败直接失败 | 安全优先，稳定性降低 |

如果你最担心风控：**必须 fail-closed**，并在网络层限制进程直连外网。

### 6.4 keep-alive 与 IP 轮换的权衡

- Node `http.Agent` keepAlive 会复用连接，**减少代理轮换频率**
- 若目标是频繁轮换 IP，可考虑降低 keepAlive 或按域名拆分连接池

### 6.5 观测与诊断建议

建议为“是否经代理 / 代理错误类型 / 上游响应码”单独打点：

- proxy_connect_error
- proxy_tunnel_error
- pixiv_403 / pixiv_429 / pixiv_5xx
- token_index / proxy_port 维度

否则很难判断是“代理质量问题”还是“Pixiv 风控问题”。

---

## 7) 与“导入 URL + 分类”需求的匹配情况

### 已具备

- **导入 pximg 原图 URL**（`adminImport.ts`）
- **解析 illustId/pageIndex**（`parsePixivUrl`）
- **写入 images 表并生成 proxyPath**
- **hydrate_metadata 拉取 Pixiv 详情**（tags/author 等）
- **随机接口支持标签/作者过滤**（`/random?included_tags=...&user_id=...`）

### 仍可增强的方向

1. **输入格式拓展**：支持 Pixiv 作品页 URL（目前仅支持 pximg）
2. **分类接口补充**：若需要“按标签/作者列表检索”而非随机，需要新增列表型 API
3. **导入后即时触发**：大批量导入时可能跳过 hydrate，可增加后台批处理或分批执行

---

## 8) 风险与注意事项

1. **机场节点并非为爬虫场景设计**：Pixiv 可能对数据中心段 IP 有额外限制
2. **代理池并不等于更高 API 配额**：token 额度仍是硬限制
3. **代理泄露风险**：若代理不可信，refresh token 可能被截取
4. **订阅刷新带来的连接中断**：需要在低峰时执行

---

## 9) 建议落地路径（不实现，只做步骤建议）

### 阶段 1：验证

- 部署 easy_proxies（pool 模式）
- 将 pximg 图片回源走代理
- 观察成功率、延迟、错误类型

### 阶段 2：token 与代理绑定

- 使用 multi-port / hybrid
- 为每个 token 映射固定代理端口
- 观测 token/IP 关联是否稳定

### 阶段 3：全面代理化

- OAuth / Pixiv API / pximg 统一走代理
- 设置 fail-closed（防止真实 IP 泄露）
- 增加指标与日志维度

---

## 10) 关键文件索引

### pixiv-反代（pixivcat-backend）

- 数据模型：`pixiv-反代/pixivcat-backend/prisma/schema.prisma`
- URL 导入：`pixiv-反代/pixivcat-backend/src/routes/adminImport.ts`
- URL 解析：`pixiv-反代/pixivcat-backend/src/utils/parsePixivUrl.impl.js`
- Hydrate 任务：`pixiv-反代/pixivcat-backend/src/jobs/hydrateMetadata.ts`
- tags 同步：`pixiv-反代/pixivcat-backend/src/repositories/tagsRepo.ts`
- 过滤逻辑：`pixiv-反代/pixivcat-backend/src/repositories/imagesRepo.ts`
- 随机接口：`pixiv-反代/pixivcat-backend/src/routes/random.ts`
- Pixiv API：`pixiv-反代/pixivcat-backend/src/services/pixivService.ts`
- Token 管理：`pixiv-反代/pixivcat-backend/src/services/pixivAuthService.ts`
- legacy 图片代理：`pixiv-反代/pixivcat-backend/src/controllers/imageProxyController.ts`

### dynamic-proxy

- 配置：`dynamic-proxy/config.yaml`
- 入口与核心逻辑：`dynamic-proxy/main.go`

### easy_proxies

- 配置：`easy_proxies/config.example.yaml`
- 入口构建：`easy_proxies/internal/builder/builder.go`
- 节点池调度：`easy_proxies/internal/outbound/pool/pool.go`
- 健康检查与监控：`easy_proxies/internal/monitor/manager.go`
- WebUI / API：`easy_proxies/internal/monitor/server.go`
- 订阅刷新：`easy_proxies/internal/subscription/manager.go`
- sing-box 生命周期：`easy_proxies/internal/boxmgr/manager.go`

---

## 11) 总结建议

- **首选 easy_proxies** 作为代理池底座（机场节点更稳定）；
- **pixiv-反代 需要补齐“出站代理层”** 并消除 legacy 直连；
- **token 与 proxy 的绑定策略** 是避免风控的关键；
- **导入 + hydrate + 分类** 已经基本具备，后续重点在“代理接入 + 稳定性策略”。

---
```

</details>

<details>
<summary>附录G：页面与功能实现问题（线上审计）</summary>

`md
# 页面和功能实现问题

> 审计对象：`https://i.mukyu.ru`（已部署站点）  
> 审计方式：Chrome DevTools MCP 真实交互 + 实网请求 + Network/Console + 代码定位  
> 审计时间：2026-02-07（北京时间）  
> 凭据处理：仅使用掩码，未在报告落盘明文密码/token/refresh_token。

关联证据：
- `pixiv-反代/pixivcat-backend/docs/review/2026-02-07_03-30-03-admin-deep-audit.md`
- `pixiv-反代/pixivcat-backend/docs/review/2026-02-07_03-30-03-api-contract-audit.md`
- `pixiv-反代/pixivcat-backend/docs/review/2026-02-07_03-30-03-api-test-results.json`
- `pixiv-反代/pixivcat-backend/docs/review/2026-02-07_03-30-03-admin-action-probe-compact.json`
- `pixiv-反代/pixivcat-backend/docs/review/2026-02-07_03-30-03-admin-rerun-network-evidence.json`
- `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/`

## 1. 风险总览

- **高风险（阻断级）**
  - TokenProxyBinding 资源 API 读路径持续 500（list/show/edit），后台“可写不可读”。
  - ProxyPoolOverview 页面 API pending/504，页面长期“刷新中…”，核心可观测能力失效。
  - ProxyEndpoint probe 外部依赖放大为 504，深层动作稳定性不足。
  - 大量 Admin action 深链展示“你必须为你的操作实现操作组件”，存在“按钮可用但深链不可用”的假可用。
- **中风险（功能/契约偏差）**
  - 资源 new/edit 路由风格不统一（`/new`、`/actions/new`、禁用动作混杂 404/未授权）。
  - HydrationRun 空态下 pause/resume/cancel 仅给 not found，无可恢复路径。
  - legacy `page=0` 返回 HTML 400，错误包与 JSON API 契约不一致。
- **低风险（体验/可维护性）**
  - `/favicon.ico` 全站 400 噪声，污染 console/network 观测。
  - HydrationOps 存在表单可访问性 issue（label/name/id 不完整）。

## 2. “应实现能力”对照表（最初计划 + 开发规划）

| 应实现能力 | 来源 | 实测结论 | 结论等级 |
|---|---|---|---|
| `/random` 默认图片流、`format=json`、`redirect=1` | `最初计划.txt` / `随机api开发规划.md` | 全部可用；redirect 返回 `/i/<id>.<ext>` | 完成 |
| 强筛选参数（r18/orientation/min_*/tags/user_id/illust_id/attempts/seed） | 同上 | 参数生效；大量组合返回 `NO_MATCH`（数据侧） | 部分完成 |
| 分类检索 `/images` `/tags` `/authors` | 同上 | 可用，分页结构一致，limit 校验生效 | 完成 |
| legacy 兼容路由 | 同上 | 兼容路由可用；非法 page 返回 HTML 400 | 部分完成 |
| 管理后台不停机热更新 | 同上 | Import/easy_proxies/token binding/hydrationOps 均可在线执行 | 完成 |
| Admin 深层动作完整可用 | 同上 | 多动作可用，但存在 action 组件缺失、TokenProxyBinding 500、probe 504 | 部分完成 |
| 失败重试/降级健壮性 | 同上 | random attempts/NO_MATCH 路径有效；Admin 部分动作缺少稳定降级 | 部分完成 |
| 统计与运维（healthz/metrics/admin观测） | 同上 | healthz/metrics 可用；proxyPoolOverview 不稳定 | 部分完成 |
| 可维护/可扩展/可追溯 | 同上 | 有 request_id/audit/计划文档；仍有路由一致性与错误面统一问题 | 部分完成 |

## 3. 页面覆盖清单（含深层 action URL）

### 3.1 Admin 主页面与自定义页面

- `/admin`
- `/admin/pages/opsNavigator`
- `/admin/pages/importUrls`
- `/admin/pages/hydrationOps`
- `/admin/pages/easyProxiesImport`
- `/admin/pages/tokenProxyBindings`
- `/admin/pages/proxyPoolOverview`

### 3.2 资源页面（list/show/new/edit）

- `Image`
  - `/admin/resources/Image`
  - `/admin/resources/Image/records/1/show`
  - `/admin/resources/Image/records/3/show`
  - `/admin/resources/Image/actions/new`（禁用反馈）
  - `/admin/resources/Image/records/1/edit`（禁用反馈）
- `Tag`
  - `/admin/resources/Tag`
  - `/admin/resources/Tag/records/1/show`（测试期间执行了 delete）
- `PixivToken`
  - `/admin/resources/PixivToken`
  - `/admin/resources/PixivToken/records/1/show`
  - `/admin/resources/PixivToken/actions/new`
  - `/admin/resources/PixivToken/records/1/edit`
- `ProxyEndpoint`
  - `/admin/resources/ProxyEndpoint`
  - `/admin/resources/ProxyEndpoint/records/1/show`
  - `/admin/resources/ProxyEndpoint/actions/new`
  - `/admin/resources/ProxyEndpoint/records/1/edit`
- `TokenProxyBinding`
  - `/admin/resources/TokenProxyBinding`
  - `/admin/resources/TokenProxyBinding/records/1/show`
  - `/admin/resources/TokenProxyBinding/records/1/edit`
- `HydrationRun`
  - `/admin/resources/HydrationRun`
- `AdminAudit`
  - `/admin/resources/AdminAudit`
  - `/admin/resources/AdminAudit/records/1/show`
  - `/admin/resources/AdminAudit/new`（404）
  - `/admin/resources/AdminAudit/records/1/edit`（禁用反馈）
- `RequestLog`
  - `/admin/resources/RequestLog`
  - `/admin/resources/RequestLog/new`（404）
  - `/admin/resources/RequestLog/records/1/show`（禁用反馈）
- `Import`
  - `/admin/resources/Import`
  - `/admin/resources/Import/records/1/show`
  - `/admin/resources/Import/records/3/show`
  - `/admin/resources/Import/new`（404）
  - `/admin/resources/Import/records/1/edit`（禁用反馈）

### 3.3 深层 action（已触发）

- Image
  - `/admin/resources/Image/actions/statusCounts`
  - `/admin/resources/Image/records/1/hydrateMetadata`
  - `/admin/resources/Image/records/2/hydrateMetadata`
  - `/admin/resources/Image/records/1/disable`
  - `/admin/resources/Image/records/3/disable`
- PixivToken
  - `/admin/resources/PixivToken/records/1/testRefresh`
- ProxyEndpoint
  - `/admin/resources/ProxyEndpoint/records/1/probe`
  - `/admin/resources/ProxyEndpoint/actions/importProxyUris`
  - `/admin/resources/ProxyEndpoint/actions/easyProxiesConfigSave`
  - `/admin/resources/ProxyEndpoint/actions/easyProxiesImport`
  - `/admin/resources/ProxyEndpoint/actions/easyProxiesRollback`
- TokenProxyBinding
  - `/admin/resources/TokenProxyBinding/actions/rebindPrimary`
  - `/admin/resources/TokenProxyBinding/actions/setOverride`
  - `/admin/resources/TokenProxyBinding/actions/clearOverride`
- HydrationRun
  - `/admin/resources/HydrationRun/records/1/pause`
  - `/admin/resources/HydrationRun/records/1/resume`
  - `/admin/resources/HydrationRun/records/1/cancel`
- HydrationOps custom page actions
  - `POST /admin/api/pages/hydrationOps` with `dlq_retry/dlq_delete/dlq_list`

## 4. 功能完成度评分（按模块）

| 模块 | 评分 | 结果 |
|---|---:|---|
| 随机图片 API 主链路 | 90 | 默认流/JSON/redirect 全可用 |
| 强筛选能力 | 75 | 参数实现完整，数据命中率不足 |
| 分类 API (`/images` `/tags` `/authors`) | 88 | 契约稳定，参数校验生效 |
| legacy 兼容路由 | 80 | 主流程可用，错误包风格不一致 |
| Admin custom pages（import/easy/hydration/token-binding） | 82 | 多动作真实可执行，局部阻塞/UX断层 |
| Admin 资源 CRUD | 62 | 多资源只读/禁用策略可用，但路由一致性差 |
| 深层 record action | 65 | handler 多数可用，但组件缺失与部分 500/504 |
| 代理池与绑定 | 58 | custom page 写入成功，资源读路径 500 严重 |
| 可观测性（healthz/metrics/admin观测） | 70 | healthz/metrics 好，proxyPoolOverview 不稳定 |
| 健壮性/降级/可维护性 | 68 | request_id/audit 完整，错误体验与统一性待补齐 |

## 5. 问题清单（按严重级别）

### High
1. TokenProxyBinding 资源 API 在 list/show/edit 全部 500。
2. ProxyPoolOverview 页面 API pending/504，观测页卡死。
3. ProxyEndpoint probe 深层动作出现 504，无法稳定完成探测。
4. 大量 action 深链缺少组件（“See the documentation”），形成假可用。

### Medium
5. 资源 new/edit 访问路径与反馈不统一（404/未授权/无动作混杂）。
6. HydrationRun 空态下 pause/resume/cancel 仅 not found，无可恢复路径。
7. legacy 非法页码返回 HTML 400，偏离 JSON 错误契约。
8. 强筛选在生产数据上命中率偏低（NO_MATCH 占比较高）。

### Low
9. `/favicon.ico` 全站 400 噪声。
10. HydrationOps 表单可访问性不足（label/name/id 缺失）。

## 6. 每个问题的证据链与代码定位

### High-1 TokenProxyBinding 资源 API 500

- 复现步骤：访问 list/show/edit 页面。
- 页面 URL：
  - `/admin/resources/TokenProxyBinding`
  - `/admin/resources/TokenProxyBinding/records/1/show`
  - `/admin/resources/TokenProxyBinding/records/1/edit`
- 截图：
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-tokenProxyBinding-resource-list-empty-after-bindings.png`
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-tokenProxyBinding-edit-page-notfound-with-api500.png`
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-tokenProxyBinding-show-api500-rerun.png`
- Network：
  - `GET /admin/api/resources/TokenProxyBinding/actions/list` -> 500, `x-request-id=0cd63dcd-68ea-4fe5-9251-03cf7136c5af`
  - `GET /admin/api/resources/TokenProxyBinding/records/1/edit` -> 500, `x-request-id=983e04c9-218e-47bc-87ae-af72aac01874`
  - `GET /admin/api/resources/TokenProxyBinding/records/1/show` -> 500, `x-request-id=1550ef22-0a50-47b8-bd5c-75bb209c5d97`
- Console：`Failed to load resource: 500` + `Uncaught (in promise) z`。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:189`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:243`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:1491`
  - `pixiv-反代/pixivcat-backend/prisma/schema.prisma:236`
- 期望 vs 实际：应可读写一致；实际仅 custom page 写动作可用、资源读全损。
- 修复建议：拆分该资源的 where/coerce 流程并增加 API 集成测试。

### High-2 ProxyPoolOverview 卡加载

- 复现步骤：进入页面并等待刷新。
- 页面 URL：`/admin/pages/proxyPoolOverview`
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-proxyPoolOverview-loading-stuck-pending.png`
- Network：`GET /admin/api/pages/proxyPoolOverview` 持续 pending（历史样本出现 504）。
- Console：页面无业务错误提示，用户无法判断恢复路径。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:985`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:1020`
- 期望 vs 实际：应快速返回缓存+状态；实际长期“刷新中…”。
- 修复建议：超时 + stale-cache + 后台异步刷新。

### High-3 ProxyEndpoint probe 504

- 复现步骤：ProxyEndpoint record 点击 probe。
- 页面 URL：`/admin/resources/ProxyEndpoint/records/1/probe`
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-proxyEndpoint-probe-missing-component.png`
- Network：`POST /admin/api/resources/ProxyEndpoint/records/1/probe` -> 504。
- Console：出现资源加载失败，前端无恢复提示。
- 代码定位：`pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2429`
- 期望 vs 实际：应有可控超时和结构化 notice；实际网关 504。
- 修复建议：后端缩时、捕获并转换错误，必要时异步化。

### High-4 Action 深链组件缺失

- 复现步骤：直接访问 action URL（GET）。
- 页面 URL（示例）：
  - `/admin/resources/Image/records/1/hydrateMetadata`
  - `/admin/resources/PixivToken/records/1/testRefresh`
  - `/admin/resources/TokenProxyBinding/actions/setOverride`
- 截图：
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-image-hydrateMetadata-missing-component.png`
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-pixivToken-testRefresh-missing-component.png`
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-tokenProxyBinding-setOverride-missing-component.png`
- Network：同一 action API handler 可返回 200（如 `Image/hydrateMetadata` GET API）。
- Console：无业务提示，仅 AdminJS 通用文案。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/admin/resources/images.ts:130`
  - `pixiv-反代/pixivcat-backend/src/admin/resources/images.ts:199`
  - `pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:211`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:1519`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2929`
- 期望 vs 实际：应可执行或可解释；实际误导为“未实现组件”。
- 修复建议：为关键 action 增加组件/GET 重定向策略。

### Medium-5 资源 new/edit 路径不一致

- 复现步骤：跨资源访问 `/new`、`/actions/new`、`/records/:id/edit`。
- 页面 URL：
  - `/admin/resources/Import/new`（404）
  - `/admin/resources/RequestLog/new`（404）
  - `/admin/resources/PixivToken/new`（404）但 `/actions/new` 可用
  - `/admin/resources/Image/actions/new`（无动作/未授权）
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/resource-RequestLog-new-not-authorized.png`
- Network：出现 404 与 200+无动作提示混杂。
- Console：用户难判断“是禁用还是故障”。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/admin/resources/imports.ts:30`
  - `pixiv-反代/pixivcat-backend/src/admin/resources/requestLogs.ts:36`
  - `pixiv-反代/pixivcat-backend/src/admin/resources/adminAudits.ts:38`
- 期望 vs 实际：反馈风格应统一；实际差异过大。
- 修复建议：统一路由兼容和只读资源提示模板。

### Medium-6 HydrationRun 空态动作不可闭环

- 复现步骤：在空数据状态触发 pause/resume/cancel。
- 页面 URL：
  - `/admin/resources/HydrationRun/records/1/pause`
  - `/admin/resources/HydrationRun/records/1/resume`
  - `/admin/resources/HydrationRun/records/1/cancel`
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-hydrationRun-pause-record-not-found.png`
- Network：返回 200，但 notice 为 `Record ... cannot be found`。
- Console：无创建引导。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2707`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2763`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2849`
- 期望 vs 实际：应有可恢复入口；实际“空态死路”。
- 修复建议：新增创建 run CTA + fixture。

### Medium-7 legacy 非法页码错误包不一致

- 复现步骤：访问 `/:illustId-0.ext`。
- 页面 URL：`/136551599-0.jpg`
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-legacy-page0-invalid-400-html.png`
- Network：400，`content-type=text/html`。
- Console：调用方需额外分支解析 HTML。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/middlewares/validationMiddleware.ts:19`
  - `pixiv-反代/pixivcat-backend/src/routes/pixivRoutes.ts:10`
- 期望 vs 实际：JSON API 契约应统一；实际返回 HTML。
- 修复建议：legacy 非法参数返回兼容 JSON（或文档明确例外）。

### Medium-8 强筛选命中率偏低（数据侧）

- 复现步骤：执行 `random` 强筛选矩阵。
- 页面 URL：`/random?...` 多参数组合。
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/issue-random-r18-no-match-404.png`
- 结构化证据：`pixiv-反代/pixivcat-backend/docs/review/2026-02-07_03-30-03-api-test-results.json`
- Network：`random_r18_1`、`random_orientation_portrait` 等多例 404 `NO_MATCH`。
- Console：无前端异常，但对调用方体验影响明显。
- 代码定位：
  - `pixiv-反代/pixivcat-backend/src/routes/random.ts:347`
- 期望 vs 实际：期望常见筛选可稳定命中；实际样本覆盖不足。
- 修复建议：补充库内元数据覆盖、按标签/方向预热导入。

### Low-9 `/favicon.ico` 400 噪声

- 复现步骤：任意后台页面切换。
- 页面 URL：`/favicon.ico`
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/admin-dashboard.png`
- Network：频繁 400。
- Console：大量 `Failed to load resource 400`。
- 代码定位：`pixiv-反代/pixivcat-backend/app.ts`
- 期望 vs 实际：应返回 icon 或 204；实际持续报错。
- 修复建议：加 favicon 路由或静态资源。

### Low-10 HydrationOps 可访问性 issue

- 复现步骤：打开 `HydrationOps` 页面。
- 页面 URL：`/admin/pages/hydrationOps`
- 截图：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-07_03-30-03/page-hydrationOps-dlq-retry-delete-rerun.png`
- Network：业务请求可成功。
- Console：
  - `No label associated with a form field`
  - `A form field element should have an id or name attribute`
- 代码定位：`pixiv-反代/pixivcat-backend/src/admin/pages/hydrationOps.jsx:291`
- 期望 vs 实际：应满足基本可访问性；实际存在结构缺陷。
- 修复建议：补充 `label/htmlFor` 和 `id/name`。

## 7. 必须立即修复 Top 10（按业务影响）

1. 修复 TokenProxyBinding 资源 API 500（读路径恢复）。
2. 修复 ProxyPoolOverview pending/504（超时+缓存降级）。
3. 修复 ProxyEndpoint probe 504（后端可控超时与错误转换）。
4. 为关键深层 action 提供组件或 GET 重定向策略。
5. 统一资源 new/edit 路由与禁用反馈语义。
6. 给 HydrationRun 空态增加可恢复入口（创建 run/引导）。
7. 统一 legacy 非法参数错误包（至少文档显式例外）。
8. 建立“强筛选数据覆盖”基线任务（R18/方向/标签）。
9. 清理 `/favicon.ico` 400 噪声，恢复 console 信噪比。
10. 修复 HydrationOps 表单可访问性（降低长期维护成本）。

## 8. 可维护性 / 拓展性 / 健壮性风险

- AdminJS 动作“API可用 vs 页面不可用”割裂，后续迭代容易回归。
- BigInt + Prisma adapter 的通用 where coercion 对复杂关系资源存在隐性破坏面。
- 资源级禁用策略较多，缺少统一 UX 约定，排障依赖经验。
- 外部依赖（probe、health check）直接走同步路径，容易拖垮管理面。
- 观测页（proxyPoolOverview）与实际状态绑定过紧，缺少缓存快照策略。
- 错误包跨 legacy/JSON API 风格不一致，影响调用方与监控规则统一。

## 9. blocked 项（真实受限）

- `blocked: 部分资源无法达到“每资源至少3条记录”覆盖`  
  实况：`HydrationRun`、`RequestLog`、`Import`、`TokenProxyBinding` 等资源记录量受线上数据限制，已尽量覆盖可用记录与空态/异常态。
- `blocked: ProxyEndpoint probe 受外部链路影响出现 504`  
  已复现并记录 `cf-ray` 与 request_id 证据，非前端可单点消除。
- `blocked: ProxyPoolOverview 数据请求存在 pending/504 外部与后端联动阻塞`  
  页面表现为长时间刷新中，已持续记录网络证据。

## 10. 总结：是否达到“最初计划的完美实现”标准

**结论：未达到“完美实现”标准，但已达到“核心链路可用、深层功能部分可用”的阶段。**

依据：
- 正向能力已成立：random 主链路、分类 API、healthz/metrics、import/easy_proxies/token binding/hydrationOps 多项动作可真实执行。
- 关键缺口仍在：
  - TokenProxyBinding 资源读路径 500（严重功能缺陷）；
  - ProxyPoolOverview 可观测页不稳定；
  - probe 动作 504；
  - action 深链组件缺失导致深层可用性与可解释性不足。

建议：先完成 Top 10 的前 4 项再进入下一轮功能扩展，否则会持续出现“看起来有功能、实际不可稳定操作”的运维风险。
```

</details>

<details>
<summary>附录H：最详细页面与功能实现问题（线上审计）</summary>

`md
# 最详细页面和功能实现问题（全量、深层、可追溯审计报告）

> 目标：对已部署站点做**真实访问测试**与**实现完成度审计**，输出可执行问题清单与优化方向（允许大幅重构）。  
> 目标站点：`https://i.mukyu.ru`  
> 线上深测基线证据（时间戳：`2026-02-08_04-48-29`）：  
> - Admin：`pixiv-反代/pixivcat-backend/docs/review/2026-02-08_04-48-29-admin-deep-audit.md`  
> - API：`pixiv-反代/pixivcat-backend/docs/review/2026-02-08_04-48-29-api-contract-audit.md`  
> - Screenshots：`pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-08_04-48-29/`  
> - Network：`pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/`  
> - Console：`pixiv-反代/pixivcat-backend/docs/review/console/2026-02-08_04-48-29/`
>
> 修复与复核证据（时间戳：`2026-02-09_05-56-38`）：  
> - Admin：`pixiv-反代/pixivcat-backend/docs/review/2026-02-09_05-56-38-admin-deep-audit.md`  
> - API：`pixiv-反代/pixivcat-backend/docs/review/2026-02-09_05-56-38-api-contract-audit.md`  
> - Issues（全量拆分与状态）：`pixiv-反代/pixivcat-backend/issues/2026-02-09_05-56-38-full-remediation.csv`  
> - Plan（依赖顺序）：`pixiv-反代/pixivcat-backend/plan/2026-02-09_05-56-38-full-remediation.md`  
> - Fixes（逐 issue 修复验证）：`pixiv-反代/pixivcat-backend/docs/review/fixes/2026-02-09_05-56-38/`  
> - 本地回归摘要：`pixiv-反代/pixivcat-backend/docs/review/console/2026-02-09_05-56-38/local-regression.summary.txt`

安全约束（硬要求）：
- 本文件与引用证据中不得出现任何完整凭据（token/password/refresh_token/代理密码）。如需引用，仅用掩码（如 `inl***` / `***`）。
- 若必须引用配置，仅写“已配置并验证可用（掩码）”。

审计说明（重要）：
- 本轮为真实站点深测，期间为验证 CRUD/动作流，**在后台创建/删除了少量审计用测试数据**（例如：Tag 记录、ProxyEndpoint dummy 记录、PixivToken dummy 记录、HydrationRun backfill run）。报告中会明确标注，不将其误判为业务数据。
- 2026-02-09 修复已按 issues 拆分逐条落地（含单测/构建/lint）；但生产站点仍未 redeploy（`/version` 404、`/healthz` 无 `build.*`），因此“修复后线上复验”暂时 blocked：需要按部署文档完成 redeploy + migrate 后重跑全量审计清单。

---

## 0. 修复交付状态（2026-02-09）

- 代码侧交付：`pixiv-反代/pixivcat-backend/issues/2026-02-09_05-56-38-full-remediation.csv` 中所有“功能修复项”已完成并提交（每项都有对应的修复验证文档：`pixiv-反代/pixivcat-backend/docs/review/fixes/2026-02-09_05-56-38/`）。
- 本地回归证据：`pixiv-反代/pixivcat-backend/docs/review/console/2026-02-09_05-56-38/local-regression.summary.txt`（`npm run test:all` + `run-regression` + `proxy-smoke`）。
- 线上复验现状：生产站点仍未 redeploy（`/version` 404、`/healthz` 无 `build.*`），导致“修复后线上复验”暂时 blocked；需完成 redeploy + migrate 后，按 `pixiv-反代/pixivcat-backend/docs/review/2026-02-09_05-56-38-*.md` 清单重跑全量审计并回写证据链。

## 1. 审计范围与方法

### 1.1 覆盖范围（强制全覆盖）
- Admin：
  - `/admin`
  - `/admin/pages/*` 全部
  - `/admin/resources/*` 全部资源 list/show/new/edit
  - 所有 recordActions/resourceActions/bulkActions：必须“进入深链 + UI 触发 + 验证 notice/network/状态变化”
- Public API：
  - `/random`（binary/json/redirect + 参数矩阵）
  - `/i`、`/images`、`/tags`、`/authors`、legacy 路由
  - `/healthz`、`/metrics`（契约与错误包结构）

### 1.2 工具与证据落盘
- UI/E2E：Chrome DevTools MCP（真实站点操作，截图落盘）
- Contract/API：真实 HTTP 请求（按文档契约与异常态矩阵；headers/body 落盘）
- 证据标准：每个问题至少包含
  1) 复现步骤（可复制）
  2) URL（精确深链）
  3) 关键 network 摘要（method/status/错误码）
  4) console 摘要
  5) 代码定位（文件+行号）
  6) 期望 vs 实际
  7) 修复建议（可执行）

---

## 2. “应实现能力”对照表（来自最初计划 + 开发规划 + README/docs）

基线来源：
- `最初计划.txt`：随机图片 API + 强筛选 + 后台热更新 + 稳健性/统计
- `pixiv-反代/pixivcat-backend/随机api开发规划.md`：总体架构/能力分层/运维与性能策略
- `pixiv-反代/pixivcat-backend/README.md` + `pixiv-反代/pixivcat-backend/docs/**`：端点契约、后台页面与鉴权、proxy/token/hydration、可观测与错误语义
- 代码实现：`pixiv-反代/pixivcat-backend/app.ts` + `src/routes/*` + `src/admin/*` + `src/proxy/*` + `src/jobs/*`

| 应实现能力 | 基线来源 | 期望行为（摘要） | 线上实测结论 | 状态 | 关键证据 |
|---|---|---|---|---|---|
| legacy Pixivcat 路由可用 | `最初计划.txt` / README | `/:illustId.:ext`、`/:illustId-:page.:ext` 流式代理 + 长缓存 + 可解释错误 | 可用 | 完成 | `.../docs/review/2026-02-08_04-48-29-api-contract-audit.md`（legacy 章节） |
| `/random` 三形态（binary/json/302） | README / `docs/api/random.md` | 默认 binary；`format=json`；`redirect=1` 302 -> `/i/*` | 可用 | 完成 | `.../docs/review/network/2026-02-08_04-48-29/random_*.headers.txt` |
| `/random` 参数矩阵 | `docs/api/random.md` | r18/r18_strict/orientation/min_*/tags/user_id/illust_id/attempts/seed | 大体生效；但存在 int4 超界触发 500；强筛选命中率受数据/补全影响 | 部分完成 | `.../docs/review/2026-02-08_04-48-29-api-contract-audit.md`（API-001/API-002） |
| 分类检索 `/tags` `/authors` `/images` | `docs/api/classification.md` | JSON + cursor + no-store + 400 校验 | 接口可用；但 tags/authors 数据为空（补全链路问题） | 部分完成 | `.../docs/review/network/2026-02-08_04-48-29/tags_*.body`、`authors_*.body` |
| 稳定图片 `/i/:id.:ext` | README | 长缓存（可 CDN） | 可用 | 完成 | `.../docs/review/network/2026-02-08_04-48-29/random_redirect_follow.headers.txt` |
| `/healthz` 依赖健康 | README / `docs/errors.md` | 返回 db/memcached/queue 健康与 request_id | 可用 | 完成 | `.../docs/review/network/2026-02-08_04-48-29/healthz_get.body` |
| `/metrics` 可控启用+可选鉴权 | README / `docs/usage/handbook.md` | disabled 时 404；可选 basic auth | 线上已启用且未开启 basic auth（属于配置风险） | 部分完成 | `.../docs/review/network/2026-02-08_04-48-29/metrics_get.headers.txt` |
| Admin 页面全覆盖 | `docs/usage/handbook.md` | `/admin/pages/*` 可打开并可执行关键动作 | 页面基本可打开；但存在加载卡住与配置缺失阻断 | 部分完成 | `.../docs/review/2026-02-08_04-48-29-admin-deep-audit.md`（pages） |
| Admin 资源全覆盖 | `docs/usage/handbook.md` | `/admin/resources/*` list/show/new/edit 可达（只读需明确） | 主要资源可达；但 `ProxyPool` 资源缺失、`TokenProxyBinding` 资源 500 | 部分完成 | `.../docs/review/screenshots/2026-02-08_04-48-29/admin-1238-proxyPool-resource-missing.png`、`admin-1222-tokenProxyBinding-resource-list-error.png` |
| Admin 深层 record action 可用 | `docs/usage/handbook.md` | `testRefresh/hydrateMetadata/probe/pause/resume/cancel` 等可触发并反馈 notice | **大面积 not found + 504**，关键闭环断裂 | 未达标 | `.../docs/review/network/2026-02-08_04-48-29/admin_action_deeplink_checks.txt`、`admin_action_post_checks.txt` |
| proxy/token/binding 热更新闭环 | `docs/traceability-proxy-pool.md` | 导入代理/绑定 token/失败切换/审计可追溯 | 自定义页 `tokenProxyBindings` 可操作；但资源页坏 + probe/refresh 动作不可用 | 部分完成 | `.../docs/review/screenshots/2026-02-08_04-48-29/admin-1108-tokenProxyBindings-rebindPrimary-success.png` |
| 敏感信息保护 | `docs/admin.md` / 合规要求 | refresh_token/代理密码不得回显、不得进入日志/前端 | **ProxyEndpoint 密码可回显/可被前端获取（高危）** | 未达标 | `.../docs/review/screenshots/2026-02-08_04-48-29/admin-1305-proxyEndpoint-12-edit-password-visible-masked.png` + 代码定位见问题详述 |

---

## 3. 覆盖结果总览（通过/失败/blocked）

### 3.1 Admin 覆盖
- `/admin/pages/*`：7/7 已访问并取证（详见 `.../docs/review/2026-02-08_04-48-29-admin-deep-audit.md`）
- `/admin/resources/*`：已覆盖运行态可见资源（Image/Tag/Import/PixivToken/TokenProxyBinding/ProxyEndpoint/HydrationRun/AdminAudit/RequestLog）；另外发现 `ProxyPool` 资源缺失
- 深层动作（Action）：
  - **成功**：Tag 的 create/edit/delete（多次）、Tag bulkDelete（后续窗口成功）、Image.statusCounts、tokenProxyBindings 页面上的 rebind/override/clearOverride
  - **失败/不可用**：PixivToken.testRefresh、Image.hydrateMetadata/disable/enable、ProxyEndpoint.probe、HydrationRun.pause/resume/cancel、TokenProxyBinding 资源读路径
  - **主要失败模式**：UI 深链 not found、Admin API POST 504（Cloudflare gateway timeout）

### 3.2 Public API 覆盖
- `/random`（binary/json/redirect + attempts/seed/r18/orientation/min_*/tags/user_id/illust_id 等矩阵）已取证
- `/images`、`/tags`、`/authors`、`/images/:id`、`/i/:id.:ext` 已取证
- `/healthz`、`/metrics` 已取证
- legacy 路由已取证

---

## 4. 关键结论摘要（先说结论）

1) **公网随机 API 主链路可用**（/random 与 /i/legacy 均可返回图片），但“高价值筛选/分类”的有效性被“元信息补全不可用”严重削弱。  
2) **AdminJS 深层动作大面积失效（not found + 504）**，导致“导入后补全/刷新 token/探测代理/控制 backfill run”等核心闭环无法运行。  
3) **存在严重敏感信息泄露风险**：ProxyEndpoint 密码可在后台 edit 明文回显，且可被前端拿到（高危）。  
4) 线上表现与本仓库实现存在“疑似未部署/版本落后”迹象：本仓库代码已定义多项 action 与降级逻辑，但线上仍显示 not found/504（需核对部署产物与运行入口）。

---

## 5. 问题清单（按严重级别 High/Medium/Low）

> 本节仅列标题与影响；第 6 节给出每条的证据链与代码定位。

### High
- ADM-001：AdminJS 深层 action 深链普遍 not found（核心闭环断裂）
- ADM-002：Admin action POST 大量 504（Cloudflare gateway timeout），导致动作不可执行
- ADM-003：ProxyEndpoint 密码可明文回显/前端可获取（严重安全风险）
- ADM-004：TokenProxyBinding 资源读链路 500（资源不可用，假可用/一致性风险）
- API-001：`min_width/min_height/min_pixels` 超 int4 上限触发 500（应为 400）

### Medium
- ADM-005：ProxyPool 资源缺失（只能看概览页，无法 CRUD/审计/定位）
- ADM-006：HydrationOps 存在“刷新中卡住/无可解释降级”体验，影响补全运维
- ADM-007：easy_proxies 配置缺失/外部依赖导致导入被阻断（需要更明确的 blocked 语义）
- API-002：线上元信息覆盖率低导致 `/tags`/`/authors` 为空、强筛选频繁 NO_MATCH（核心卖点被削弱）
- API-003：`/metrics` 未开启 basic auth（配置风险：暴露运行态指标）
- CONS-001：Tag.bulkDelete 在不同时间窗口出现 500/504 与成功混杂（稳定性/一致性风险）

### Low
- UX-001：部分后台 action guard 文案与实现不一致（例如“不会明文展示”与实际回显风险并存）
- UX-002：部分页面/资源存在“可打开但无恢复路径”的死路（建议统一空态/异常态引导）

---

## 6. 每个问题的证据链与代码定位（详述）

> 说明：Admin 侧更多逐页细节见 `pixiv-反代/pixivcat-backend/docs/review/2026-02-08_04-48-29-admin-deep-audit.md`；API 侧矩阵细节见 `pixiv-反代/pixivcat-backend/docs/review/2026-02-08_04-48-29-api-contract-audit.md`。

### ADM-001：AdminJS 深层 action 深链普遍 not found（核心闭环断裂）
- 严重级别：High
- 影响面：刷新 token / 元信息补全 / 代理探测 / run 控制不可用；出现“按钮/入口存在但不可执行”的假可用
- 复现步骤（以 Image 为例）：
  1. 打开 `https://i.mukyu.ru/admin/resources/Image/records/1/show`
  2. 访问 `https://i.mukyu.ru/admin/resources/Image/records/1/hydrateMetadata`
  3. 页面显示“找不到网页：具有 id: Image 的资源没有名为 hydrateMetadata 的操作…”
- 页面 URL（样例）：
  - `https://i.mukyu.ru/admin/resources/Image/records/1/hydrateMetadata`
  - `https://i.mukyu.ru/admin/resources/PixivToken/records/1/testRefresh`
  - `https://i.mukyu.ru/admin/resources/HydrationRun/records/1/pause`
- 关键 Network 摘要：
  - `GET /admin/resources/Image/records/1/hydrateMetadata -> 200 (页面内错误提示)`
- Console 摘要：无显式 JS error；失败更多体现在“路由层 not found”与“执行层 504”
- 相关代码定位（“应存在”的动作定义，用于对照部署版本）：
  - `pixiv-反代/pixivcat-backend/src/admin/resources/images.ts:203`
  - `pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:211`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2844`
- 期望 vs 实际：
  - 期望：深链可打开 action 页面，并可点击确认触发 POST，返回 notice + redirect
  - 实际：深链直接 not found（动作失效）
- 修复建议（可执行）：
  1. 核对线上实际运行的 AdminJS 资源/动作注册表与本仓库一致性（强烈怀疑未部署最新构建或运行旧版本/旧 dist）；
  2. 为所有自定义 action 明确 `component:false`（或提供已打包的自定义 component），并保证 `GET` 分支可返回 `record`；
  3. 增加“线上 Admin 深链 smoke”回归：逐个 GET 深链 + POST 执行（失败即报警）。
- 证据文件：
  - `pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/admin_action_deeplink_checks.txt`
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-08_04-48-29/admin-1204-image-hydrateMetadata-deeplink-notfound.png`
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-08_04-48-29/admin-1212-pixivToken-testRefresh-deeplink-notfound.png`

### ADM-002：Admin action POST 大量 504（Cloudflare gateway timeout），导致动作不可执行
- 严重级别：High
- 影响面：所有“依赖外部资源”的动作在网关层直接超时，UI 反馈不可解释
- 复现步骤（以 PixivToken.testRefresh 为例）：
  1. 在 PixivToken show 页触发 testRefresh
  2. 观察 Admin API `POST /admin/api/resources/PixivToken/records/1/testRefresh -> 504`
- 关键 Network 摘要（样例）：
  - `POST /admin/api/resources/PixivToken/records/1/testRefresh -> 504`
  - `POST /admin/api/resources/Image/records/1/hydrateMetadata -> 504`
  - `POST /admin/api/resources/HydrationRun/records/1/pause -> 504`
- Console 摘要：`Failed to load resource: 504`（见 console 证据）
- 相关代码定位（应具备“快速降级/异步化”的位置）：
  - `pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:217`
  - `pixiv-反代/pixivcat-backend/src/admin/resources/images.ts:209`
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2526`
- 期望 vs 实际：
  - 期望：动作在外部依赖失败时快速返回结构化 notice（timeout/blocked），或转为异步 job
  - 实际：504（网关超时）+ UI 无可解释反馈
- 修复建议（可执行）：
  1. 为所有外部依赖动作设置严格 timeout（< Cloudflare 超时预算），并把耗时逻辑移到 job（pg-boss）；
  2. action 返回中包含 `code/status/message/request_id`，并提供“去哪里看进度/日志”的恢复入口；
  3. 明确网关/反代的超时预算（包括 Cloudflare、上游代理、Pixiv API），写入 runbook。
- 证据文件：
  - `pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/admin_action_post_checks.txt`
  - `pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/admin_pixivToken_testRefresh_post_504_cloudflare.json`
  - `pixiv-反代/pixivcat-backend/docs/review/console/2026-02-08_04-48-29/admin_actions_console_messages_001.txt`

### ADM-003：ProxyEndpoint 密码可明文回显/前端可获取（严重安全风险）
- 严重级别：High
- 影响面：代理密码泄露（后台操作者/浏览器端/潜在 XSS/截图/日志），可能导致代理池被盗用或暴露真实 IP
- 复现步骤：
  1. 打开 `https://i.mukyu.ru/admin/resources/ProxyEndpoint/records/12/edit`
  2. 观察 `Password` 输入框为普通文本输入框（`type=text`）且可回显
  3. 通过 Admin API action preflight 可获取 record.params.password（本轮已脱敏留证）
- 页面 URL：`https://i.mukyu.ru/admin/resources/ProxyEndpoint/records/12/edit`
- 关键 Network 摘要：`GET /admin/api/resources/ProxyEndpoint/records/12/probe -> 200`（响应包含 `password` 字段；已脱敏）
- Console 摘要：无（问题为“设计与数据暴露”）
- 相关代码定位：
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2806`（`properties.password.isVisible.edit=true`）
  - `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2554`（probe 读取 password 并拼接 proxyUri）
- 期望 vs 实际：
  - 期望：password 为 write-only，不回显；前端永远拿不到明文（最多显示 `password_configured=true/false`）
  - 实际：edit 可回显；API 返回 `password` 字段
- 修复建议（可执行）：
  1. DB 层：代理密码改为“加密存储 + 仅 server 可解密使用”（或迁移到 easy_proxies 并仅保存引用）；
  2. AdminJS 层：password 字段改为 write-only（edit 默认空；提供 `clear_password` 勾选）；并在 list/show/API 响应中彻底剔除 `password`；
  3. 文案/契约：`importProxyUris` guard 文案必须与实现一致（不要承诺“不会明文展示”但实际回显）。
- 证据文件：
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-08_04-48-29/admin-1305-proxyEndpoint-12-edit-password-visible-masked.png`
  - `pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/admin_proxyEndpoint_12_probe.response.json`

### ADM-004：TokenProxyBinding 资源读链路 500（资源不可用，假可用/一致性风险）
- 严重级别：High
- 复现步骤：
  1. 打开 `https://i.mukyu.ru/admin/resources/TokenProxyBinding`
  2. 资源 list 返回 500（页面显示错误）
- 页面 URL：`https://i.mukyu.ru/admin/resources/TokenProxyBinding`
- 关键 Network 摘要：`GET /admin/api/resources/TokenProxyBinding/actions/list -> 500`
- 相关代码定位（本仓库对照）：
  - 资源注册：`pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:1580`
  - filter 空值防护：`pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:110`、`pixiv-反代/pixivcat-backend/src/admin/utils/filterValue.ts:1`
- 期望 vs 实际：
  - 期望：资源 list/show/edit 可读，页面动作与资源动作一致
  - 实际：资源页不可用，但同名自定义页面 `tokenProxyBindings` 可操作 → 体验割裂、排障困难
- 修复建议（可执行）：
  1. 以线上 500 的 `request_id` 对齐 server 日志定位根因（重点检查 BigInt/筛选条件）；
  2. 统一“资源页/自定义页”的能力边界：要么都可用、要么资源页明确下线并给出跳转到页面的引导。
- 证据文件：
  - `pixiv-反代/pixivcat-backend/docs/review/screenshots/2026-02-08_04-48-29/admin-1222-tokenProxyBinding-resource-list-error.png`
  - `pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/admin_tokenProxyBinding_list_500.json`

### API-001：`min_width/min_height/min_pixels` 超过 int4 上限触发 500（应为 400）
- 严重级别：High
- 复现步骤：
  1. 请求 `GET /random?format=json&min_width=2147483648`
  2. 观察返回 `500`（Prisma/P2010/P2020 一类错误）
- 请求 URL（样例）：
  - `GET /random?format=json&min_width=2147483648` → `500`：`pixiv-反代/pixivcat-backend/docs/review/network/2026-02-08_04-48-29/random_min_width_int4_over.body`
- 相关代码定位（根因点）：
  - 输入层缺上限校验：`pixiv-反代/pixivcat-backend/src/routes/random.ts:159`（parseMinWidth 仅校验 safeInteger/非负）
  - images 同类：`pixiv-反代/pixivcat-backend/src/routes/images.ts:155`
  - 查询层溢出：`pixiv-反代/pixivcat-backend/src/repositories/imagesRepo.ts:260`、`pixiv-反代/pixivcat-backend/src/repositories/imagesRepo.ts:426`
- 期望 vs 实际：
  - 期望：超界值返回 `400 BAD_REQUEST`（或 clamp 后 NO_MATCH），并给出明确错误文案
  - 实际：500
- 修复建议（可执行）：
  1. 输入层：`min_*` 加上限校验（`<= 2147483647`），超界直接 400；
  2. 查询层：raw SQL 使用 bigint cast 避免乘法溢出（`width::bigint * height::bigint`）；
  3. 增加契约测试覆盖超界值（防回归）。
- 证据文件：见 `pixiv-反代/pixivcat-backend/docs/review/2026-02-08_04-48-29-api-contract-audit.md`（API-001）

---

## 7. Top 10（必须立即修复，按业务影响排序）

1) 修复 Admin 深层 action not found（ADM-001）：否则“补全/刷新/探测/控制”全部无法闭环  
2) 消除 Admin action 504（ADM-002）：所有外部依赖动作异步化 + timeout + 可解释 notice  
3) 修复 ProxyEndpoint 密码泄露（ADM-003）：write-only + API 剔除 + 加密存储  
4) 修复 TokenProxyBinding 资源 500（ADM-004）：资源页恢复可读，消除假可用  
5) 修复 `min_*` 超界触发 500（API-001）：避免轻易触发 500  
6) 打通元信息补全主链路（关联 ADM-001/ADM-002）：否则标签/作者/筛选价值无法兑现  
7) 为 hydrationOps/proxyPoolOverview 增加超时与 stale/fallback（ADM-006）：避免“刷新中卡死”  
8) 明确 easy_proxies 配置与 blocked 语义（ADM-007）：缺 baseUrl 时动作应清晰告知并禁止误操作  
9) `/metrics` 建议启用 basic auth（API-003）：避免裸露运行态指标  
10) 修复 bulkDelete 等操作在时间窗口内不一致（CONS-001）：避免“偶现成功/偶现失败”的运维灾难

---

## 8. 可维护性 / 拓展性 / 健壮性风险（面向重构建议）

- **运行入口与部署一致性风险**：线上表现与仓库实现存在偏差（怀疑旧 dist/旧 commit 在跑）；需在 `/healthz` 或 `/admin` 明确暴露 build/version/commit，并把“部署产物一致性校验”写入发布流程。
- **长耗时动作不应同步执行**：refresh/probe/hydrate/backfill 控制都应异步 job 化（立即返回 + 进度页），否则在 Cloudflare/反代超时预算下必然 504。
- **敏感信息必须端到端治理**：代理密码/refresh token 必须做到“日志不落盘、前端拿不到、DB 加密/或仅存引用”，并给出专门的脱敏工具与审计策略。
- **资源页与自定义页能力分裂**：同一概念（TokenProxyBinding）“资源坏但页面可用”会导致排障与运维心智崩溃；建议统一信息架构与跳转。
- **数据补全是随机 API 的生命线**：若 hydrateMetadata/backfill 长期不可用，则 `/tags`/`/authors` 与强筛选的价值无法兑现，最终只剩“随机返图”，与最初目标偏差巨大。

---

## 9. blocked 项（真实受限项，不得伪造）

- blocked:cloudflare_gateway_timeout（多条 Admin action POST 被 504 阻断；需线上日志/网关超时预算/外部依赖稳定性配合定位）
- blocked:non_interactive_relogin_without_secrets（为避免工具调用输出明文凭据，本轮未执行“清 cookie 后重新登录”的回归；以已登录页面渲染证据替代）

---

## 10. 总结：是否达到“最初计划的完美实现”

结论：**否（未达标）**。

依据（可追溯）：
- 公网 API 主链路（/random、/i、legacy）可用，但关键筛选能力存在契约缺陷（API-001）且数据补全不足（API-002）。
- Admin 的“核心闭环动作”大面积不可用（ADM-001/ADM-002），直接阻断“导入→补全→分类→高自定义随机 API”的目标路径。
- 存在高危安全问题（ADM-003：代理密码可回显/前端可得），必须先修复才能谈可用性与对外开放。
```

</details>

<details>
<summary>附录I：第二次最详细页面与功能实现问题（线上审计）</summary>

`md
# 第二次最详细页面和功能实现问题（真实站点全量深测 + 完成度审计）

- 审计时间：2026-02-09（本机 Codex CLI + Chrome DevTools MCP 实测）
- 目标站点：`https://i.mukyu.ru`
- 输出要求：中文、详尽、可执行、带证据链（截图/网络摘要/控制台摘要/代码定位）

> 安全硬规则（已执行）：本文与仓库内证据**不写入任何明文凭据**（token/password/refresh_token/代理密码/cookie）。所有引用仅使用掩码或长度（例如 `***`、`len=43`）。

---

## 1. 审计范围、方法与证据目录

### 1.1 范围（硬覆盖）

1) AdminJS（深层可用性，尤其 actions）
- `/admin`
- `/admin/pages/*` 全部页面
- `/admin/resources/*` 全部资源 list/show/new/edit（可达即测）
- **每个资源 action/record action/resource action/bulk action**：逐个触发或给出 blocked 证据

2) Public API（契约矩阵）
- `/random`（binary/json/redirect）与参数矩阵
- `/i`、`/images`、`/tags`、`/authors`、legacy 路由
- `/healthz`、`/metrics`、`/version`

### 1.2 方法（保证“真实访问测试”可追溯）

- 真实站点交互：使用 `chrome-devtools` MCP 打开页面、点击按钮、提交动作、观察 notice/跳转/状态变化。
- 接口契约：以 curl 落盘（headers/body）为准，补充 Admin API 的脱敏摘要。
- 代码完成度：对照 `最初计划.txt` + `pixiv-反代/pixivcat-backend/随机api开发规划.md` + docs/README + 线上实测行为，定位到具体文件与行号。

### 1.3 证据（本轮时间戳：`2026-02-09_15-20-48`）

- Admin 深测过程文档：`docs/review/2026-02-09_15-20-48-admin-deep-audit.md`
- Public API 契约审计：`docs/review/2026-02-09_15-20-48-api-contract-audit.md`
- 截图目录：`docs/review/screenshots/2026-02-09_15-20-48/`
- Network（脱敏）：`docs/review/network/2026-02-09_15-20-48/`
- API artifacts（headers/body）：`docs/review/artifacts/2026-02-09_15-20-48/api/`
- Admin artifacts（脱敏）：`docs/review/artifacts/2026-02-09_15-20-48/admin/`

---

## 2. “应实现能力”对照表（来自最初计划 + 开发规划）

> 说明：本表“应实现能力”来自 `最初计划.txt` 与 `pixiv-反代/pixivcat-backend/随机api开发规划.md` 的核心目标（导入→元数据→分类→高可用随机 API + 可运维后台）。  
> “实际结果”以线上 `https://i.mukyu.ru` 实测为准，证据链见第 6 节。

| 能力域 | 应实现能力（摘要） | 实际结果（线上） | 关键证据 |
|---|---|---|---|
| 图片库闭环 | 能导入大量 Pixiv 原图 URL → 生成 Image 库（可筛选、可随机） | ❌ **Image=0**，闭环断裂；/random 永久 NO_MATCH | `admin-0143-image-list-0-records.png`、`api/random-json.body.txt` |
| 随机图片 API | `/random` 默认返回图片；`format=json` 返回 JSON；`redirect=1` 302 | ❌ 因 Image=0 全部 404；json 为 `NO_MATCH` | `docs/review/artifacts/.../api/random*.body*` |
| 强筛选 | r18/作者/标签/方向/尺寸/seed/attempts 等 | ⚠️ 校验基本存在，但 tags 多值仅取第一个；无数据无法验证“筛选命中” | `docs/review/2026-02-09_15-20-48-api-contract-audit.md` |
| 后台热更新 | 不停机导入/删除/启停/修复，实时生效 | ❌ 导入无法落到 Image；部分动作 UI 不可用 | `admin-0150~0153-*.png`、多处“找不到网页” |
| Token 刷新 | refreshToken 入库、掩码展示、测试刷新动作可追溯 | ❌ `testRefresh` 入队但 job 失败；且 **Admin API 回显 refreshToken 明文（严重）** | `admin-0130-*.png`、`artifacts/.../pixivtoken-refresh-token-leak.summary.json` |
| 代理池 | 代理端点导入、启停、探测、绑定令牌、回退策略 | ⚠️ 端点 CRUD 可用；`probe` 入队但失败；多个 resource action 按钮进入“找不到网页” | `admin-0039-*.png`、`admin-0134-*.png` |
| 元数据补全 | Image.hydrateMetadata / 补全运行控制 / DLQ | ⚠️ HydrationRun 的 pause/resume/cancel 可用；Image 无记录导致 hydrateMetadata blocked；DLQ 页面可操作 | `admin-0082~0084-*.png`、`admin-0115~0116-*.png` |
| 统计与审计 | RequestLog/AdminAudit 可读、可检索、可追溯 | ⚠️ 基本可浏览；但核心队列不可观测导致排障困难 | `admin-0090-*.png`、`admin-0094-*.png` |
| 运维端点 | `/healthz`、`/version`、`/metrics` 合约清晰 | ⚠️ `/healthz`/`version` OK；metrics 受保护返回 404/401（需文档对齐） | `api/healthz.*`、`api/version.*`、`api/metrics.*` |

---

## 3. 覆盖情况摘要（是否满足“全量深层”）

### 3.1 Admin Pages（全部覆盖，且触发关键操作）

已覆盖并落盘截图（代表性证据）：
- Dashboard：`docs/review/screenshots/2026-02-09_15-20-48/admin-0001-dashboard.png`
- opsNavigator：`docs/review/screenshots/2026-02-09_15-20-48/admin-0002-ops-navigator.png`
- importUrls：`docs/review/screenshots/2026-02-09_15-20-48/admin-0003-import-urls-page.png`
- adminJobs：`docs/review/screenshots/2026-02-09_15-20-48/admin-0004-admin-jobs.png`
- hydrationOps：`docs/review/screenshots/2026-02-09_15-20-48/admin-0005-hydration-ops.png`
- easyProxiesImport：`docs/review/screenshots/2026-02-09_15-20-48/admin-0006-easy-proxies-import.png`
- tokenProxyBindings：`docs/review/screenshots/2026-02-09_15-20-48/admin-0007-token-proxy-bindings-page.png`
- proxyPoolOverview（脱敏）：`docs/review/screenshots/2026-02-09_15-20-48/admin-0156-proxyPoolOverview-masked.png`

### 3.2 Admin Resources（全部覆盖 list 入口；部分资源因“无记录/动作不可用”达不到 3 条记录硬门槛）

- 已覆盖资源：Image/Tag/Import/PixivToken/ProxyPool/ProxyEndpoint/TokenProxyBinding/HydrationRun/RequestLog/AdminAudit（共 10）
- 动作枚举证据（脱敏）：`docs/review/artifacts/2026-02-09_15-20-48/admin/adminjs-actions-from-redux-state.json`

> 未达标点（将列入 blocked）：`Image` 资源无记录，导致“每资源>=3条记录 + record actions 全触发”无法完成；其根因是“导入闭环断裂”（High）。

---

## 4. 审计基线摘要（我理解的“本质目标”）

从 `最初计划.txt` 与开发规划抽象出的“本质”：

1) 你已经能拿到大量 Pixiv 原图 URL（img-original）。系统要做的是：  
   - 批量导入 → 去重 → 入库（Image 表）  
   - 后台冷路径补全元数据（作者/标签/R18/宽高等）  
   - 这些元信息成为筛选与分类的基础  
2) 线上热路径应尽可能是：  
   - DB 过滤 + 随机挑选（稳定、快速）  
   - 返回图片流或 302 到稳定 URL（高并发/CDN 友好）  
3) 管理后台要能不停机完成：  
   - 导入/回滚/启停/补全/代理池维护/令牌刷新/审计追溯  
4) 必须可运维：  
   - 出错可解释、可恢复  
   - 队列/任务/失败原因可见  
   - 严格脱敏（refreshToken/密码 write-only）

本轮结论：当前线上版本距离“完美实现”差距主要集中在 **导入闭环（Image=0）**、**Admin actions 可用性**、**队列与动作可观测性**、**refreshToken 明文回显（安全）** 四个方面。

---

## 5. 问题清单（按严重级别）

> 每条问题的“证据链 + 代码定位 + 修复建议”见第 6 节。

### 5.1 High

- HIGH-001：**Image 库为空（Image=0）→ /random 永久 NO_MATCH，核心业务不可用**
- HIGH-002：**ImportUrls → Import 记录可创建但不产出 Image（导入闭环断裂/不可观测）**
- HIGH-003：PixivToken record action `testRefresh` 入队后 job 固定失败（`Invalid token_id`）
- HIGH-004：ProxyEndpoint record action `probe` 入队后 job 固定失败（`Invalid endpoint_id`）
- HIGH-005：多个 AdminJS resource actions（ProxyEndpoint/TokenProxyBinding/Image）点击进入“找不到网页”，UI 无法触发核心动作
- HIGH-006：AdminJobs 仅展示 2 个队列，导入/补全任务不可见，导致线上排障不可追溯
- HIGH-007：**安全严重缺陷：Admin API 在 PixivToken list/show 中回显 `refreshToken` 明文（len>0）**

### 5.2 Medium

- MED-001：`included_tags/excluded_tags` 多值策略不可用（重复 query 仅取第一个；逗号不拆分；仅支持 `|`）
- MED-002：legacy `/:illustId-:page.:ext` 强制 pageNumber>0（与 Pixiv `p0` 常见语义冲突）
- MED-003：`/metrics` 返回 404 `METRICS_PROTECTED`（策略可接受但需与文档/可观测性对齐）
- MED-004：`/version` commit=null，发布可追溯性不足（排障/回滚困难）

### 5.3 Low

- LOW-001：部分页面的“空态/异常态文案”与实际可恢复动作不匹配（容易误导）
- LOW-002：动作触发反馈语义不统一（有的入队成功但后续失败不提示，需要二次跳转查 AdminJobs）

---

## 6. 每个问题的证据链与代码定位（可复制复现 + 可执行修复）

> 约定：网络摘要只写 path/method/status，不落盘 cookie/Authorization。截图/Artifacts 已在第 1 节列出目录。

### HIGH-001：Image 库为空（Image=0）→ /random 永久 NO_MATCH

- 严重级别：High
- 影响：
  - 随机图片 API 完全不可用（所有请求 404/NO_MATCH）
  - 分类检索（/images、/authors）无意义
  - Admin 的 Image 相关 actions（hydrateMetadata）无法验证/无法运行
- 复现步骤：
  1. 打开 `https://i.mukyu.ru/admin/resources/Image`
  2. 观察列表显示 0 记录
  3. 请求 `GET https://i.mukyu.ru/random?format=json`
- URL：
  - `/admin/resources/Image`
  - `/random?format=json`
- 证据：
  - Admin：`docs/review/screenshots/2026-02-09_15-20-48/admin-0143-image-list-0-records.png`
  - API：`docs/review/artifacts/2026-02-09_15-20-48/api/random-json.body.txt`
- Network 摘要：
  - `GET /admin/api/resources/Image/actions/list` → 200（records_count=0）
  - `GET /random?format=json` → 404（`code=NO_MATCH`）
- Console 摘要：未见明显 console error（本轮 chrome MCP console 为空）
- 代码定位（数据根来源）：
  - Image 模型：`pixiv-反代/pixivcat-backend/prisma/schema.prisma:31`
  - /random 使用 Image 作为数据源：`pixiv-反代/pixivcat-backend/src/routes/random.ts:409` 起（从 query 解析 filters 并查库）
- 期望 vs 实际：
  - 期望：至少存在可随机挑选的 Image 数据，/random 在无筛选时应能返回 200（binary 或 json）。
  - 实际：Image=0，导致 /random 永久 NO_MATCH。
- 修复建议（可执行）：
  1. 先修 HIGH-002（导入闭环断裂），确保最少能创建 Image 记录。
  2. 为 `/admin/pages/importUrls` 增加“导入后 Image 增量验证”（例如导入完成后展示 `images_created` 计数）。
  3. 加一条健康检查：当 Image=0 时，在 Dashboard / opsNavigator 显示明确告警与引导（而不是让用户自己猜）。

### HIGH-002：ImportUrls → Import 可创建但不产出 Image（导入闭环断裂/不可观测）

- 严重级别：High
- 影响：
  - 你要求的“导入大量图片 URL → 元数据补全 → 分类 → 随机 API”的核心链路断裂
  - 导入看似成功（有 Import#24），但业务数据未生效，属于典型“假可用”
- 复现步骤（基于本轮已落盘）：
  1. 打开 `/admin/pages/importUrls`
  2. 粘贴多行 pixiv 原图 URL，点击 preview（可看到解析结果）
  3. 提交导入（创建 Import 记录，例如 #24）
  4. 打开 `/admin/resources/Image`，仍然 0 记录
- URL：
  - `/admin/pages/importUrls`
  - `/admin/resources/Import/records/24/show`（示例）
  - `/admin/resources/Image`
- 证据：
  - preview：`docs/review/screenshots/2026-02-09_15-20-48/admin-0072-importurls-preview.png`
  - Import#24：`docs/review/screenshots/2026-02-09_15-20-48/admin-0152-import-24-show.png`
  - Image 仍为 0：`docs/review/screenshots/2026-02-09_15-20-48/admin-0153-image-list-still-0-after-import-24.png`
  - Network preview（脱敏）：`docs/review/network/2026-02-09_15-20-48/admin-importurls-preview-req.txt`、`docs/review/network/2026-02-09_15-20-48/admin-importurls-preview-res.json`
- Network 摘要（关键）：
  - `POST /admin/images/import` → 200（创建 Import 记录并 enqueue jobId）
  - **缺失可追溯项**：无法从 AdminJobs 看见 `admin_images_import` 队列执行情况（见 HIGH-006）
- Console 摘要：未见明显 console error
- 代码定位：
  - 导入 API（创建 Import + 入队）：`pixiv-反代/pixivcat-backend/src/routes/adminImport.ts:475` 起（`enqueueAdminImagesImport`）
  - 导入队列/worker：`pixiv-反代/pixivcat-backend/src/jobs/importImages.ts:12`（队列名）与 `pixiv-反代/pixivcat-backend/src/jobs/importImages.ts:328`（worker 注册）
  - 应用启动时注册 worker：`pixiv-反代/pixivcat-backend/app.ts:91` 起
- 期望 vs 实际：
  - 期望：导入后 Image 记录数增加；Import 进度可追溯（成功/失败/最后错误/耗时）。
  - 实际：Import 记录存在，但 Image=0；且看不到导入 job 的执行状态。
- 修复建议（优先级最高）：
  1. **先补齐可观测性**：把导入 job 加入 AdminJobs（见 HIGH-006），或在 Import show 页面展示 job state（created/active/completed/failed）与 output_message（脱敏）。
  2. 在 `processAdminImagesImport` 写入 Image 后，回写 Import：`success/failed/deduped/enqueued_hydrate_metadata` 等（目前 UI 进度可能仅反映解析失败行）。
  3. 若 worker 实际未消费：检查 `DATABASE_URL`、pgboss schema 权限、以及 `app.ts` worker 注册是否在部署产物中执行（当前 `/version.commit=null` 增加排障难度，见 MED-004）。

### HIGH-003：PixivToken.testRefresh 入队后 job 固定失败（Invalid token_id）

- 严重级别：High
- 影响：
  - “refresh token → access token 刷新能力”不可用（无法验证/无法自愈）
  - 后续所有 Pixiv API 依赖链路不可信
- 复现步骤：
  1. 打开 `/admin/resources/PixivToken`
  2. 进入任意记录 show
  3. 触发 record action：`testRefresh`
  4. 打开 `/admin/pages/adminJobs`，选择队列 `admin_pixiv_token_test_refresh`
  5. 观察 job state=failed，输出 `Invalid token_id`
- URL：
  - `/admin/resources/PixivToken/records/<id>/show`
  - `/admin/pages/adminJobs`
- 证据：
  - 入队后的 PixivToken show：`docs/review/screenshots/2026-02-09_15-20-48/admin-0129-pixivtoken-1-show-after-testRefresh.png`
  - AdminJobs 失败：`docs/review/screenshots/2026-02-09_15-20-48/admin-0130-adminJobs-pixivToken-testRefresh-invalid-token-id.png`
- Network 摘要：
  - `POST /admin/api/resources/PixivToken/records/<id>/actions/testRefresh` → 200（notice: 已入队 test_refresh）
  - 随后 `AdminJobs` 查询到该 job state=failed（output_message=Invalid token_id）
- Console 摘要：无
- 代码定位：
  - 入队 handler：`pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:212`
  - 入队 payload：`pixiv-反代/pixivcat-backend/src/jobs/adminActions.ts:85`
  - worker 解析：`pixiv-反代/pixivcat-backend/src/jobs/adminActions.ts:117`（读取 job.data.token_id）+ `pixiv-反代/pixivcat-backend/src/jobs/adminActions.ts:35`（`toBigIntId` 抛 `Invalid token_id`）
- 期望 vs 实际：
  - 期望：job 成功后写入审计（ok/expires_in），失败则给出 Pixiv 返回状态码与可恢复建议。
  - 实际：固定在解析阶段失败，无法进入真实刷新逻辑。
- 修复建议（可执行）：
  1. 在 worker 中把 `tokenIdRaw` 的 **类型** 与 `JSON.stringify(job.data)` 的**脱敏摘要**写入 output（不要写 refreshToken），用于定位是否存在“隐藏字符/类型不一致/数据被序列化为字符串”等问题。
  2. 在 enqueue 处增加一致性校验：入队前将 token.id 强制转换为十进制字符串并验证 `/^[0-9]+$/`。
  3. 为 `adminActions.ts` 增加 integration test：模拟 pgboss job.data（string/number/bigint）三种形态，确保 `toBigIntId` 不误伤合法值。

### HIGH-004：ProxyEndpoint.probe 入队后 job 固定失败（Invalid endpoint_id）

- 严重级别：High
- 影响：
  - 代理探测与健康检查不可用，代理池策略无法自证正确
  - “失败回退/熔断/换代理”链路缺少基础数据支撑
- 复现步骤：
  1. 打开 `/admin/resources/ProxyEndpoint`
  2. 进入任意端点 show
  3. 触发 record action：`probe`
  4. 打开 `/admin/pages/adminJobs`，选择队列 `admin_proxy_endpoint_probe`
  5. 观察 job failed：`Invalid endpoint_id`
- 证据：`docs/review/screenshots/2026-02-09_15-20-48/admin-0134-adminJobs-proxy-endpoint-probe-invalid-endpoint-id.png`
- 代码定位：
  - 入队：`pixiv-反代/pixivcat-backend/src/admin/resources/proxyEndpoints.ts:513` 起（probe record action）
  - worker：`pixiv-反代/pixivcat-backend/src/jobs/adminActions.ts:180` 起（读取 endpoint_id 并 `toBigIntId`）
- 修复建议：同 HIGH-003（对 job.data 做脱敏类型诊断 + integration test），并补齐探测结果回写（成功/失败/latency/error）。

### HIGH-005：多个 AdminJS resource actions 点击进入“找不到网页”，UI 无法触发核心动作

- 严重级别：High
- 影响：
  - 代理开关/批量导入/绑定操作等“必须在后台完成”的能力，在资源页层面不可用
  - 用户体验为：按钮存在但点击报错，极易误判为权限或数据问题
- 复现（代表性）：
  - ProxyEndpoint：点击 `setProxyEnabled` / `importProxyUris` / `easyProxiesConfigSave` 等
  - TokenProxyBinding：点击 `rebindPrimary` / `setOverride` / `clearOverride`
  - Image：点击 `statusCounts`
- 证据（代表性截图）：
  - ProxyEndpoint：`docs/review/screenshots/2026-02-09_15-20-48/admin-0039-proxyendpoint-setProxyEnabled.png`
  - TokenProxyBinding：`docs/review/screenshots/2026-02-09_15-20-48/admin-0109-tokenproxybinding-rebindPrimary-not-found.png`
  - Image：`docs/review/screenshots/2026-02-09_15-20-48/admin-0144-image-statusCounts-action-not-found.png`
- 代码定位（共同特征：resource action 多为 `component:false`）：
  - ProxyEndpoint resource actions：`pixiv-反代/pixivcat-backend/src/admin/resources/proxyEndpoints.ts:60` 起
  - Image.statusCounts：`pixiv-反代/pixivcat-backend/src/admin/resources/images.ts:171` 起
  - TokenProxyBinding resource actions：`pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:1954` / `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2112` / `pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:2292`
- 期望 vs 实际：
  - 期望：点击动作 → 二次确认（如有）→ 执行 → notice + 状态变化 + 可追溯 jobId/结果。
  - 实际：点击进入“找不到网页”，动作无法触发（或只能通过自定义 Pages 间接触发）。
- 修复建议（建议一次性重构解决同类问题）：
  1. 将这些 resource actions 的 `component:false` 改为 `component:'RecordActionRunner'`（该组件已支持 resource/bulk/record 三类动作），并保留 guard 确认。  
     - 参考：`pixiv-反代/pixivcat-backend/src/admin/components/recordActionRunner.jsx:1`
  2. 或实现一个专用 `ResourceActionRunner`（但当前 RecordActionRunner 已足够）。
  3. 增加 admin-ui smoke test：逐个打开 `/admin/resources/<res>/actions/<action>` 并断言不出现 “NoActionError/找不到网页”。

### HIGH-006：AdminJobs 仅展示 2 个队列，导入/补全任务不可见（排障不可追溯）

- 严重级别：High
- 影响：
  - HIGH-002 无法定位（导入 job 是否入队/是否执行/为何失败）
  - hydration/hydrate_metadata/backfill 等关键队列同样不可见，导致“不可维护”
- 复现步骤：
  1. 打开 `/admin/pages/adminJobs`
  2. 观察队列下拉只包含 2 个值
- 证据：`docs/review/screenshots/2026-02-09_15-20-48/admin-0130-adminJobs-pixivToken-testRefresh-invalid-token-id.png`
- 代码定位：
  - 队列枚举仅返回 2 个：`pixiv-反代/pixivcat-backend/src/jobs/adminActions.ts:81`
  - AdminJobs handler 依赖该函数：`pixiv-反代/pixivcat-backend/src/admin/adminJs.ts:571`
- 修复建议：
  1. 扩展为“所有核心队列”：至少加入 `getAdminImportQueueNames()`（`pixiv-反代/pixivcat-backend/src/jobs/importImages.ts:68`）以及 hydrate/backfill 队列名（来自对应 job 文件）。
  2. AdminJobs 增加“按队列前缀/模糊搜索”与“显示 DLQ 数量/最近失败原因摘要”。
  3. Import/ HydrationRun 详情页直接显示关联 jobId 与 state/output_message（脱敏）。

### HIGH-007：安全严重缺陷：PixivToken list/show 回显 refreshToken 明文（len>0）

- 严重级别：High（安全）
- 影响：
  - refresh_token 属于高价值长期凭据；一旦被 Admin API 回显，任何拥有后台访问能力的人都可直接导出全部 token（即使 UI 隐藏）
  - 日志/抓包/浏览器扩展都可能意外泄露
- 复现步骤（脱敏验证方式）：
  1. 请求 `GET /admin/api/resources/PixivToken/actions/list`
  2. 或请求 `GET /admin/api/resources/PixivToken/records/1/show`
  3. 检查响应中 `record.params.refreshToken` 的存在性与长度（本轮仅记录 `len`，不记录明文）
- 证据（脱敏摘要）：`docs/review/artifacts/2026-02-09_15-20-48/admin/pixivtoken-refresh-token-leak.summary.json`
- Network 摘要：
  - `GET /admin/api/resources/PixivToken/actions/list` → 200（refreshToken_len>0）
  - `GET /admin/api/resources/PixivToken/records/1/show` → 200（refreshToken_len>0）
- 代码定位（根因很明确：未对 list/show 做 strip）：
  - strip 函数存在：`pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:21`
  - 但 actions 仅覆盖 new/edit/testRefresh/delete 等，**缺少 list/show after hook**：`pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:63`
- 修复建议（必须立即修复）：
  1. 为 `list` 与 `show` 增加 `after` hook：遍历 `response.records` 与 `response.record`，执行 `stripSensitiveFields`；并确保 edit GET 也强制置空（已做）。
  2. 增加单测（已经有 redaction 相关测试文件，可补齐）：断言所有 Admin API 响应里 `refreshToken` 不存在或为空。
  3. 建议加一层“全局响应脱敏”防漏：对所有资源的敏感字段（refreshToken/password）做统一 sanitize（避免未来新增 action 再次漏）。

### MED-001：included_tags/excluded_tags 多值策略不可用

- 严重级别：Medium
- 影响：筛选表达能力不足，无法满足“高度自定义范围请求”的关键诉求
- 证据（详见 API 契约审计）：`docs/review/2026-02-09_15-20-48-api-contract-audit.md`
- 代码定位：
  - `/random`：`pixiv-反代/pixivcat-backend/src/routes/random.ts:227`（`Array.isArray(value) ? value[0] : ...`）
  - `/images`：`pixiv-反代/pixivcat-backend/src/routes/images.ts:178`
- 修复建议：
  1. 支持三种输入：重复 query（`included_tags=a&included_tags=b`）、逗号分隔、`|` 分隔（保持兼容）。
  2. 文档明确优先级与去重规则，并在响应 `hints.applied_filters` 中回显最终解析结果。

### MED-002：legacy pageNumber 强制 >0（与 Pixiv p0 语义冲突）

- 严重级别：Medium
- 证据：`docs/review/2026-02-09_15-20-48-api-contract-audit.md`（`/123-0.jpg` → 400 `Invalid page number`）
- 代码定位：`pixiv-反代/pixivcat-backend/src/middlewares/validationMiddleware.ts:23`
- 修复建议：
  - 若要兼容 Pixiv `p0`：允许 pageNumber=0；或在路由层把 `-0` 映射为第 1 页（内部 0-based）。
  - 明确文档：该路由是历史兼容还是新标准。

### MED-003：/metrics 保护策略需对齐文档与可观测性

- 严重级别：Medium
- 证据：`docs/review/artifacts/2026-02-09_15-20-48/api/metrics.body.txt`（`METRICS_PROTECTED`）
- 修复建议：
  - 在 docs 中明确三态：disabled/protected/enabled，并给出推荐部署方案（默认 protected + 管理侧鉴权）。

### MED-004：/version commit=null，发布追溯性不足

- 严重级别：Medium
- 影响：线上出现 HIGH 类问题时，难以确认“当前跑的是哪次构建/是否已发布修复”
- 证据：`docs/review/artifacts/2026-02-09_15-20-48/api/version.body.txt`
- 代码定位：`pixiv-反代/pixivcat-backend/src/utils/buildInfo.ts:115`
- 修复建议：
  - 在构建/部署流程注入 `APP_COMMIT/APP_BUILD_TIME`，并在 `/healthz` 与 Admin Dashboard 明显展示。

### LOW-001：空态/异常态文案与可恢复动作不匹配（易误导）

- 严重级别：Low
- 影响：
  - 用户在“看起来可用”的后台里做完操作后，不知道下一步要去哪里验证（尤其导入/补全/随机 API 的闭环）。
  - 空态与异常态缺少“可恢复路径”，容易造成重复导入/误操作/长时间排障。
- 复现步骤（示例）：
  1. 打开 `/admin/resources/Image`（线上 Image=0），观察空态只显示“0 records/No records”，没有给出“先导入/看队列/看 Import”的下一步。
  2. 打开 `/admin/resources/Tag` 在无数据时同理（缺少“下一步做什么/如何恢复”的引导）。
  3. 触发一条不可达的 resource action（见 HIGH-005），页面展示“找不到网页”，但缺少返回/替代路径提示。
- URL：
  - `/admin/resources/Image`
  - `/admin/resources/Tag`
  - `/admin/resources/ProxyEndpoint/actions/importProxyUris`（示例）
- 证据：
  - `docs/review/screenshots/2026-02-09_15-20-48/admin-0143-image-list-0-records.png`
  - `docs/review/screenshots/2026-02-09_15-20-48/admin-0012-tag-list-empty.png`
  - `docs/review/screenshots/2026-02-09_15-20-48/admin-0125-proxyendpoint-importProxyUris-action-not-found.png`
- Network 摘要：无（主要是引导/文案与“可恢复路径”缺失）
- Console 摘要：未见明显 console error
- 代码定位（修复点建议放在“导航入口”，而不是依赖 AdminJS 默认空态）：
  - Dashboard 已有 images 统计，可在 `images.total===0` 时渲染“闭环告警 + 下一步链接”：`pixiv-反代/pixivcat-backend/src/admin/pages/dashboard.jsx:88`、`pixiv-反代/pixivcat-backend/src/admin/pages/dashboard.jsx:161`
  - opsNavigator 是固定入口，建议注入动态运行态（例如 Image=0/最近导入失败/队列不可用）：`pixiv-反代/pixivcat-backend/src/admin/pages/opsNavigator.jsx:55`、`pixiv-反代/pixivcat-backend/src/admin/pages/opsNavigator.jsx:74`
- 期望 vs 实际：
  - 期望：空态/异常态要“可解释 + 可恢复”，至少给出下一步跳转（importUrls/import 记录/adminJobs/补全面板）。
  - 实际：大量页面只给出“空/404”，用户需要自行猜测工作流。
- 修复建议（可执行）：
  1. Dashboard 顶部增加“闭环验收面板”：Image>0、最近导入成功、最近 hydrate 成功、最近 random 200/302、队列可用性（红/黄/绿 + 下一步链接）。
  2. opsNavigator 对每个 group 展示当前关键计数与 blocked 原因（例如 Image=0 → “先导入并确认 Image 增长”）。
  3. 对 action-not-found 的页面增加明确文案：该 action 未注册 UI 路由（开发缺口），并提供“返回资源页/去 Pages 触发/查看 AdminJobs”的替代路径。

### LOW-002：动作反馈语义不统一（入队成功但失败无直观提示）

- 严重级别：Low
- 影响：
  - 许多后台动作是“异步入队”，但 UI 反馈仅靠短暂 notice/toast；失败需要用户自行去 AdminJobs 翻找，体验割裂。
  - 动作与 job 之间缺少稳定关联（例如点击后没有“查看本次 job”的固定入口），导致排障成本高。
- 复现步骤（示例）：
  1. 在 PixivToken show 页点击 `测试刷新`（record action）。
  2. 返回 show 页后看不到 job 状态；必须打开 `/admin/pages/adminJobs` 才能看到失败原因（本轮为 `Invalid token_id`）。
- URL：
  - `/admin/resources/PixivToken/records/<id>/show`
  - `/admin/pages/adminJobs`
- 证据：
  - AdminJobs 失败：`docs/review/screenshots/2026-02-09_15-20-48/admin-0130-adminJobs-pixivToken-testRefresh-invalid-token-id.png`
  - AdminJobs 重试仍失败：`docs/review/screenshots/2026-02-09_15-20-48/admin-0131-adminJobs-retry-still-invalid-token-id.png`
- Network 摘要：
  - `POST /admin/api/resources/PixivToken/records/<id>/actions/testRefresh` → 200（notice: 已入队 test_refresh）
  - 后续 job 失败只能在 `/admin/pages/adminJobs` 中看到 output_message
- Console 摘要：未见明显 console error
- 代码定位（“动作→job→可追溯 UI”链路缺口）：
  - record action 返回的是“文本 notice”，缺少结构化 job 元数据：`pixiv-反代/pixivcat-backend/src/admin/resources/pixivTokens.ts:309`
  - ProxyEndpoint.probe 同类：`pixiv-反代/pixivcat-backend/src/admin/resources/proxyEndpoints.ts:613`
  - 前端 `RecordActionRunner` 只展示 notice/redirectUrl，不展示 jobId/队列/跳转 AdminJobs：`pixiv-反代/pixivcat-backend/src/admin/components/recordActionRunner.jsx:71`
- 期望 vs 实际：
  - 期望：异步动作返回后应提供“可追溯入口”（查看本次 job、重试、复制 jobId），并在失败时能回到发起处可见。
  - 实际：动作成功入队与最终失败之间缺少桥梁，需要人工跳转排查。
- 修复建议（可执行）：
  1. 所有 enqueue 型 action 返回结构化字段（例如 `job: { id, queue }`），避免只把 jobId 拼进 message 字符串。
  2. `RecordActionRunner` 在收到 `job` 字段时，显示“查看 AdminJobs（带 queue/jobId 预填）”链接，并在页面内保留 lastResult（避免 toast 消失即丢失上下文）。
  3. AdminJobs 增加 jobId 搜索框（或支持 query param 自动筛选），让“从动作跳转到 job”成为一键路径。

---

## 7. “必须立即修复”Top 10（按业务影响排序）

1) 修复导入闭环（HIGH-002）：确保导入后 Image 增长，/random 能 200（这是“项目可用”的起点）
2) 修复 PixivToken refreshToken 明文回显（HIGH-007）：这是安全红线
3) 修复 Admin resource actions UI（HIGH-005）：让后台按钮真正可执行（建议统一用 `RecordActionRunner`）
4) 修复 adminActions worker `Invalid token_id/endpoint_id`（HIGH-003/004）：否则 token 刷新/代理探测不可用
5) 扩展 AdminJobs 覆盖所有核心队列（HIGH-006）：导入/补全/回滚必须可观测
6) 在 Import 详情页展示 job 状态/最后错误/重试入口：把排障从“猜”变为“看得见”
7) 让 Image.hydrateMetadata 可运行（依赖 Image 有数据）：补全链路闭环，验证元数据写入与 tags/authors 分类
8) 修复 tags 多值解析（MED-001）：满足“高度自定义筛选”的核心诉求
9) 修复 legacy pageNumber 语义（MED-002）：减少用户侧迁移成本/误解
10) 补齐 build traceability（MED-004）：为后续大改动提供可回滚、可比对的基础

---

## 8. 可维护性 / 扩展性 / 健壮性风险（面向“大刀阔斧重构”）

### 8.1 “假可用”风险（当前已发生）

- 表现：后台页面可打开、按钮可见、导入看似成功（有 Import 记录），但业务核心（Image 数据、/random）不可用。
- 建议：引入“闭环验收面板”（Dashboard 上用红/黄/绿显示：Image>0、最近导入成功、最近 hydrate 成功、最近 random 200、队列 backlog 等）。

### 8.2 AdminJS 动作体系的结构性风险

- 当前：同一能力同时存在于 Pages 与 Resources，但资源页 actions 不可用，页面却可用（逻辑分裂）。
- 建议：
  - 统一动作触发机制：所有自定义 action 使用同一 runner（RecordActionRunner），避免 component=false 导致不可达。
  - 明确职责：Pages 负责“聚合/批量/引导”，Resources 负责“单实体 CRUD + action”，两者不要互相替代。

### 8.3 队列与任务可观测性不足

- 当前：AdminJobs 只看得到 2 个队列，导入/补全属于黑盒。
- 建议：
  - 所有后台任务必须可追溯：jobId 写回业务表（Import/HydrationRun），并提供“重试/取消/查看最近错误”入口。

### 8.4 安全红线（refreshToken/password write-only）

- 当前：refreshToken 明文回显（已证据）。
- 建议：
  - 对敏感字段采用“强制删字段”而非仅靠 UI isVisible。
  - 增加自动化审计测试（CI）阻止回归。

---

## 9. blocked 项（真实受限项，不伪造）

- BLOCKED-001：无法完成 Image 资源“>=3 条记录 + hydrateMetadata record action”深测  
  - 原因：线上 Image=0（HIGH-001/002），无记录可操作。
- BLOCKED-002：无法验证 /random 的 200/302 真阳性行为（返回图片或重定向到 `/i/:id.:ext`）  
  - 原因：同上（无 Image 数据）。

---

## 10. 总结：当前版本是否达到“最初计划的完美实现”标准？

结论：**未达到**。

依据（最短证据链）：
- “随机图片 API”的前置条件是 Image 库可用，但线上 `Image=0`，导致 `/random` 永久 `NO_MATCH`（HIGH-001）。
- “热更新导入”是核心能力，但导入闭环断裂且不可观测（HIGH-002 + HIGH-006）。
- “令牌刷新/代理探测”是核心支撑能力，但 record action job 固定失败（HIGH-003/004）。
- “安全要求”明确 refreshToken write-only，但 Admin API 明文回显 refreshToken（HIGH-007）。

建议的验收门槛（修复后再宣称“可用”）：
1) 导入 100+ URL → Image 增长可见；/random 200/302 ≥ 99%（失败自动换图重试）
2) 后台所有关键 action 可在 UI 中执行，并能追溯 jobId/状态/最后错误
3) refreshToken/password 绝不回显（API/日志/审计）并有 CI 测试兜底
```

</details>

<details>
<summary>附录J：easy_proxies README_ZH（原文备份）</summary>

`md
# Easy Proxies

[English](README.md) | 简体中文

基于 [sing-box](https://github.com/SagerNet/sing-box) 的代理节点池管理工具，支持多协议、多节点自动故障转移和负载均衡。

## 特性

### 核心功能
- **多协议支持**: VMess、VLESS、Hysteria2 (hy2://)、Shadowsocks、Trojan
- **多种传输层**: TCP、WebSocket、HTTP/2、gRPC、HTTPUpgrade
- **订阅链接支持**: 自动从订阅链接获取节点，支持 Base64、Clash YAML 等格式
- **订阅定时刷新**: 自动定时刷新订阅，支持 WebUI 手动触发（⚠️ 刷新会导致连接中断）
- **节点池模式**: 自动故障转移、负载均衡
  - **GeoIP 地域路由** ⭐（可选功能）: 通过 URL 路径访问特定地域的节点池
    - `/jp` - 日本节点，`/kr` - 韩国节点，`/us` - 美国节点等
    - 首次启动自动下载 GeoIP 数据库
    - 自动定期更新（可配置间隔，默认 24 小时）
    - 热重载，无需服务中断
- **多端口模式**: 每个节点独立监听端口
- **混合模式**: 同时启用节点池 + 多端口，节点状态共享同步

### 管理与监控
- **Web 监控面板**: 实时查看节点状态、延迟探测、一键导出节点
- **WebUI 设置**: 无需编辑配置文件即可修改 external_ip 和 probe_target
- **自动健康检查**: 启动时自动检测所有节点可用性，定期（5分钟）检查节点状态
- **智能节点过滤**: 自动过滤不可用节点，WebUI 和导出按延迟排序
- **端口保留**: 添加/更新节点时，已有节点保持原有端口不变

### 安全与性能（新增！）
- **增强会话管理**: 安全的会话令牌，自动过期和清理机制
- **时序攻击防护**: 恒定时间密码比较，防止暴力破解攻击
- **并发控制**: 基于信号量的 goroutine 限制，防止资源耗尽
- **文件锁定**: 使用 syscall.Flock 确保配置文件并发写入安全
- **解析优化**: 订阅内容解析速度提升 50-70%
- **HTTP 连接池**: 高效的连接复用，减少 TIME_WAIT 连接
- **优雅关闭**: 正确的连接排空机制，可配置超时时间

### 部署
- **灵活配置**: 支持配置文件、节点文件、订阅链接多种方式
- **多架构支持**: Docker 镜像同时支持 AMD64 和 ARM64
- **密码保护**: WebUI 支持密码认证，安全的会话管理

## 快速开始

### 1. 配置

复制示例配置文件：

```bash
cp config.example.yaml config.yaml
cp nodes.example nodes.txt
```

编辑 `config.yaml` 配置监听地址和认证信息，编辑 `nodes.txt` 添加代理节点。

### 2. 运行

**Docker 方式（推荐）：**

```bash
./start.sh
```

或手动执行：

```bash
docker compose up -d
```

**本地编译运行：**

```bash
go build -tags "with_utls with_quic with_grpc" -o easy-proxies ./cmd/easy_proxies
./easy-proxies --config config.yaml
```

## 配置说明

### 基础配置

```yaml
mode: pool                    # 运行模式: pool (节点池)、multi-port (多端口) 或 hybrid (混合)
log_level: info               # 日志级别: debug, info, warn, error
external_ip: ""               # 外部 IP 地址，用于导出时替换 0.0.0.0（Docker 部署时建议配置）

# 订阅链接（可选，支持多个）
subscriptions:
  - "https://example.com/subscribe"

# 管理接口
management:
  enabled: true
  listen: 0.0.0.0:9090        # Web 监控面板地址
  probe_target: www.apple.com:80  # 延迟探测目标
  password: ""                # WebUI 访问密码，为空则不需要密码（可选）

# 统一入口监听
listener:
  address: 0.0.0.0
  port: 2323
  username: username
  password: password

# 节点池配置
pool:
  mode: sequential            # sequential (顺序) 或 random (随机)
  failure_threshold: 3        # 失败阈值，超过后拉黑节点
  blacklist_duration: 24h     # 拉黑时长

# 多端口模式
multi_port:
  address: 0.0.0.0
  base_port: 24000            # 起始端口，节点依次递增
  username: mpuser
  password: mppass
```

### 运行模式详解

#### Pool 模式（节点池）

所有节点共享一个入口地址，程序自动选择可用节点：

```yaml
mode: pool

listener:
  address: 0.0.0.0
  port: 2323
  username: user
  password: pass

pool:
  mode: sequential  # sequential (顺序) 或 random (随机)
  failure_threshold: 3
  blacklist_duration: 24h
```

**适用场景：** 自动故障转移、负载均衡

**使用方式：** 配置代理为 `http://user:pass@localhost:2323`

#### Multi-Port 模式（多端口）

每个节点独立监听一个端口，精确控制使用哪个节点：

**配置格式：** 支持两种写法

```yaml
mode: multi-port  # 推荐：连字符格式
# 或
mode: multi_port  # 兼容：下划线格式
```

**完整配置示例：**

```yaml
mode: multi-port

multi_port:
  address: 0.0.0.0
  base_port: 24000  # 端口从这里开始自动递增
  username: user
  password: pass

# 使用 nodes_file 简化配置
nodes_file: nodes.txt
```

**启动时输出：**

```
📡 Proxy Links:
═══════════════════════════════════════════════════════════════
🔌 Multi-Port Mode (3 nodes):

   [24000] 台湾节点
       http://user:pass@0.0.0.0:24000
   [24001] 香港节点
       http://user:pass@0.0.0.0:24001
   [24002] 美国节点
       http://user:pass@0.0.0.0:24002
═══════════════════════════════════════════════════════════════
```

**适用场景：** 需要指定特定节点、测试节点性能

**使用方式：** 每个节点有独立的代理地址，可精确选择

#### Hybrid 模式（混合模式）

同时启用节点池和多端口模式，两者共享节点状态：

```yaml
mode: hybrid

listener:
  address: 0.0.0.0
  port: 2323           # 节点池入口
  username: user
  password: pass

multi_port:
  address: 0.0.0.0
  base_port: 24000     # 多端口起始端口
  username: mpuser
  password: mppass

pool:
  mode: balance        # sequential (顺序)、random (随机) 或 balance (负载均衡)
  failure_threshold: 3
  blacklist_duration: 24h
```

**启动时输出：**

```
📡 Proxy Links:
═══════════════════════════════════════════════════════════════
🌐 Pool Entry Point:
   http://user:pass@0.0.0.0:2323

   Nodes in pool (3):
   • 台湾节点
   • 香港节点
   • 美国节点

🔌 Multi-Port Entry Points (3 nodes):

   [24000] 台湾节点
       http://mpuser:mppass@0.0.0.0:24000
   [24001] 香港节点
       http://mpuser:mppass@0.0.0.0:24001
   [24002] 美国节点
       http://mpuser:mppass@0.0.0.0:24002
═══════════════════════════════════════════════════════════════
```

**核心特性：**

- **状态共享**: 节点黑名单状态在节点池和多端口之间同步
  - 节点池中某节点失败被拉黑，多端口模式也会同步标记为不可用
  - 健康检查结果同时更新两种模式
- **端口自动重分配**: 如果端口被占用，自动分配下一个可用端口
- **灵活访问**: 节点池用于负载均衡，多端口用于直连特定节点

**适用场景：** 既需要自动故障转移，又需要直连特定节点

### 节点配置

**方式 1: 使用订阅链接（推荐）**

支持从订阅链接自动获取节点，支持多种格式：

```yaml
subscriptions:
  - "https://example.com/subscribe/v2ray"
  - "https://example.com/subscribe/clash"
```

支持的订阅格式：
- **Base64 编码**: V2Ray 标准订阅格式
- **Clash YAML**: Clash 配置文件格式
- **纯文本**: 每行一个节点 URI

**方式 2: 使用节点文件**

在 `config.yaml` 中指定：

```yaml
nodes_file: nodes.txt
```

`nodes.txt` 每行一个节点 URI：

```
vless://uuid@server:443?security=reality&sni=example.com#节点名称
hysteria2://password@server:443?sni=example.com#HY2节点
ss://base64@server:8388#SS节点
trojan://password@server:443?sni=example.com#Trojan节点
vmess://base64...#VMess节点
```

**方式 3: 直接在配置文件中**

```yaml
nodes:
  - uri: "vless://uuid@server:443#节点1"
  - name: custom-name
    uri: "ss://base64@server:8388"
    port: 24001  # 可选，手动指定端口
```

> **提示**: 可以同时使用多种方式，节点会自动合并。

## 支持的协议

| 协议 | URI 格式 | 特性 |
|------|----------|------|
| VMess | `vmess://` | WebSocket、HTTP/2、gRPC、TLS |
| VLESS | `vless://` | Reality、XTLS-Vision、多传输层 |
| Hysteria2 | `hysteria2://` 或 `hy2://` | 带宽控制、混淆 |
| Shadowsocks | `ss://` | 多加密方式 |
| Trojan | `trojan://` | TLS、多传输层 |

### VMess 参数

VMess 支持两种 URI 格式：

**格式一：Base64 JSON（标准格式）**
```
vmess://base64({"v":"2","ps":"名称","add":"server","port":443,"id":"uuid","aid":0,"scy":"auto","net":"ws","type":"","host":"example.com","path":"/path","tls":"tls","sni":"example.com"})
```

**格式二：URL 格式**
```
vmess://uuid@server:port?encryption=auto&security=tls&sni=example.com&type=ws&host=example.com&path=/path#名称
```

- `net/type`: tcp, ws, h2, grpc
- `tls/security`: tls 或空
- `scy/encryption`: auto, aes-128-gcm, chacha20-poly1305 等

### VLESS 参数

```
vless://uuid@server:port?encryption=none&security=reality&sni=example.com&fp=chrome&pbk=xxx&sid=xxx&type=tcp&flow=xtls-rprx-vision#名称
```

- `security`: none, tls, reality
- `type`: tcp, ws, http, grpc, httpupgrade
- `flow`: xtls-rprx-vision (仅 TCP)
- `fp`: 指纹 (chrome, firefox, safari 等)

### Hysteria2 参数

```
hysteria2://password@server:port?sni=example.com&insecure=0&obfs=salamander&obfs-password=xxx#名称
# 或使用简写
hy2://password@server:port?sni=example.com&insecure=0&obfs=salamander&obfs-password=xxx#名称
```

- `upMbps` / `downMbps`: 带宽限制
- `obfs`: 混淆类型
- `obfs-password`: 混淆密码

## Web 监控面板

访问 `http://localhost:9090` 查看：

- 节点状态（健康/警告/异常/拉黑）
- 实时延迟
- 活跃连接数
- 失败次数统计
- 手动探测延迟
- 解除节点拉黑
- **一键导出节点**: 导出所有可用节点的代理池 URI（格式：`http://user:pass@host:port`）
- **设置**: 点击齿轮图标修改 `external_ip` 和 `probe_target`（立即保存生效）

### WebUI 设置

点击页面顶部的 ⚙️ 齿轮图标进入设置：

| 设置项 | 说明 |
|--------|------|
| 外部 IP 地址 | 导出节点时使用的 IP 地址（替换 `0.0.0.0`） |
| 探测目标 | 健康检查目标地址（格式：`host:port`） |

修改后立即保存到 `config.yaml`，无需重启即可生效。

### 节点管理

Web UI 提供**节点管理** Tab 页，支持节点的增删改查操作：

- **添加节点**: 通过 URI 添加新节点（名称自动从 URI fragment 提取）
- **编辑节点**: 修改现有节点配置
- **删除节点**: 从配置中移除节点
- **重载配置**: 重启 sing-box 内核使更改生效（⚠️ 会中断现有连接）
- **端口保留**: 重载后已有节点保持原有端口不变

Multi-Port 模式下，端口从 `base_port` 自动分配。

**API 端点：**

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/nodes/config` | 获取所有配置节点 |
| POST | `/api/nodes/config` | 添加新节点 |
| PUT | `/api/nodes/config/:name` | 按名称更新节点 |
| DELETE | `/api/nodes/config/:name` | 按名称删除节点 |
| POST | `/api/reload` | 重载配置 |
| GET | `/api/settings` | 获取当前设置 |
| PUT | `/api/settings` | 更新设置（external_ip, probe_target） |

**请求示例：**

```bash
# 添加节点
curl -X POST http://localhost:9090/api/nodes/config \
  -H "Content-Type: application/json" \
  -d '{"uri": "vless://uuid@server:443#节点名称"}'

# 删除节点
curl -X DELETE http://localhost:9090/api/nodes/config/节点名称

# 重载配置
curl -X POST http://localhost:9090/api/reload
```

### 健康检查机制

程序启动时会自动对所有节点进行健康检查，之后定期检查：

- **初始检查**: 启动后立即检测所有节点的连通性
- **定期检查**: 每 5 分钟检查一次所有节点状态
- **智能过滤**: 不可用节点自动从 WebUI 和导出列表中隐藏
- **探测目标**: 通过 `management.probe_target` 配置（默认 `www.apple.com:80`）

```yaml
management:
  enabled: true
  listen: 0.0.0.0:9090
  probe_target: www.apple.com:80  # 健康检查探测目标
```

### 密码保护

为了保护节点信息安全，可以为 WebUI 设置访问密码：

```yaml
management:
  enabled: true
  listen: 0.0.0.0:9090
  password: "your_secure_password"  # 设置 WebUI 访问密码
```

- 如果 `password` 为空或不设置，则无需密码即可访问
- 设置密码后，首次访问会弹出登录界面
- 登录成功后，session 会保存 7 天

### 订阅定时刷新

支持定时自动刷新订阅链接，获取最新节点：

```yaml
subscription_refresh:
  enabled: true                 # 启用定时刷新
  interval: 1h                  # 刷新间隔（默认 1 小时）
  timeout: 30s                  # 获取订阅超时
  health_check_timeout: 60s     # 新节点健康检查超时
  drain_timeout: 30s            # 旧实例排空超时
  min_available_nodes: 1        # 最少可用节点数，低于此值不切换
```

> ⚠️ **重要提示：订阅刷新会导致连接中断**
>
> 订阅刷新时，程序会**重启 sing-box 内核**以加载新节点配置。这意味着：
>
> - **所有现有连接将被断开**
> - 正在进行的下载、流媒体播放等会中断
> - 客户端需要重新建立连接
>
> **建议：**
> - 将刷新间隔设置为较长时间（如 `1h` 或更长）
> - 避免在业务高峰期手动触发刷新
> - 如果对连接稳定性要求极高，建议关闭此功能（`enabled: false`）

**WebUI 和 API 支持：**

- WebUI 显示订阅状态（节点数、上次刷新时间、错误信息）
- 支持手动触发刷新按钮
- API 端点：
  - `GET /api/subscription/status` - 获取订阅状态
  - `POST /api/subscription/refresh` - 手动触发刷新

## 端口说明

| 端口 | 用途 |
|------|------|
| 2323 | 统一代理入口（节点池/混合模式） |
| 9090 | Web 监控面板 |
| 24000+ | 每节点独立端口（多端口/混合模式） |

## Docker 部署

**方式一：主机网络模式（推荐）**

使用 `network_mode: host` 直接使用主机网络，无需手动映射端口：

```yaml
# docker-compose.yml
services:
  easy-proxies:
    image: ghcr.io/jasonwong1991/easy_proxies:latest
    container_name: easy-proxies
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./config.yaml:/etc/easy-proxies/config.yaml
      - ./nodes.txt:/etc/easy-proxies/nodes.txt
```

> **注意**: 配置文件需要可写权限以支持 WebUI 设置保存。如遇权限问题，请执行 `chmod 666 config.yaml nodes.txt`

> **优点**: 容器直接使用主机网络，所有端口自动对外开放。端口自动重分配功能可完美工作。

**方式二：端口映射模式**

手动指定需要映射的端口：

```yaml
# docker-compose.yml
services:
  easy-proxies:
    image: ghcr.io/jasonwong1991/easy_proxies:latest
    container_name: easy-proxies
    restart: unless-stopped
    ports:
      - "2323:2323"       # 节点池/混合模式入口
      - "9091:9091"       # Web 监控面板
      - "24000-24200:24000-24200"  # 多端口/混合模式
    volumes:
      - ./config.yaml:/etc/easy-proxies/config.yaml
      - ./nodes.txt:/etc/easy-proxies/nodes.txt
```

> **注意**: 多端口和混合模式需要映射足够的端口范围，建议预留一些缓冲端口用于自动重分配。

## 构建

```bash
# 基础构建
go build -o easy-proxies ./cmd/easy_proxies

# 完整功能构建
go build -tags "with_utls with_quic with_grpc with_wireguard with_gvisor" -o easy-proxies ./cmd/easy_proxies
```

## 更新日志

### v1.1.0 (2026-02-02) - GeoIP、安全与性能版本

**🌍 GeoIP 功能（仅节点池模式）：**
- ⭐ **基于地域的节点池路由**（可选功能）
  - 通过 URL 路径访问特定地域的节点池：`/jp`、`/kr`、`/us`、`/hk`、`/tw` 等
  - 节点池模式下自动识别所有节点的 IP 地理位置
  - Dashboard 显示各地域节点数量
- ⭐ **自动 GeoIP 数据库管理**
  - 首次启动自动从 GitHub 下载（约 9MB）
  - 定期自动更新（可配置间隔，默认 24 小时）
  - 热重载，无需服务中断
  - MMDB 格式验证和完整性检查
- ⭐ **hy2:// 协议支持**
  - 支持 Hysteria2 简写形式（hy2://）
  - 向后兼容 hysteria2://

**🔒 安全增强：**
- 增强的会话管理，支持自动过期（24小时 TTL）和每小时清理
- 恒定时间密码比较，防止时序攻击
- 基于信号量的并发控制（CPU×4 个 goroutine，最少 10 个）
- 文件锁定机制，确保配置文件并发写入安全

**⚡ 性能改进：**
- 订阅内容解析速度提升 50-70%，优化 base64 检测算法
- HTTP 连接池（最大空闲连接 100，每主机 10）减少 TIME_WAIT 连接
- 响应大小限制（10MB）防止内存耗尽
- 优雅关闭机制，30秒超时和2秒连接排空

**🔧 技术细节：**
- 新增自动 GeoIP 数据库下载和更新机制
- 实现 GeoIP 数据库热重载功能
- 新增 `golang.org/x/sync/semaphore` 用于并发控制
- 实现 `syscall.Flock` Unix 文件锁定
- 配置自定义 HTTP transport 和优化的超时设置
- 无破坏性变更 - 完全向后兼容

**📝 升级说明：**
- GeoIP 是节点池模式的可选功能（默认禁用）
- 启用后 GeoIP 数据库将自动下载
- 升级后现有会话将失效（用户需要重新登录）
- 无需修改配置文件
- 建议在低流量时段重启服务

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jasonwong1991/easy_proxies&type=Date)](https://star-history.com/#jasonwong1991/easy_proxies&Date)

## 许可证

MIT License
```

</details>
