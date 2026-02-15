# REV-0300 全量 Review（可运营/可管理/默认行为一致）

创建时间：2026-02-15

## 1. 需求摘要（来自 `要求.txt`）
- 能批量导入大量图片 URL，并写入数据库形成可随机的图片库。
- 使用 token 池 + 代理池，从 Pixiv 获取并持久化更多元数据（tags/作者/R18/AI/热度等）。
- 设计更高质量的随机：默认更偏向高收藏/高清图，而不是纯随机。
- 所有常用操作尽量在前端完成（启动/停止/补全/探测/绑定/设置），docker compose 启动后无需手工操作后台。

## 2. 当前实现概览（本地审查）

### 2.1 导入闭环（Import → DB → 随机）
- Admin 端点：`POST /admin/api/imports`（json/multipart，支持 dry_run preview）。
- 导入以 job 形式执行（可 inline 或 worker 执行），ImportDetail 页面会提示“worker 未启动会导致 success=0”。
- URL 解析目前只接受 pximg 原图链接：`*.pximg.net/<illustId>_p<page>.<ext>`（这不是 bug，是已知限制）。

### 2.2 元数据补全（HydrateMetadata）
- 通过 Pixiv App API：`https://app-api.pixiv.net/v1/illust/detail?illust_id=...&filter=for_android`。
- 可持久化：tags/作者/R18/AI/分辨率/热度（收藏/浏览/评论）。
- 支持 backfill run（创建/暂停/恢复/取消）与单图补全，且后台可看到“缺失覆盖率”统计。

### 2.3 Token 池 / 代理池 / 绑定
- Token：支持新增、测试刷新、失败退避计数重置；refresh_token 写入不回显。
- Proxy：支持手工导入与 easy-proxies 导入；支持 probe 探测 job；池与成员权重可配置。
- Bindings：后端已支持 recompute + override + clear-override，但前端目前只提供 recompute 与列表展示。

### 2.4 高质量随机（Tournament Selection）
- `/random` 默认 quality 策略：抽样 N 个候选，按 “收藏为主 + 分辨率/浏览/评论为辅” 评分取最优。
- 支持 `strategy=random|quality` 与 `quality_samples=N` 覆盖；JSON debug 可观察 picked_by/score/sources。

## 3. 发现的问题/改进点（本批次要做）

> 这些会映射到 `issues/2026-02-15_15-37-17-full-review-hardening.csv` 的 issue。

### 3.1 `/random` 默认值与 Settings 不一致（高优先级）
- Settings 已提供 random.defaults（attempts/r18_strict/fail_cooldown/strategy/samples），但 `/random` 部分默认值仍硬编码或读取 env。
- 影响：用户在设置页修改后，调用 `/random` 仍可能表现不一致，造成“设置不生效”的困惑。
- 对应 Issue：`RND-0301`

### 3.2 Tokens 管理缺少编辑/启停/权重调整（高优先级）
- 目前仅支持新增/测试刷新/重置失败计数，缺少更新接口与 UI。
- 影响：运营期无法热调整（例如临时停用一个 token 或调整权重）。
- 对应 Issue：`TOK-0302`

### 3.3 Proxy 节点缺少启停操作 + 无密码导入不应依赖加密密钥（高优先级）
- 目前没有 endpoint 级别的启停接口与 UI。
- proxy 导入接口当前会在一开始就要求 FIELD_ENCRYPTION_KEY，即使导入的代理没有密码也会 500（体验不佳，容易被误认为“系统坏了”）。
- 对应 Issue：`PRX-0303`

### 3.4 Bindings 前端缺少 override/clear 操作（中高优先级）
- 后端已支持 override，但前端没有可操作入口。
- 影响：用户难以“手动让某 token 换节点/临时切换线路”。
- 对应 Issue：`BND-0304`

### 3.5 导入页面缺少“错误行/预览”可见性与格式说明（中优先级）
- 导入结果目前主要给汇总数，错误细节隐藏在 detail JSON，容易产生“看着多但进去没图”的误解。
- 需要在 UI 直接展示：支持的 URL 格式说明 + preview + 错误行（前 N 条）。
- 对应 Issue：`IMP-0305`

## 4. 联网依据（关键字段与鉴权）
- 作品详情字段（`total_bookmarks/total_view/total_comments`，以及原图 URL 的 meta_single_page/meta_pages）在开源 TS/Go 客户端类型定义中可见。
- OAuth refresh 需要 `X-Client-Time`/`X-Client-Hash` 的常见实现方式有公开说明；本项目按此实现。
- 已将引用补齐到：`docs/research/pixiv-illust-metadata.md`

## 5. 回归策略
- 每条 issue 按 CSV 的 Test_Method 跑：backend pytest + frontend vitest/typecheck。
- 批次末统一把 Regression_Status 标记 DONE 并提交 meta commit。
