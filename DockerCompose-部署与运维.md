# Docker Compose 部署与运维 Runbook

> 目标：你在一台低配云服务器上也能稳定部署、升级、回滚。  
> 本文给出推荐 compose 拓扑、环境变量、备份策略、升级流程、以及常见故障排查。

---

## 1. 推荐拓扑（2 服务起步）

最小可用：
- `api`：FastAPI（对外提供 public/admin API）
- `worker`：后台任务（hydrate/heal/import/probe）

可选：
- `web`：React 静态站（nginx），或由 api 直接托管
- `caddy/nginx`：公网反代、TLS、基本防护

---

## 2. 目录与卷（强烈建议）

### 2.1 本仓库默认布局（开发/自托管示例）

> 下面的路径以仓库根目录为基准（即 `new-pixiv-api实现/`）。

```text
deploy/docker-compose.yml
deploy/.env (copy from .env.example)
data/app.db
```

运行/验证（本仓库）：

```bash
cd deploy
docker compose config
docker compose up -d --build
```

> 说明：`deploy/docker-compose.yml` 挂载 `../data:/app/data`（相对 compose 文件目录 `deploy/`），因此 DB 文件在宿主机是 `data/app.db`。

运行成功后（默认端口 `23222`）：
- 管理后台（React）：`http://<你的IP>:23222/admin`（登录页：`/admin/login`）
- Swagger：`http://<你的IP>:23222/docs`
- 健康检查：`http://<你的IP>:23222/healthz`

> 本仓库的 Docker 镜像会在 build 时打包前端产物，并由 `api` 服务在 `/admin` 下直接托管；默认无需额外 `web` 服务。

### 2.3 常用 Docker Compose 指令速查（建议收藏）

> 下面以本仓库示例 `deploy/docker-compose.yml` 为准（也可以先 `cd deploy` 再省略 `-f`）。

启动/更新（推荐；会重建镜像）：
```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

查看运行状态：
```bash
docker compose -f deploy/docker-compose.yml ps
```

查看日志（跟随）：
```bash
docker compose -f deploy/docker-compose.yml logs -f api
docker compose -f deploy/docker-compose.yml logs -f worker
```

重启服务（不重建镜像）：
```bash
docker compose -f deploy/docker-compose.yml restart api worker
```

停止服务（保留容器，稍后可 `start` 恢复）：
```bash
docker compose -f deploy/docker-compose.yml stop
```

下线/清理（移除容器与网络；不会删除宿主机 `data/`）：
```bash
docker compose -f deploy/docker-compose.yml down
```

强制重建（建议升级代码后使用；可同时拉取上游 base 镜像）：
```bash
docker compose -f deploy/docker-compose.yml build --pull
docker compose -f deploy/docker-compose.yml up -d --force-recreate
```

> 重要提醒：如果你更新了代码但后台页面还是旧的，通常是因为**没有重建镜像**（前端静态资源在镜像构建阶段打包）。请使用 `docker compose up -d --build`。

### 2.2 生产建议布局（示例）

宿主机目录（示例）：
```text
/opt/new-pixiv-api/
  docker-compose.yml
  .env
  data/          # SQLite DB、cache、运行态文件
  backups/       # 自动备份
  logs/          # 若做文件日志（推荐仍以 stdout 为主）
```

compose 中挂载：
- `./data:/data`
- `./backups:/backups`（可选）

---

## 3. 示例 docker-compose.yml（草案）

本仓库已提供一个可直接运行的 compose：`deploy/docker-compose.yml`（用于开发/自托管示例）。

下方示例更偏“生产模板”（你可以按需改造到自己的 `/opt/...` 目录）：

```yaml
services:
  api:
    image: new-pixiv-api:latest
    restart: unless-stopped
    environment:
      APP_ENV: prod
      DATABASE_URL: sqlite+aiosqlite:////data/app.db
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}
      PROXY_ENABLED: "true"
      PROXY_FAIL_CLOSED: "true"
    volumes:
      - ./data:/data
    ports:
      - "23222:8000"
    command: ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]

  worker:
    image: new-pixiv-api:latest
    restart: unless-stopped
    environment:
      APP_ENV: prod
      DATABASE_URL: sqlite+aiosqlite:////data/app.db
      SECRET_KEY: ${SECRET_KEY}
      FIELD_ENCRYPTION_KEY: ${FIELD_ENCRYPTION_KEY}
    volumes:
      - ./data:/data
    command: ["python","-m","app.worker"]
