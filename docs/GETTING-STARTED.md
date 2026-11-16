# 新手入门：5 分钟收录第一位画师

在线入口：<https://tera-dark.github.io/artist-atlas/>

## 先了解它是什么

Artist Atlas 是个人画师索引与灵感图鉴。GitHub 仓库保存正式记录，Danbooru 用于核验 Artist 身份和提供公开作品预览。个人评分、分类、风格标签和备注由收藏者自己决定。

浏览图鉴、搜索和筛选不需要登录。只有添加、编辑、删除或设置精选时，才需要 GitHub 写入授权。

## 第一步：浏览

1. 打开在线图鉴。
2. 使用搜索框查画师名称、别名、风格标签或备注。
3. 使用分类筛选和排序查看收藏。

首次打开会出现简短引导；之后可随时点击顶部「使用指南」重新查看。

## 第二步：准备 GitHub 授权

管理功能通过 GitHub Contents API 将修改提交到本项目仓库。GitHub Pages 没有服务端密钥，因此当前版本需要维护者自己提供 Fine-grained Personal Access Token。

1. 打开 <https://github.com/settings/personal-access-tokens/new>。
2. Token name 可以填写 Artist Atlas。
3. Expiration 建议设置为较短的有效期，并在到期时重新创建。
4. Repository access 选择 Only select repositories，只勾选 artist-atlas。
5. Repository permissions 中将 Contents 设置为 Read and write。
6. 其他权限保持 No access，创建后复制 Token。
7. 回到网页，点击「管理图鉴」，粘贴 Token 并连接。

**安全注意：** 不要把 Token 发给别人、贴到 Issue、写进源码或提交到仓库。公共网页使用者不应使用自己的 Token 修改不属于自己的仓库。当前 Token 只在当前浏览器会话中使用；关闭会话或点击「清除会话授权」可清除保存的会话凭据。

## 第三步：核验并收录

1. 在管理面板输入 Danbooru 画师名称或别名。
2. 对照规范名称、别名和 Artist ID。名字相似不等于同一个人。
3. 封禁或删除状态的条目不能正常收录。
4. 检查作品预览。当前只请求 General（rating:g）作品；没有预览不代表 Artist 身份无效。
5. 填写图鉴显示名称、分类、风格标签、评分和备注。
6. 保存前检查资料，确认后提交到 GitHub。

保存成功代表 GitHub 已接受提交；公开页面还需要等待 GitHub Actions 完成 Pages 部署后才会更新。

## 推荐的整理方式

- 分类用于大方向，例如「插画」「角色设计」「厚涂」。
- 风格标签用于交叉检索，例如「柔和光影」「复古」「少女感」。
- 评分是个人审美评价，不是客观排名。
- 备注写清楚你喜欢这位画师的原因，未来回看更有价值。

## 常见问题

**为什么需要 Token？**  因为静态 GitHub Pages 没有可以安全保存写入密钥的服务器。当前管理功能直接调用 GitHub API。

**Danbooru 没搜到怎么办？**  检查拼写、常用别名或 Artist 页面链接。不要为了完成收录而选择一个相似名字的条目。

**为什么没有作品预览？**  可能没有 General 级别作品、作品标签不完整，或 Danbooru 请求暂时失败。应以 Artist ID 和来源页面为主要身份依据。

**为什么保存后页面没立刻变化？**  提交后需要 GitHub Actions 构建并部署 Pages。可以在仓库 Actions 页面查看部署状态。

**可以批量导入候选画师吗？**  目前候选收集箱和批量导入仍在规划中；当前版本以逐个核验、逐个收录为主。