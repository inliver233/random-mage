# 高质量随机策略 v2（加入收藏率）

目标：
- 在保持现有“抽样 + 评分”（Tournament Selection）性能特征不变的前提下，让默认 `GET /random` 更大概率返回**高质量**图片。
- 在 v1 基础上，降低对“纯浏览量”的偏置：避免“浏览很高但收藏率很低”的作品被过度选中。

## 1) v1 的局限

v1 的质量评分里包含 `view_count`（浏览数）作为辅助信号，但在某些数据分布下：
- 浏览数可能更容易被外部曝光/传播放大；
- 仅看浏览数容易把“热但不一定好看”的作品排到更前。

因此 v2 引入“收藏率（bookmark/view）”作为补充信号：更偏向**既有收藏、且收藏/浏览比例更高**的作品。

## 2) 评分公式（v2）

依旧使用 `log1p(x)=ln(1+x)` 压缩数量级差异，避免极端热门作品完全垄断。

定义：
- `pixels = max(0,width) * max(0,height)`
- `bookmark_rate_per_mille = 1000 * bookmark_count / view_count`（仅当 `view_count>0` 时计算，否则该项为 0）

推荐公式（v2）：

```text
score =
  4.0 * log1p(bookmark_count) +
  0.5 * log1p(view_count) +
  2.0 * log1p(comment_count) +
  1.0 * log1p(pixels / 1_000_000) +
  3.0 * log1p(bookmark_rate_per_mille)
```

说明：
- `bookmark_count` 仍是主信号（权重最高）。
- `view_count` 权重下调（从 v1 的 1.0 → 0.5），并由收藏率项补足“质量判断”。
- 收藏率项用“千分比”缩放（per mille），让数值在常见范围内更稳定。

## 3) 可观测性（debug）

`/random?format=json` 中：
- `image.bookmark_count/view_count/comment_count` 用于验证元数据是否覆盖；
- `debug.quality_score` 用于解释本次为何选中该图（分数更高）。

## 4) 与补全系统的关系

收藏率依赖 `bookmark_count` 与 `view_count`：
- 冷启动阶段字段缺失会让评分更接近 0，质量策略会退化。
- 建议优先进行 `missing=popularity` 的 backfill，提升覆盖率。