```

说明：
- `api` 与 `worker` 共用同一个 SQLite 文件。必须启用 WAL + busy_timeout + 应用层重试。
- 生产建议：在 api 前面加 Nginx/Caddy 做 TLS 与限流（尤其 admin）。

---

## 4. 环境变量清单（生产必须填）

### 4.1 安全
- `SECRET_KEY`：用于 JWT/session（长度>=32，随机）
- `FIELD_ENCRYPTION_KEY`：用于加密 refresh_token 与 proxy 密码（Fernet 32 urlsafe base64；生产必须设置）
- `FIELD_ENCRYPTION_KEY_FILE`：可选；从文件读取 Fernet key（例如挂载 Secret 到容器），优先级低于 `FIELD_ENCRYPTION_KEY`
  - 开发环境（`APP_ENV=dev`）若两者都未设置，会自动生成并写入 `./data/field_encryption_key`
- `PIXIV_OAUTH_CLIENT_ID` / `PIXIV_OAUTH_CLIENT_SECRET` / `PIXIV_OAUTH_HASH_SECRET`：用于 Pixiv OAuth 刷新与 App API
  - 开发环境（`APP_ENV=dev`）若为空，后端会使用 Pixiv Android App 默认值

### 4.2 数据库
- `DATABASE_URL=sqlite+aiosqlite:////data/app.db`

### 4.3 代理与出站策略
- `PROXY_ENABLED=true|false`
- `PROXY_FAIL_CLOSED=true|false`
- `PROXY_ROUTE_MODE=pixiv_only|all|allowlist`
- `PROXY_ROUTE_ALLOWLIST_DOMAINS=...`（逗号分隔）

### 4.4 easy_proxies（可选）
- `EASY_PROXIES_BASE_URL=http://easy-proxies:9090`
- `EASY_PROXIES_PASSWORD=***`
- `EASY_PROXIES_AUTO_REFRESH=true`
- `EASY_PROXIES_REFRESH_INTERVAL_MS=1800000`
- `EASY_PROXIES_AUTO_ATTACH=true`（默认 true；导入后自动加入代理池）
- `EASY_PROXIES_ATTACH_POOL_ID=1`（可选；不填则自动选第一个启用的代理池）
- `EASY_PROXIES_ATTACH_WEIGHT=1`（可选；默认 1）
- `EASY_PROXIES_AUTO_RECOMPUTE_BINDINGS=true`（默认 true；导入后自动重算 token↔proxy 绑定）
- `EASY_PROXIES_MAX_TOKENS_PER_PROXY=2`（可选；默认 2）
- `EASY_PROXIES_BINDINGS_STRICT=false`（可选；默认 false；更稳健，不因容量不足而失败）
- `EASY_PROXIES_HOST_OVERRIDE=152.53.91.30`（可选；当导出 host 是 `0.0.0.0/127.0.0.1/localhost` 等占位符时，用于强制指定可连接的 host；不填则默认使用 `EASY_PROXIES_BASE_URL` 的 host）

### 4.5 imgproxy（可选；生产强烈建议开启签名）
- `IMGPROXY_BASE_URL=http://imgproxy:8080`（你的 imgproxy 服务地址）
- `IMGPROXY_KEY=...`（hex；必须）
- `IMGPROXY_SALT=...`（hex；必须）
- `IMGPROXY_MAX_DIM=2048`（可选；默认 2048）
- `IMGPROXY_DEFAULT_OPTIONS=rs:fit:2048:2048`（可选；默认按 MAX_DIM 生成）
- `IMGPROXY_URL_CHUNK_SIZE=16`（可选；默认 16）

### 4.6 Public API Key（可选；对外部署强烈建议开启）
- `PUBLIC_API_KEY_REQUIRED=true|false`（默认 false）
- `PUBLIC_API_KEY_RPM=60`（默认 0=不启用限流；按 API key 维度）
- `PUBLIC_API_KEY_BURST=60`（默认 0=自动用 RPM 作为 burst）

---

## 5. 备份与升级（必须写成 SOP）

### 5.1 备份（SQLite）

推荐方式 A（离线，最安全）：
1) 停服务（本仓库示例）：
   - `docker compose -f deploy/docker-compose.yml stop api worker`
