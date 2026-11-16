# Artist Atlas · 使用说明

在线入口：<https://tera-dark.github.io/artist-atlas/>

## 当前测试范围

目前只保留三位测试画师：zhanzhan_lan、zhi_xu_li_ming、z3zz4。这不是候选池，也不是正式扩容完成后的全量图鉴；当前目标是先验收作品显示、卡片统一性与浏览交互。

## 浏览图鉴

- 主页面只有一份正式画师列表。
- 搜索支持名称、别名、风格标签与备注。
- 「我的收藏」仅筛选当前浏览器保存的收藏。
- 卡片上的左右箭头和圆点用于切换最多三张最新作品。
- 点击作品打开 Danbooru 原帖；点击 DANBOORU PROFILE 打开画师主页。

作品来自 Danbooru rating:g 的最新帖子，主展示优先采用较大尺寸的作品文件。页面不使用 180×180 缩略图作为主视觉。若 Danbooru 请求失败，卡片会显示提示，不会静默用模糊小图替代高清作品。

## NAI5 画师串

在画师卡片点「加入组合」，再点页眉的「NAI5 画师串」即可调整组合顺序和标签强弱，并复制候选串。实际识别效果仍以 NovelAI 输入框的标签建议为准。

## 管理图鉴

仅在新增、编辑或删除画师时需要 GitHub Token：

1. 打开 <https://github.com/settings/personal-access-tokens/new> 创建 Fine-grained Token。
2. Repository access 选择 Only select repositories，并只勾选 artist-atlas。
3. 将 Contents 权限设为 Read and write，其余权限保持 No access。
4. 回到图鉴，点击「管理图鉴」，连接 Token。
5. 搜索 Danbooru Artist 名称或别名，仔细核对 Artist ID。
6. 选择准确条目，填写自己的显示名称、分类、标签、评分与备注，再保存。

Token 仅保存在当前浏览器会话，不要分享、截图或写入源码。仓库数据更新后，GitHub Actions 会校验并触发 Pages 部署。

## 常见情况

**作品没有显示？** 检查浏览器网络请求是否能访问 danbooru.donmai.us。无作品或 API 请求失败时，卡片会显示说明和画师主页入口。

**保存后页面没有立即更新？** 查看 GitHub Actions 中的校验与 Pages 部署状态；部署完成后刷新页面。

**什么时候恢复完整画师列表？** 等三位测试卡片的视觉与交互验收通过，再决定下一轮导入。当前阶段不会自动恢复之前移除的名单。
