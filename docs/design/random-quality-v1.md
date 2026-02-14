# 高质量随机策略 v1（Tournament Selection）

目标：
- 让 `GET /random` 在“用户不传任何筛选参数”的情况下，更大概率返回高质量图片（更受欢迎、清晰度更高）。
- 维持随机接口热路径性能：只读 SQLite，避免全表扫描与重排序。

## 1) 为什么不用“直接按收藏数排序随机”

在 SQLite 中，如果每次请求都做：
- `ORDER BY bookmark_count DESC, random() LIMIT 1`

会导致：
- 大表场景性能不可控（`ORDER BY`/`random()` 往往需要扫描与排序）
- 过滤条件叠加（tags/user_id/分辨率等）后更容易退化

因此采用“抽样 + 评分”的近似加权方式。

## 2) Tournament Selection（最佳 N 选 1）

策略：
1. 先用现有 `random_key` 索引机制，从满足筛选条件的集合里抽 `N` 张**互不重复**的候选。
2. 对每张候选计算 `quality_score`。
3. 返回分数最高的一张。

性质（直觉）：
- `N` 越大，返回的图片越接近“高分分位”；`N=1` 时退化为纯随机。
- 不改变“候选来自同一筛选集合”的约束，因此 `r18/orientation/tags/...` 等依旧生效。

默认值建议：
- `strategy=quality`
- `quality_samples=5`

## 3) 质量评分（Quality Score）

输入特征：
- 主信号：`bookmark_count`
- 辅信号：`view_count`、`comment_count`、`width*height`

缩放与权重：
- 使用 `log1p(x)`（即 `ln(1+x)`）压缩数量级差异，避免极端热门作品完全垄断。
- 缺失字段按 0 处理（缺失会降低被选中概率，推动补全覆盖率提升）。

推荐公式（v1）：

```
score =
  4.0 * log1p(bookmark_count) +
  1.0 * log1p(view_count) +
  2.0 * log1p(comment_count) +
  1.0 * log1p(pixels / 1_000_000)
```

其中：
- `pixels = max(0,width) * max(0,height)`
- `bookmark_count/view_count/comment_count` 为非负整数（NULL 视为 0）

## 4) 可观测性（debug）

`/random?format=json` 建议输出：
- `image.bookmark_count/view_count/comment_count`
- `debug.picked_by`：`quality|random`
- `debug.quality_samples`
- `debug.quality_score`

用于解释结果是否符合预期与排查“为什么总抽到某类图”。

## 5) 与补全系统的关系

质量策略依赖热度字段覆盖率：
- 覆盖率低时，很多图片 score=0，策略会退化为随机里挑最不差。
- 建议提供后台一键 backfill：`missing=popularity`。

## 6) 未来演进（不在 v1）

- 引入“去重/新鲜度”：避免短时间重复同一张图。
- 引入“收藏率”：`bookmark_count / view_count` 作为更稳定的质量指标。
- 按标签/作者做分层抽样：避免被单一作者或热门 tag 垄断。

