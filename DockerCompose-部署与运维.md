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
deploy/.env.example
data/app.db
```

运行/验证（本仓库）：

```bash
docker compose -f deploy/docker-compose.yml config
docker compose -f deploy/docker-compose.yml up -d --build
```

> 说明：`deploy/docker-compose.yml` 挂载 `../data:/app/data`（相对 compose 文件目录 `deploy/`），因此 DB 文件在宿主机是 `data/app.db`。

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
      - "8000:8000"
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
- `FIELD_ENCRYPTION_KEY`：用于加密 refresh_token 与 proxy 密码（Fernet 32 urlsafe base64）

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

### 4.5 imgproxy（可选；生产强烈建议开启签名）
- `IMGPROXY_BASE_URL=http://imgproxy:8080`（你的 imgproxy 服务地址）
- `IMGPROXY_KEY=...`（hex；必须）
- `IMGPROXY_SALT=...`（hex；必须）
- `IMGPROXY_MAX_DIM=2048`（可选；默认 2048）
- `IMGPROXY_DEFAULT_OPTIONS=rs:fit:2048:2048`（可选；默认按 MAX_DIM 生成）
- `IMGPROXY_URL_CHUNK_SIZE=16`（可选；默认 16）

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
