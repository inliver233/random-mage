# API 契约（详细版）— Public API / Admin API / 错误码

> 本文是 `new随机api开发文档.md` 的接口细化补充。  
> 约定：所有 JSON 接口默认 `Content-Type: application/json; charset=utf-8`，并返回 `request_id` 便于追踪。

---

## 1. 通用约定

### 1.1 Request-ID

后端对每个请求生成 `request_id`（UUID 或短 ID），并：
- 响应头：`X-Request-Id: <id>`
- JSON body：`request_id: <id>`（若为 JSON 响应）

### 1.2 错误响应（统一结构）

所有 JSON 错误返回：

```json
{
  "ok": false,
  "code": "BAD_REQUEST",
  "message": "Human readable message",
  "request_id": "req_...",
  "details": {}
}
```

说明：
- `code` 必须稳定（用于前端与监控规则）。
- `details` 可选（用于指出哪一项参数/哪一行输入错误）。

### 1.3 分页（cursor-based）

列表接口统一返回：

```json
{
  "ok": true,
  "items": [],
  "next_cursor": "12345",
  "request_id": "req_..."
}
```

约定：
- `cursor` 为空表示从头开始。
- `next_cursor` 为空表示没有更多。
- 默认排序：`id DESC`（稳定，适合增量扫描）。

### 1.4 多值参数编码（tags）

支持两种：
1) 管道分隔：`included_tags=tag1|tag2`
2) 重复 query：`included_tags=tag1&included_tags=tag2`

后端需要统一解析为数组。

---

## 2. Public API（对外）

### 2.1 `GET /random`

用途：随机返回一张图片（默认流式）或 JSON，支持强筛选。

Query：
- `format`: `image|json|simple_json`（默认 image）
- `redirect`: `0|1`（默认 0；为 1 时返回 302 Location `/i/{id}.{ext}`）
- `attempts`: `1..10`（默认 3）
- `seed`: string（可选；可复现随机）

筛选：
- `r18`: `0|1|2`（默认 0）
- `r18_strict`: `0|1`（默认 1；当 r18=0 且 strict=1 时，不允许 x_restrict=NULL）
- `orientation`: `portrait|landscape|square|any`
- `min_width`, `min_height`, `min_pixels`: `0..2147483647`
- `included_tags`, `excluded_tags`: 多值
- `user_id`, `illust_id`: 正整数
- `ai_type`: `0|1|any`
- `created_from`, `created_to`: ISO 日期/时间（UTC）

响应模式：

1) `format=image`（默认）
- 成功：`200` + 图片流
- 头：`Cache-Control: no-store`
- 头：`X-Origin-URL`（可选：由配置决定是否输出）
- 失败：`404`（NO_MATCH）或 `502`（连续 attempts 失败）

2) `format=json`

成功示例：
```json
{
  "ok": true,
  "code": "OK",
  "request_id": "req_...",
  "data": {
    "image": {
      "id": "123",
      "illust_id": "118437245",
      "page_index": 0,
      "ext": "jpg",
      "width": 2480,
      "height": 3508,
      "x_restrict": 0,
      "ai_type": 0,
      "user": { "id": "999", "name": "author" },
      "title": "title",
      "created_at_pixiv": "2024-05-05T00:47:58Z"
    },
    "tags": ["tag1", "tag2"],
    "urls": {
      "proxy": "/i/123.jpg",
      "origin": "https://i.pximg.net/img-original/...",
      "legacy_single": "/118437245.jpg",
      "legacy_multi": "/118437245-1.jpg"
    },
    "debug": {
      "attempts_used": 1,
      "picked_by": "random_key"
    }
  }
}
```

无匹配：
```json
{
  "ok": false,
  "code": "NO_MATCH",
  "message": "No matching image.",
  "request_id": "req_...",
  "details": {
    "hints": {
      "applied_filters": { "r18": 0, "orientation": "portrait" },
      "suggestions": [
        "run hydration backfill to improve metadata coverage",
        "relax included_tags",
        "lower min_width/min_height/min_pixels"
      ]
    }
  }
}
```

3) `redirect=1`
- 成功：`302 Location: /i/{id}.{ext}`
- 失败：`404`

### 2.2 `GET /i/{image_id}.{ext}`

用途：稳定图片 URL（建议供 CDN 缓存）。

规则：
- `image_id` 必须为正整数
- `ext` 必须与 DB 一致，否则 404

成功：
- `200` 图片流
- `Cache-Control: max-age=31536000, public`
- `Content-Disposition: filename="..."`（来源于 originUrl basename）

失败：
- `404` image 不存在或 ext 不匹配
- `404/502` 上游失败（同时写入 image.fail_count/last_error_code，并可触发 heal job）

### 2.3 `GET /images`

用途：图片列表检索（用于外部调用方做自定义筛选，或给前端用）。

Query：
- `limit`: `1..200`（默认 50）
- `cursor`: string（可选）
- 支持 `/random` 同款筛选参数（r18/orientation/min_*/tags/user_id/illust_id/ai_type/time）

返回：
```json
{
  "ok": true,
  "items": [{ "id": "1", "illust_id": "..." }],
  "next_cursor": "123",
  "request_id": "req_..."
}
```

### 2.4 `GET /images/{id}`

用途：单图元信息（含 tags）。

返回：
```json
{
  "ok": true,
  "item": {
    "image": { },
    "tags": ["..."]
  },
  "request_id": "req_..."
}
```

### 2.5 `GET /tags`

用途：标签检索。

Query：
- `q`: string（可选）
- `limit`: `1..100`
- `cursor`

建议返回包含计数：
- `count_images`（可选：通过聚合或物化）

