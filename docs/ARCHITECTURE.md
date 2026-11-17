# Artist Atlas · 前端与作品归档架构

> 当前状态：三位画师的本地作品归档与统一卡片验收版

## 产品边界

Artist Atlas 是个人画师与视觉参考档案。公开页面只维护一份正式画师索引，不展示候选列表、核验批次或第二套目录。

当前测试数据仅保留 zhanzhan_lan、zhi_xu_li_ming、z3zz4。当前归档范围是这三位画师；后续新增画师会走相同流程。

## 单一数据流

data/artists.json
       |
       v
GitHub Actions 按 score 查询 Danbooru Artist 的 General 图片作品
       |
       v
把源文件下载到临时暂存目录（受大小限制时使用较大 sample）
       |
       v
校验文件格式 / 尺寸 / SHA-256
       |
       v
docs/assets/artists/<artist_id>/<post_id>.display.webp   唯一归档文件
       |
       v
生成 <post_id>.display.webp（最长边 1600 px，WebP 85）
       |
       +---- data/artworks.json（来源、署名、授权与显示副本清单）
       |
       v
GitHub commit
       |
       v
GitHub Pages 只加载 display 副本

## 页面信息架构

公开页面只保留以下层级：

1. 站点标识与全局操作。
2. 图鉴标题与轻量统计。
3. 搜索、收藏筛选和排序。
4. 唯一的画师卡片网格。
5. 来源与版权说明。

候选审核、批量导入、核验队列不属于公开浏览页面。身份核验只在管理弹窗中按单个 Artist 进行。

## 画师卡片约束

- 所有画师使用同一套卡片模板和信息顺序，不允许按单个 ID 编写特例卡片。
- 每位画师最多展示 3 张热度最高且互不重复（排除差分）的 General 图片作品。
- 主页面只读取仓库内的本地资产，且只加载 display 副本；仓库不保留源文件。
- 卡片需要保持懒加载：首屏只请求可见卡片，预取在 idle 阶段执行，切换作品时旧图保留到新图解码完成。
- 骨架屏与「读取中」动画只在卡片进入视口时播放（`data-inview`），离屏卡片保持暂停，避免长期占用合成线程。
- 源文件优先；超过单文件大小上限或下载失败时，才尝试使用 Danbooru large sample；源文件只用于转换。
- 图片保持原始长宽比完整显示，不使用强制裁切。
- 左右按钮、圆点、键盘方向键和手机左右滑动控制同一卡片内部的作品索引。
- 点击作品打开对应 Danbooru Post；资料入口打开 Artist 页面。
- 图片请求失败时展示明确的错误提示与 Artist 主页链接。
- 卡片正文显示 Danbooru 作品总数与常用别名，资料来自 artworks manifest 的 danbooru_post_count / danbooru_aliases；缺失时不显示，不要在前端伪造数字。
- 网格支持每行 2 / 3 / 4 列（默认 3），以 CSS 变量 --cols 驱动，实际列数按 320 px 最小卡片宽度收敛。

## 前端实现约定

- 设计变量集中在 `docs/index.html` 的 `:root` 与 `[data-theme="dark"]`：纸张色、墨色、苔绿强调色、圆角、阴影、缓动。新增样式应优先复用变量，不要散落硬编码颜色。
- 图标使用页首内联 SVG 精灵（`#i-*` symbol），不依赖 emoji 或字体图标；任何需要图标的按钮都应保留 `aria-label`。
- 触控目标不小于 44×44 CSS 像素（`@media (pointer:coarse)` 会进一步放大按钮与圆点）。
- 渲染采用 keyed 局部更新：只有可见画师集合变化时才重建卡片网格；收藏、加入组合、切换作品只更新对应节点，避免大图重复解码和焦点丢失。
- 图片加载分层：首屏一张 eager + high，其余 lazy；IntersectionObserver 在接近视口时通过 requestIdleCallback 预取下一张；悬停/聚焦时预取整张卡片的 display 副本。
- 切换作品时先 `img.decode()` 再替换显示，旧图保持到新帧就绪；预加载缓存上限 8 条。
- 环境模糊背景只在主图加载完成后设置，离屏卡片不得提前请求图片。
- 主图是 1600 px 显示副本，禁止对主图使用 `filter: drop-shadow()` 等会触发大尺寸离屏栅格化的效果。
- 弹窗需要焦点圈定、`Escape` 关闭、关闭后还原焦点，并在打开时锁住页面滚动。
- 动效遵循 `prefers-reduced-motion`；主题默认跟随 `prefers-color-scheme`，用户手动切换后以 `localStorage` 为准。

## 归档与来源记录

data/artworks.json 为本地图片档案清单，每张作品记录：

- Danbooru Post ID 与原帖 URL。
- 原始媒体 URL、下载后的本地路径。
- 文件类型、尺寸、字节数与 SHA-256。
- 下载时间、署名与对应 Artist ID。
- 仓库所有者确认的作者再保存和公开展示许可。
- display 副本的路径、变体、尺寸、字节数、SHA-256 与源图 SHA-256。

仓库所有者于 2026-11-17 确认当前归档范围的作者已允许将作品保存、上传并公开展示。授权确认以仓库所有者的声明作为记录；如果许可范围变化，必须停止同步并移除不再获准保留的资产。

## 自动同步

scripts/sync-artworks.mjs：
- 每位画师用 `order:score` 查询最多 120 条候选，筛选非删除、General、静态图片格式作品。
- 按 score、fav_count、Post ID 排序，选择 3 张无差分/近重复的作品。
- 差分判定：Danbooru 父帖关系（含向上三层）与 180px preview 的 8×8 dHash（汉明距离 ≤ 12）。
- 跳过的候选写入 `selection_detail.skipped_variants`，便于复核。
- preview 只用于比较，不写入仓库。
- 源文件下载上限 32 MiB；仓库只归档显示副本，总量上限 120 MiB。
- Danbooru 请求之间保持间隔，失败时不提交部分归档。
- 只保留当前三张选中作品，清理对应画师目录中的旧文件。

scripts/make-display-assets.py：
- 从暂存源文件生成最长边 1600 px、WebP quality 85 的 display 副本，随后删除源文件。
- 幂等：display 复制件校验通过就跳过；清理 manifest 未引用的旧文件和遗留源文件。

scripts/validate-artworks.mjs：
- 校验所有正式画师都有 3 张图片。
- 校验授权确认、作者署名、Post ID 和来源链接。
- 读取本地文件并校验图片签名、尺寸、字节数及 SHA-256。
- 校验每张作品的 WebP display 副本、源文件追溯字段与 120 MiB 总量。

.github/workflows/sync-artworks.yml：
- 正式画师索引或归档脚本变化时自动运行。
- 支持手动运行。
- 每周一自动复查作品。
- 同步完成后提交图片及清单，并在同一工作流中部署 Pages，避免图片尚未提交就先发布页面。

## 管理流程

管理弹窗使用 Fine-grained GitHub Token 访问 Contents API。建议仅授权本仓库的 Contents Read and write 权限。

提交前重新读取远端文件并比对 blob SHA；若远端已有其他修改，则停止写入并要求刷新，避免覆盖并发更新。

## 后续扩容原则

只有在三张卡片的作品清晰度、信息层级、桌面与移动端布局、轮播与管理流程完成验收后，才恢复完整名单。新增画师只需要增加正式索引；归档工作流会自动创建对应目录，不需要为单个画师写专属卡片结构。