2) 备份 DB 文件（建议连同 WAL/SHM 一起备份）：
   - Linux/macOS：`cp -a data/app.db* backups/`
   - Windows/PowerShell：
     - `New-Item -ItemType Directory -Force -Path backups | Out-Null`
     - `Copy-Item -Path data/app.db* -Destination backups -Force`
3) 启动服务：
   - `docker compose -f deploy/docker-compose.yml up -d --build`

推荐方式 B（在线备份；容器镜像默认不包含 `sqlite3` CLI，使用 Python 的 sqlite3.backup）：
```bash
docker compose -f deploy/docker-compose.yml exec -T api python - <<'PY'
import os
import sqlite3
import time

ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
src = "/app/data/app.db"
dst_dir = "/app/data/backups"
dst = f"{dst_dir}/app.db.{ts}"

os.makedirs(dst_dir, exist_ok=True)

with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print("backup_ok", dst)
PY
```

### 5.2 升级流程（建议）
1) 备份 DB
2) 拉取/构建新镜像（本仓库示例为本地 build）：
   - `docker compose -f deploy/docker-compose.yml build --pull`
3) 运行迁移：
   - `docker compose -f deploy/docker-compose.yml run --rm api alembic upgrade head`
4) 重启：
   - `docker compose -f deploy/docker-compose.yml up -d --force-recreate`
5) Smoke 验收：
   - `GET /healthz` 200
   - `GET /version` 返回新 commit
   - `GET /random?format=json` 返回 NO_MATCH 或 OK（至少不 500）

### 5.3 回滚流程
1) stop
   - `docker compose -f deploy/docker-compose.yml stop api worker`
2) 恢复备份 DB（优先恢复备份，而不是尝试 downgrade）：
   - 复制备份文件覆盖 `data/app.db*`
3) 使用旧代码/旧镜像启动：
   - `docker compose -f deploy/docker-compose.yml up -d --build`

### 5.4 request_logs 清理（可选）

`request_logs` 用于请求观测，长期运行可能增长较快。建议在低峰期按需清理。

管理端提供一个维护接口（需要 admin 鉴权）：
- `POST /admin/api/maintenance/request-logs/cleanup`

示例（dry-run）：
```bash
curl -X POST http://127.0.0.1:23222/admin/api/maintenance/request-logs/cleanup \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"keep_days":30,"max_delete_rows":50000,"chunk_size":1000,"dry_run":true}'
```

执行清理：
```bash
curl -X POST http://127.0.0.1:23222/admin/api/maintenance/request-logs/cleanup \
  -H "Authorization: Bearer <admin_jwt>" \
  -H "Content-Type: application/json" \
  -d '{"keep_days":30,"max_delete_rows":50000,"chunk_size":1000}'
```

> 说明：删除记录不会立刻缩小 SQLite 文件体积；如需收缩文件体积，建议通过“备份-恢复”方式（见 5.1），或在停机窗口执行 `VACUUM`。

---

## 6. 生产反代建议（强烈建议）

### 6.1 管理后台不要裸奔
- `/admin/*` 只允许内网或加额外认证（basic auth / IP allowlist）
- `/metrics` 默认也应保护

### 6.2 CDN 缓存策略
- `/i/*`：长缓存（1y）
- legacy：长缓存
- `/random`：no-store

---

## 7. 常见故障排查

### 7.1 `database is locked`
- 确认 WAL 已启用
- 增大 busy_timeout
- 降低 worker 并发
- 缩短写事务（批量写入分 chunk）

### 7.1.1 外网访问 `HTTP 502`，但服务器内 `curl http://127.0.0.1:23222/healthz` 正常
优先排查顺序：
1) 云厂商安全组/防火墙：确认入站已放行 `23222/tcp`（UFW 放行不等于安全组放行）
2) 客户端代理/网络：关闭系统代理（如 Clash/V2Ray 等）或把 `154.17.18.187:23222` 加入直连列表
3) 自检响应来源：在服务器上执行 `curl -i http://<公网IP>:23222/healthz`，看响应头是否包含 `server: uvicorn`

### 7.2 /random 总是 NO_MATCH
- Images=0：先导入
- 强筛选过严：降低 min_*、移除 tags
- 元信息缺失：跑 backfill hydrate

### 7.3 代理 fail-closed 导致全部失败
- 没有健康 proxy：先导入 proxy 并 probe
- easy_proxies base_url 不通：检查容器网络与端口

### 7.4 token 全部 backoff
- refresh_token 失效：重新获取 token
- 代理质量差导致刷新失败：先修 proxy
