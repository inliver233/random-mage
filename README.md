# Random Mage（Pixiv 随机图 API）

一个自建图库的随机图片 API：支持强筛选（R18/AI/作品类型/横竖图/分辨率/热度/标签 AND/OR 等），同时提供稳定的图片代理路径（便于 CDN 缓存）与公开展示页（/docs、/status、/wtf）。

## 快速入口

- 使用说明（公开）：`/docs`
- 状态仪表盘（公开）：`/status`（机器可读：`/status.json`）
- 瀑布流（公开）：`/wtf`（参数与 `/random` 一致）
- Swagger：`/api/docs`（OpenAPI：`/openapi.json`）

## 常用用法

直接出图：

```text
/random
/random?r18=1
/random?orientation=portrait
/random?adaptive=1
```

JSON（用于调试/信息展示）：

```text
/random?format=simple_json
/random?format=json
```

标签 AND / OR：

- AND：重复参数（`included_tags=a&included_tags=b`）
- OR：同一参数内用 `|`（`included_tags=a|b`，`|` 也可写 `%7C`）

例：

```text
/random?included_tags=girl|boy&included_tags=white|black
```

## 图片上游镜像（第三方/自建反代）

服务端拉取原图时，可把 `i.pximg.net` 替换为第三方/自建镜像域名（客户端仍访问本站 `/i/...`，不会跳到第三方域名）。

### 1) 全局开关（管理端）

在「系统设置 → 图片加速」开启后：

- 大陆访问优先使用 `i.pixiv.re`
- 非大陆默认使用你选择的镜像（默认 `i.pixiv.cat`）

### 2) 单次请求强制（公开参数 `proxy=`）

`proxy=` 优先级最高：会隐式开启第三方镜像（等价于 `pixiv_cat=1`），并覆盖地区自动选择。

内置写法示例：

```text
/random?proxy=i-pixiv-cat
/random?proxy=re
/i/123.jpg?proxy=cat
```

自建镜像：

1) 在「系统设置 → 图片加速 → 自定义镜像白名单」中添加你的域名（例如 `i.mirror.example.com`）
2) 请求时传 `proxy=i.mirror.example.com`

```text
/random?proxy=i.mirror.example.com
```

## 管理端导入

在管理端「导入 URL」支持两种文件：

- `.txt`：每行一个图片 URL（可选导入后补全，获取更完整元数据/标签）
- `PixivBatchDownloader` 导出的 `.json`：会自动提取图片链接，并尽可能填充已有元数据/标签；不依赖 refresh token 也可正常使用（不会强制触发补全）

## 部署

参考 `deploy/docker-compose.yml` 与 `deploy/.env.example`。

