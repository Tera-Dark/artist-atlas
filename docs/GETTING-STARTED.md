# Artist Atlas · 快速使用说明

在线图鉴：https://tera-dark.github.io/artist-atlas/

完整项目说明、数据结构、作品归档流程、GitHub Actions、手动命令、授权要求和 AI 接手规范，请优先阅读仓库根目录 README.md：

https://github.com/Tera-Dark/artist-atlas#readme

## 当前测试范围

目前正式图鉴收录 **71 位画师**，完整名单以 `data/artists.json` 为准。每位画师归档 3 张按 Danbooru score 排名最高、未删除的 General 作品，并排除差分与近似重复。

仓库只保存最长边 1600 px 的 WebP 显示副本（`docs/assets/artists/<Artist ID>/<Post ID>.display.webp`）；Danbooru 源文件只在临时目录中用于转换，转换完即删除。前端通过 `data/artworks.json` 的 `display_url` 加载显示副本，所以页面不需要解码大尺寸图片。

## 浏览图鉴

- 搜索支持画师名称、别名、风格标签和备注，空格与下划线可以混用。
- 可以按收藏筛选和排序。
- 卡片左右箭头、圆点、键盘方向键或手机左右滑动切换三张本地作品。
- 工具栏「列数」可切换每行 2 / 3 / 4 张，默认 3 张；窗口变窄会自动减少列数，手机端固定单列。
- 卡片上会显示 Danbooru 作品总数和常用别名，数字越大通常说明该画师的风格在模型里越稳定。
- 作品图使用 1600 px 显示副本，首屏只加载可见卡片，切换时无空白闪动。
- 点击作品打开大图弹窗，可切换「适应 / 100% / 200%」并拖动查看；方向键换图，弹窗内保留「原帖」入口。
- 点击 Danbooru 主页打开 Artist 页面。
- 收藏与主题保存在当前浏览器；NAI5 组合只保存在当前页面会话，刷新后不保证保留。
- 主题默认跟随系统深浅色，也可以手动切换。
- 布局在桌面、平板和手机上使用同一套卡片，不提供第二份画师列表。

## NAI5 画师串

在画师卡片点「加入组合」，再点页眉的「NAI5 画师串」，可调整组合顺序和标签强弱并复制候选串。实际识别效果以 NovelAI 输入框的标签建议为准。

## 管理图鉴

只有新增、编辑或删除正式画师时才需要 GitHub Token。创建 Fine-grained Token 时，仅选择 artist-atlas 仓库，并只授予 Contents: Read and write。

新增画师前必须核对 Danbooru Artist ID，并确认作者允许作品重新保存、转换、上传到公开 GitHub 仓库及通过 GitHub Pages 展示。保存正式画师记录后，main 分支的自动化工作流会发现、下载、校验三张图片并部署网页。

Token 仅保存在当前浏览器会话，不能分享或提交到仓库。

## 作品更新

打开 GitHub Actions → Sync Authorized Artist Artwork → Run workflow，可以手动重新同步所有正式画师按 score 选出且互不重复的三张 General 作品。自动流程也会在正式画师数据或归档脚本变化时运行，并每周一 UTC 03:17 检查更新。

## 常见问题

**作品没有显示？** 检查 data/artworks.json 的 display_url 是否对应 docs/assets 中真实存在的 `.display.webp`，再检查最新 Pages 部署是否成功。不要把 180×180 preview 当作高清主图。

**保存后页面没有立即更新？** 查看 GitHub Actions 中的校验与 Pages 部署状态；部署完成后强制刷新页面。

**如何继续扩容？** 先确认新作者的再托管许可，再把 Artist 记录写入 `data/artists.json` 并提交；归档工作流会自动补齐作品。
