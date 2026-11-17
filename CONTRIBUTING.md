# 参与 Artist Atlas

感谢你帮忙完善画师图鉴。改动请通过 Pull Request 提交，并在描述里写明依据。

## 可以改什么

- 画师索引：`data/artists.json`（名称、别名、分类、标签、评分、备注）
- 前端：`docs/index.html`（一个文件包含全部样式与脚本）
- 归档脚本与校验：`scripts/`
- 文档：`README.md`、`docs/`、`CONTRIBUTING.md`

`data/artworks.json` 和 `docs/assets/artists/` 由归档工作流生成，**不要手工编辑或手工上传图片**。需要刷新作品时在 Actions 里重跑同步任务。

## 新增一位画师

前提：该作者的再保存、格式转换、上传到公开仓库和 Pages 展示已经得到允许。仅凭 Danbooru 公开可看、General 分级或可下载 URL 都不构成授权。

1. 在 Danbooru 找到准确的 Artist 条目，确认 Artist ID、规范名和别名；`is_banned` 或 `is_deleted` 的条目不收录。
2. 先搜索现有 `data/artists.json`，确认该 Artist ID、名称、别名都还没有被收录。
3. 添加一条记录，字段只允许 `id`、`name`、`danbooru_id`、`danbooru_name`、`aliases`、`category`、`tags`、`score`、`note`、`added_at`、`updated_at`；`id` 使用 `artist-<Artist ID>`。
4. 运行 `node scripts/validate-data.mjs`，确认没有重复 ID、重复别名或字段错误。
5. 在 PR 里说明身份核验依据（Artist 页面链接、别名来源、为何不是同名他人）。

合并后归档工作流会挑选 3 张热度最高、互不为差分的 General 作品，转成 1600 px WebP 显示副本并部署。

## 修改前端

- 保持单一正式画师网格和统一卡片模板，不为单个 Artist ID 写特例。
- 图片只从 `data/artworks.json` 的 `display_url` 加载；不要引入 Danbooru CDN 图片、不要重新保存源文件。
- 保留懒加载、`img.decode()` 切换、离屏卡片不做无限动画的既有约定。
- 改完运行 `node scripts/validate-data.mjs`（会检查 DOM id 重复、脚本引用和 JS 语法）。

## 修改归档脚本

同时检查这三处是否一致：脚本常量、`data/artworks.json` 里的策略文案、文档说明。改完至少跑一次：

```bash
node scripts/validate-data.mjs
node scripts/validate-artworks.mjs
```

## 不要做的事

- 伪造 Post ID、图片路径、文件大小、SHA-256 或授权记录。
- 提交 Danbooru 源文件、候选池、核验批次或第二份画师列表。
- 提交 Token、Cookie、账号数据、采集结果或任何本机凭证。
- 仅凭名称相似合并两条画师记录；有疑问就在 PR 里标出来人工确认。
- 为了“看起来更多”而批量导入未经逐个核验的画师。

## 报告问题

请说明涉及的页面或数据记录、复现步骤、期望结果和实际结果，并附上浏览器版本与截图（不要包含凭证或私密信息）。
