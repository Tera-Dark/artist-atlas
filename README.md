# Artist Atlas · 画师图鉴

**以 GitHub 仓库为数据中心的画师发现、核验与灵感整理图鉴。**

在线图鉴：<https://tera-dark.github.io/artist-atlas/>

## 当前方向

Artist Atlas 正在从 Windows 本地采集工作台转为 **Repository-first 画师图鉴**：

- GitHub 仓库中的 `data/artists.json` 是唯一正式画师索引，所有访问者读取同一份数据。
- GitHub Pages 提供暗色画师卡片、分类筛选、搜索、代表作预览与管理界面。
- 画师入库前通过 Danbooru Artist API 查询；精确选择条目后保存 Danbooru ID、别名、分类、风格标签、个人评分、备注与安全级别为 General 的作品预览。
- 管理操作通过 GitHub Contents API 提交 commit，不再以本机 JSON 或本地图片目录作为主数据库。
- Danbooru 仅用于只读核验；不确定的候选不会自动认定为同一画师。

## 使用在线图鉴

1. 打开 [Artist Atlas](https://tera-dark.github.io/artist-atlas/)。
2. 浏览公开图鉴、按分类筛选，或搜索画师名、别名和风格标签。
3. 点击「管理图鉴」，创建一个仅针对本仓库的 GitHub Fine-grained Personal Access Token。
4. Token 权限只需 `Contents: Read and write`；不要授予其他仓库或工作流权限。
5. 输入 Token 连接仓库，然后搜索 Danbooru 画师、选择准确条目、填写个人分类和备注并保存。
6. 保存后会直接向仓库提交变更；GitHub Pages 会在部署完成后显示更新。

创建 Token：<https://github.com/settings/personal-access-tokens/new>

**安全说明：** Token 仅保存在当前浏览器标签页的 sessionStorage 中，关闭标签页后失效；不要把 Token 写入仓库、截图或发给他人。公开仓库中的画师索引对所有访客可见，只有持有写权限 Token 的人可以修改。

## Danbooru 核验原则

- 查询入口使用 Danbooru `/artists.json` Artist API。
- 只有明确选中的 Artist 条目才会作为已核验画师保存。
- 作品预览只查询 `rating:g`，并保存缩略图 URL 与作品数量索引。
- Danbooru 的 Artist 条目与 artist 类型标签、作品收录情况并非完全等价；没有作品预览不代表画师身份无效。
- 遵守 Danbooru API 速率限制；不要高频批量请求。

参考：<https://danbooru.donmai.us/wiki_pages/api:artists> · <https://danbooru.donmai.us/wiki_pages/help:api>

## 数据结构

正式数据位于 `data/artists.json`。每位画师包含：

- `id`、`name`、`aliases`
- `danbooru_id`、`danbooru_name`
- `category`、`tags`、`score`、`note`
- `post_count`、`preview_urls`
- `added_at`、`updated_at`、`featured`

## 原 Windows 工具

仓库仍保留早期 Windows 本地采集工具源码，供需要从小红书推荐笔记整理候选名单的人使用。它不再是在线图鉴的主数据库，也不会自动把本地采集结果写入仓库。后续可增加「候选名单导入」功能，将候选画师批量送入 Danbooru 核验队列。

## 版权与隐私

画师作品版权归原作者及相应权利人所有。本项目只整理创作者索引和指向 Danbooru 的公开预览，不声称拥有作品版权。请尊重平台规则，不要未经授权转载、商用或重新分发作品。
