# Pixiv 插画元数据调研（App API `illust/detail`）

本文目的：
- 明确本项目通过 Pixiv App API 实际能拿到哪些“可用于判断图片质量”的元数据字段。
- 给出字段 → 数据库 → 接口输出 的映射，作为后续“高质量随机策略”的数据依据。

> 注意：Pixiv 并未提供稳定的官方公开文档；这里以常见开源客户端/抓包结果为依据。字段命名在不同客户端可能会有 **snake_case（JSON）** 与 **camelCase（语言模型）** 的差异，但语义一致。

## 1) 获取途径

### 1.1 Endpoint
- URL：`https://app-api.pixiv.net/v1/illust/detail`
- Query：`illust_id=<id>&filter=for_android`
- 认证：OAuth Bearer（本项目通过 refresh_token 换取 access_token）

本项目实现位置：
- 获取：`backend/app/jobs/handlers/hydrate_metadata.py`
- URL 常量：`PIXIV_ILLUST_DETAIL_URL`

### 1.2 返回结构（概览）
响应为 JSON object，核心字段为：
- `illust`: object（插画主体）
  - `id`
  - `width/height`
  - `x_restrict`（R18 标记，NULL 代表未知）
  - `illust_ai_type`（AI 标记）
  - `user`
  - `tags`
  - `meta_single_page` / `meta_pages`（原图 URL）
  - **热度字段**：`total_bookmarks` / `total_view` / `total_comments`

## 2) 与“质量”强相关字段

### 2.1 热度（优先）
- `total_bookmarks`：收藏数（本项目的主质量信号）
- `total_view`：浏览数（辅助信号）
- `total_comments`：评论数（辅助信号）

> “点赞”说明：Pixiv 存在点赞能力（官方帮助中心亦有说明），但在 App API 的 illust 对象中更稳定、可直接使用的公开数值字段通常是上述三项。本项目将以 `total_bookmarks` 作为“点赞/喜爱/收藏”的主要代理指标，并保留 view/comments 作为辅助特征。

衍生指标（项目内部计算，不是 Pixiv 原始字段）：
- `bookmark_rate`：收藏率（`bookmark_count / max(1, view_count)`，或按千分比缩放）。用于“质量随机 v2”中降低对纯浏览量的偏置。

### 2.2 清晰度/观感（辅助）
- `width` / `height`：分辨率
- `page_count`：页数（多图作品）

### 2.3 标签（内容语义）
- `tags`: array
  - `name`：原始标签
  - `translated_name`：翻译（可能为空）

## 3) 与本项目数据库的映射

### 3.1 images 表（页级记录）
由 `hydrate_metadata` 持久化：
- `width`, `height`, `aspect_ratio`, `orientation`
- `x_restrict`
- `ai_type`（来自 `illust_ai_type`）
- `user_id`, `user_name`
- `title`
- `created_at_pixiv`（来自 `create_date`，归一化到 UTC 秒）
- `bookmark_count` ← `total_bookmarks`
- `view_count` ← `total_view`
- `comment_count` ← `total_comments`

### 3.2 tags / image_tags
由 `hydrate_metadata` 持久化：
- `tags.name` ← tag.name
- `tags.translated_name` ← tag.translated_name
- `image_tags`：多对多关系

## 4) 接口输出映射（关键）

### 4.1 Public API
- `GET /images`、`GET /images/{id}`：输出热度字段（bookmark/view/comment）用于验证与外部消费
- `GET /random?format=json`：建议输出热度字段 + debug(quality_score 等)，便于解释“为什么更常抽到这类图”

### 4.2 Admin API
- `GET /admin/api/summary`：建议输出 `counts.hydration.missing.popularity`（热度字段缺失数）
- `GET /admin/api/images`：建议支持 `missing=popularity` 并展示 bookmark/view/comment 三字段

## 5) 参考资料（联网调研）

以下仅用于证明字段存在/语义一致（不是完整文档）：
- pixivpy wiki 的插画对象示例包含 `total_view/total_bookmarks`（抓包/模拟 App API）
  - https://github.com/upbit/pixivpy/wiki/zh_cn/%E6%8D%95%E8%8E%B7%E6%96%B0API
- Go 客户端 struct 定义包含 `total_view/total_bookmarks/total_comments`
  - https://pkg.go.dev/github.com/everpcpc/pixiv#Illust
- TS 客户端类型定义直接展示 `x_restrict`、`meta_single_page.original_image_url`、`meta_pages[].image_urls.original` 与 `total_view/total_bookmarks/total_comments`
  - https://github.com/Moestash/pixiv.ts/blob/master/README.md
- TS 客户端接口定义包含 `totalView/totalBookmarks/totalComments`
  - https://github.com/akameco/pixiv-app-api
- 官方帮助中心：点赞功能说明（用于说明“点赞存在”，但字段以 bookmarks 等为主）
  - https://www.pixiv.help/hc/en-us/articles/235584268-Liking-works
- OAuth 刷新鉴权头（`X-Client-Time`/`X-Client-Hash`）说明（用于证明本项目 refresh 实现方式的依据）
  - https://errorism.dev/posts/pixiv-api/
