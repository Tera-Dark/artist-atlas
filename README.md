# Artist Atlas · 画师图鉴

**一份以作品为中心的个人画师与视觉灵感档案。**

在线图鉴：<https://tera-dark.github.io/artist-atlas/>

## 当前版本

Artist Atlas 目前处于 **三位画师的前端验收阶段**。正式图鉴只保留：

- zhanzhan_lan · Danbooru Artist ID 63362
- zhi_xu_li_ming · Danbooru Artist ID 408507
- z3zz4 · Danbooru Artist ID 261471

旧画师索引已从正式目录移除；旧候选池和核验结果已清空。后续新增画师应在当前卡片、作品清晰度与浏览体验验收通过后再进行。

## 页面设计

- 主页面只有一个正式画师图鉴，不再同时展示候选池和已收录画师两套列表。
- 三位画师共用同一套卡片、信息层级、作品舞台和轮播交互。
- 每位画师归档 3 张最新的 Danbooru General 级别作品。授权归档由 GitHub Actions 自动下载到 docs/assets/artists/<artist_id>/，页面只读取仓库内的本地高清图片。
- 作品按原始比例完整呈现，不做强制裁切；点击作品可打开 Danbooru 原帖。
- 支持名称/别名/风格/备注搜索、收藏筛选、排序、主题切换和 NAI5 画师串组合。
- 收藏、主题与组合状态保存在当前浏览器；正式画师资料保存在 data/artists.json。

## 管理图鉴

管理操作通过 GitHub Contents API 提交到本仓库。GitHub Pages 是静态站点，因此只有维护者在需要新增、编辑或删除资料时才需要连接 Fine-grained Personal Access Token。

建议权限：
- Repository access：Only select repositories → artist-atlas
- Repository permissions：Contents: Read and write
- 其他权限：No access

Token 只保存在当前浏览器会话中，不要写入源码、仓库或截图，也不要分享给他人。

## 数据结构

正式索引位于 data/artists.json，每位画师包含：

- id、name、aliases
- danbooru_id、danbooru_name、danbooru_url
- category、tags、score、note
- post_count、preview_urls、preview_post_ids
- added_at、updated_at、featured

作品展示以浏览器实时读取的 Danbooru 帖子数据为准；仓库中的预览 URL 仅保留来源与历史记录用途，不作为高清主展示的保证。

## 质量检查

- data/artist.schema.json：画师数据结构。
- scripts/validate-data.mjs：检查数据、重复身份、页面 DOM ID 与内联脚本语法。
- .github/workflows/validate.yml：推送和 Pull Request 自动检查。
- GitHub Pages 发布工作流会在部署前进行校验。

## 版权与来源

画师作品版权归原作者及相应权利人所有。画师作者已授权仓库所有者重新保存、上传并公开展示当前归档范围内的作品。仓库会为每张图保存 Danbooru 原帖、署名、下载信息和完整性校验；如授权范围变化，应立即停止同步并移除不再获准展示的文件。请尊重平台规则与原作者权益。

## 本地作品归档

- scripts/sync-artworks.mjs：按 Artist ID 搜索最新 General 图片，下载原图或较大 sample，执行格式、尺寸和文件大小检查。
- scripts/validate-artworks.mjs：校验授权确认记录、原帖链接、本地文件路径、文件签名、大小与 SHA-256。
- .github/workflows/sync-artworks.yml：当正式画师目录变更时自动运行；同时支持手动运行，并每周一自动检查更新。
- 图片保存为 docs/assets/artists/<artist_id>/<post_id>.<ext>，页面通过 data/artworks.json 使用本地文件。
- 每位画师保留最新 3 张 General 图片。同步完成后，工作流提交图片和清单并重新部署 GitHub Pages。
- 当前授权范围是仓库现存的三位测试画师；新增画师将进入同一条同步流程。