### 2.6 `GET /authors`

用途：作者检索（按 user_id 聚合）。

Query：
- `q`（匹配 user_name）
- `limit` `cursor`

返回 item：
- `user_id`
- `user_name`
- `count_images`

### 2.7 legacy（兼容路由）

#### `GET /{illust_id}.{ext}`
#### `GET /{illust_id}-{page}.{ext}`

行为：
- 优先从 DB 查 `images.original_url`（避免打 Pixiv API）
- 如果 DB 无记录，可配置是否允许回落 Pixiv API（默认不建议；但为了兼容可选）

缓存：
- `Cache-Control: max-age=31536000, public`

---

## 3. Admin API（管理端，仅管理员）

> 前缀：`/admin/api`  
> 鉴权：`Authorization: Bearer <admin_jwt>` 或 HttpOnly session cookie（二选一，最终实现择其一）。

### 3.1 Auth

#### `POST /admin/api/login`
Body：
```json
{ "username": "admin", "password": "..." }
```
返回：
```json
{ "ok": true, "token": "...", "request_id": "..." }
```

#### `POST /admin/api/logout`
清 session/cookie。

### 3.2 Imports

#### `POST /admin/api/imports`
支持两种内容类型：
- `application/json`：`{ "text": "...", "dry_run": false, "hydrate_on_import": true, "source": "manual" }`
- `multipart/form-data`：上传文件 `file`（txt），同样参数

返回（创建 import + 入队 job）：
```json
{
  "ok": true,
  "import_id": "10",
  "job_id": "999",
  "accepted": 1000,
  "deduped": 200,
  "errors": [{ "line": 12, "url": "...", "code": "unsupported_url", "message": "..." }],
  "request_id": "req_..."
}
```

#### `GET /admin/api/imports/{id}`
返回 import 详情 + 进度 + 关联 job（可选）。

#### `POST /admin/api/imports/{id}/rollback`
Body：
```json
{ "mode": "disable" }  // or delete
```

### 3.3 Tokens

#### `GET /admin/api/tokens`
列表（refresh_token 不回显）。

#### `POST /admin/api/tokens`
Body：
```json
{ "label": "acc1", "refresh_token": "...", "enabled": true, "weight": 1.0 }
```

#### `POST /admin/api/tokens/{id}/test-refresh`
触发刷新测试 job，返回 expires_in 或错误。

#### `POST /admin/api/tokens/{id}/reset-failures`
清 backoff/error_count。

### 3.4 Proxies

#### `GET /admin/api/proxies/endpoints`

#### `POST /admin/api/proxies/endpoints/import`
Body：
```json
{ "text": "http://a:b@1.2.3.4:2323\nsocks5://...", "source": "manual", "conflict_policy": "overwrite" }
```

#### `POST /admin/api/proxies/easy-proxies/import`
Body：
```json
{ "base_url": "http://easy-proxies:9090", "password": "***", "conflict_policy": "skip_non_easy_proxies" }
```

#### `POST /admin/api/proxies/probe`
触发全量健康探测（异步 job）。

### 3.5 Proxy Pools

#### `GET /admin/api/proxy-pools`
#### `POST /admin/api/proxy-pools`
#### `PUT /admin/api/proxy-pools/{id}`
#### `POST /admin/api/proxy-pools/{id}/endpoints`
更新池包含的 endpoints（带 weight/enabled）。

### 3.6 Bindings

#### `GET /admin/api/bindings?pool_id=...`
列出 token↔proxy 的 primary/override。

#### `POST /admin/api/bindings/recompute`
Body：`{ "pool_id": 1, "max_tokens_per_proxy": 2 }`

#### `POST /admin/api/bindings/{id}/override`
Body：`{ "override_proxy_id": 10, "ttl_ms": 1200000, "reason": "manual_override" }`

#### `POST /admin/api/bindings/{id}/clear-override`

### 3.7 Hydration & Jobs

#### `POST /admin/api/hydration-runs`
创建 backfill（criteria：缺 tags/缺 geometry/缺 r18 等）。

#### `POST /admin/api/hydration-runs/{id}/pause|resume|cancel`

#### `GET /admin/api/jobs?status=&type=&cursor=`
#### `POST /admin/api/jobs/{id}/retry|cancel|move-to-dlq`

### 3.8 Settings

#### `GET /admin/api/settings`
#### `PUT /admin/api/settings`

必须支持的 key（示例）：
- `proxy.enabled`
- `proxy.fail_closed`
- `proxy.route_mode`
- `random.defaults`
- `security.hide_origin_url_in_public_json`
- `rate_limit.*`

---

## 4. 错误码字典（必须稳定）

### 4.1 通用
- `BAD_REQUEST`
- `UNAUTHORIZED`
- `FORBIDDEN`
- `NOT_FOUND`
- `INTERNAL_ERROR`

### 4.2 Random
- `NO_MATCH`
- `UPSTREAM_STREAM_ERROR`
- `UPSTREAM_403`
- `UPSTREAM_404`
- `UPSTREAM_RATE_LIMIT`

### 4.3 Import
- `INVALID_UPLOAD_TYPE`
- `PAYLOAD_TOO_LARGE`
- `UNSUPPORTED_URL`

### 4.4 Pixiv/Token
- `TOKEN_REFRESH_FAILED`
- `TOKEN_BACKOFF`
- `NO_TOKEN_AVAILABLE`

### 4.5 Proxy
- `PROXY_REQUIRED`（fail-closed 且无可用 proxy）
- `PROXY_AUTH_FAILED`
- `PROXY_CONNECT_FAILED`

