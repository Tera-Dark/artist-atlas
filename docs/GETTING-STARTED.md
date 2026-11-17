# Artist Atlas · 快速使用说明

在线图鉴：https://tera-dark.github.io/artist-atlas/

完整项目说明、数据结构、作品归档流程、GitHub Actions、手动命令、授权要求和 AI 接手规范，请优先阅读仓库根目录 README.md：

https://github.com/Tera-Dark/artist-atlas#readme

## 当前测试范围

目前正式图鉴只保留三位画师：

- zhanzhan_lan · Danbooru Artist ID 63362
- zhi_xu_li_ming · Danbooru Artist ID 408507
- z3zz4 · Danbooru Artist ID 261471

每位画师当前归档 3 张最新、未删除的 General 作品。图片已经保存到仓库 docs/assets/artists/<Artist ID>/，前端通过 data/artworks.json 加载本地图片。

## 浏览图鉴

- 搜索支持画师名称、别名、风格标签和备注。
- 可以按收藏筛选和排序。
- 卡片左右箭头和圆点切换三张本地作品。
- 点击作品打开对应 Danbooru 原帖；点击 DANBOORU PROFILE 打开 Artist 主页。
- 收藏与主题保存在当前浏览器；NAI5 组合只保存在当前页面会话。

## NAI5 画师串

在画师卡片点「加入组合」，再点页眉的「NAI5 画师串」，可调整组合顺序和标签强弱并复制候选串。实际识别效果以 NovelAI 输入框的标签建议为准。

## 管理图鉴

只有新增、编辑或删除正式画师时才需要 GitHub Token。创建 Fine-grained Token 时，仅选择 artist-atlas 仓库，并只授予 Contents: Read and write。

新增画师前必须核对 Danbooru Artist ID，并确认作者允许作品重新保存、上传到公开 GitHub 仓库及通过 GitHub Pages 展示。保存正式画师记录后，main 分支的自动化工作流会发现、下载、校验三张图片并部署网页。

Token 仅保存在当前浏览器会话，不能分享或提交到仓库。

## 作品更新

打开 GitHub Actions → Sync Authorized Artist Artwork → Run workflow，可以手动重新同步所有正式画师的最新三张 General 作品。自动流程也会在正式画师数据或归档脚本变化时运行，并每周一 UTC 03:17 检查更新。

## 常见问题

**作品没有显示？** 检查 data/artworks.json 的 local_url 是否对应 docs/assets 中真实存在的图片，再检查最新 Pages 部署是否成功。不要把 180×180 preview 当作高清主图。

**保存后页面没有立即更新？** 查看 GitHub Actions 中的校验与 Pages 部署状态；部署完成后强制刷新页面。

**什么时候恢复完整画师列表？** 当前三位是前端与归档流程的验收基线。只有用户明确要求扩容、并且新增作者的再托管许可已确认后，才增加正式记录。
