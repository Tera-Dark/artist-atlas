# Artist Atlas · 画师图鉴

**以 GitHub 仓库为数据中心的画师发现、核验与灵感整理图鉴。**

在线图鉴：<https://tera-dark.github.io/artist-atlas/>

## 当前方向

Artist Atlas 正在从 Windows 本地采集工作台转为 **Repository-first 画师图鉴**：

- GitHub 仓库中的 `data/artists.json` 是唯一正式画师索引，所有访问者读取同一份数据；Pages 部署时将其复制到同源静态目录。
- GitHub Pages 提供中性色画师图鉴、分类筛选、搜索、最多 3 张 General 级别作品预览、本地收藏与管理界面。
- 画师入库前通过 Danbooru Artist API 查询；精确选择条目后保存 Danbooru ID、别名、分类、风格标签、个人评分、备注与安全级别为 General 的作品预览。
- 管理操作通过 GitHub Contents API 提交 commit；写入时会对比远端最新记录，检测并发修改，避免静默覆盖。
- Danbooru 仅用于只读核验；不确定的候选不会自动认定为同一画师。
- 作品预览保留 Danbooru 远程缩略图和原帖链接，不将作品图片重新托管到本仓库。
- 收藏保存在访问者当前浏览器；NAI5 画师串搭配器支持调整画师顺序、单独设置标签强弱并复制候选串。

## 使用在线图鉴

1. 打开 [Artist Atlas](https://tera-dark.github.io/artist-atlas/)。
2. 浏览公开图鉴、按分类筛选，或搜索画师名、别名和风格标签。
3. 在画师卡片收藏喜欢的画师，或加入 NAI5 画师串搭配器组合、排序和调整强弱。
4. 点击「管理图鉴」，创建一个仅针对本仓库的 GitHub Fine-grained Personal Access Token。
5. Token 权限只需 `Contents: Read and write`；不要授予其他仓库或工作流权限。
6. 输入 Token 连接仓库，然后搜索 Danbooru 画师、选择准确条目、填写个人分类和备注并保存。
7. 保存后会直接向仓库提交变更；GitHub Pages 会在部署完成后显示更新。

创建 Token：<https://github.com/settings/personal-access-tokens/new>

**安全说明：** Token 仅保存在当前浏览器标签页的 sessionStorage 中，关闭标签页后失效；不要把 Token 写入仓库、截图或发给他人。公开仓库中的画师索引对所有访客可见，只有持有写权限 Token 的人可以修改。

## Danbooru 核验原则

- 查询入口使用 Danbooru `/artists.json` Artist API。
- 只有明确选中的 Artist 条目才会作为已核验画师保存。
- 作品预览按热度取最多 3 张 `rating:g` 作品，并保存缩略图 URL 和 Danbooru 原帖 ID，卡片可直接打开来源作品。
- Danbooru 的 Artist 条目与 artist 类型标签、作品收录情况并非完全等价；没有作品预览不代表画师身份无效。
- 遵守 Danbooru API 速率限制；不要高频批量请求。

参考：<https://danbooru.donmai.us/wiki_pages/api:artists> · <https://danbooru.donmai.us/wiki_pages/help:api>

## 数据结构

正式数据位于 `data/artists.json`。每位画师包含：

- `id`、`name`、`aliases`
- `danbooru_id`、`danbooru_name`
- `category`、`tags`、`score`、`note`
- `post_count`、`preview_urls`、`preview_post_ids`
- `added_at`、`updated_at`、`featured`

## 新手开始

第一次使用请阅读 [5 分钟新手入门](docs/GETTING-STARTED.md)。页面也提供首次打开引导和随时可查看的使用指南。

## 项目结构与质量检查

- `data/artist.schema.json`：正式数据结构。
- `scripts/validate-data.mjs`：检查 JSON、重复身份、预览链接和页面脚本。
- `scripts/import-verified-artists.mjs`：将唯一有效的核验结果生成或刷新图鉴卡片，保留已有个人整理字段。
- `.github/workflows/validate.yml`：推送和 Pull Request 自动检查。
- Pages 发布前也会先执行数据校验。
- `docs/ARCHITECTURE.md`：数据边界、核验规则和演进路线。
- `CONTRIBUTING.md`：社区贡献与画师收录规则。

## 原 Windows 工具

仓库仍保留早期 Windows 本地采集工具源码，供需要从小红书推荐笔记整理候选名单的人使用。它不再是在线图鉴的主数据库，也不会自动把本地采集结果写入仓库。网页内的候选名单导入仍待实现；已核验候选可通过 `node scripts/import-verified-artists.mjs` 批量生成图鉴记录。

## 版权与隐私

画师作品版权归原作者及相应权利人所有。本项目只整理创作者索引和指向 Danbooru 的公开预览，不声称拥有作品版权。请尊重平台规则，不要未经授权转载、商用或重新分发作品。

## NAI5 画师串

在卡片上将画师加入组合后，可在搭配器中调整顺序，并为单个标签选择普通、加强或减弱，最后复制逗号分隔的 `artist:` 标签候选串。NovelAI 对不同画师标签的识别程度会有差异，建议在 NAI 输入框中结合标签建议核对。收藏和组合状态保存在本地浏览器，不会写入公开仓库。
