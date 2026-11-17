# 实现细节与设计约束

> 面向改代码的人。产品说明、目录结构与运维流程见根目录 `README.md`。

## 数据流

```
data/artists.json                     画师身份（唯一来源）
        │
        ▼
scripts/sync-artworks.mjs             order:score 取候选 → 差分排除 → 下载到暂存目录
        │                             (ATLAS_STAGING，默认系统临时目录)
        ▼
scripts/make-display-assets.py        暂存源文件 → 1600 px WebP → 删除源文件
        │
        ├──▶ docs/assets/artists/<Artist ID>/<Post ID>.display.webp   仓库里唯一的图片
        └──▶ data/artworks.json        来源、署名、许可、副本校验信息
                    │
                    ▼
              git commit → GitHub Pages
                    │
                    ▼
        docs/index.html 只请求 display 副本
```

## 页面信息架构

1. 站点标识与全局操作（主题、使用说明、NAI5 组合、管理图鉴）。
2. 标题与轻量统计（画师数、收录作品数、收藏数）。
3. 搜索、收藏筛选、排序、列数。
4. 唯一的画师卡片网格。
5. 来源与版权说明。

候选审核、批量导入、核验队列不属于公开页面；身份核验只在管理弹窗里按单个 Artist 进行。

## 卡片约束

- 所有画师共用一套卡片模板与信息顺序，禁止按单个 Artist ID 写特例。
- 每位画师恰好 3 张作品，必须是按 score 选出的、互不为差分的 General 图片。
- 卡片只加载 `display_url`；仓库没有源文件可回退，也不要接 Danbooru CDN 图。
- 图片保持原始比例完整显示，不裁切；留白由 `.art-ambient` 模糊背景填充。
- 网格由 CSS 变量 `--cols` 驱动，可切 2 / 3 / 4 列；实际列数按 320 px 最小卡片宽度收敛，≤720 px 隐藏控件。
- 照片、名字、别名、Danbooru 总数、已收录数、评分/核验标记的顺序固定。
- 分类为空或「未分类」时不渲染分类角标，避免整页出现相同标签。
- 图片失败时显示错误态与 Artist 主页链接，不用预览图掩盖问题。

## 渲染与性能

- **设计变量**集中在 `:root` 与 `[data-theme="dark"]`：纸色、墨色、苔绿强调色、圆角、阴影、缓动。新样式优先复用变量，不要散落硬编码颜色。
- **图标**用页首内联 SVG 精灵（`#i-*`），不依赖 emoji 或字体图标；带图标的按钮必须有 `aria-label`。
- **触控**目标不小于 44×44 CSS 像素；`@media (pointer:coarse)` 会进一步放大按钮与圆点。
- **keyed 局部更新**：只有可见画师集合变化时才重建网格；收藏、加入组合、切换作品只改对应节点，避免重复解码和焦点丢失。
- **加载分层**：首张 `eager` + `high`，其余 `lazy` + `low`；IntersectionObserver（`rootMargin: 260px`）在 `requestIdleCallback` 里预取下一位作品；悬停/聚焦预取整卡三张。
- **切换**：`img.decode()` 成功后再替换；旧帧由 ghost 图层做方向相关滑出（约 450 ms，只动 opacity/transform），定时器兜底被节流的标签页；`prefers-reduced-motion` 直接瞬时切换。预加载缓存上限 8 条。
- **离屏卡片**的骨架微光与「读取中」脉冲用 `data-inview` 门控，只有进入视口才 `animation-play-state: running`。
- **禁止**对大图主图使用 `filter: drop-shadow()` 等大尺寸离屏栅格化效果。
- **弹窗**需要焦点圈定、`Escape` 关闭、关闭后还原焦点，并在打开时锁住页面滚动。
- **主题**默认跟随 `prefers-color-scheme`；手动切换后以 localStorage 为准。

## 归档实现

`sync-artworks.mjs`

- 候选查询：`<artist_tag> rating:g order:score`，最多 120 条；要求未删除、有宽高、有 `file_url`/`large_file_url`、扩展名 jpg/jpeg/png/webp（排除 gif、ugoira）。
- 排序：score → fav_count → Post ID。
- 差分两层判定：Danbooru 父子关系（含向上三层）与 180 px 预览的 8×8 dHash（汉明距离 ≤ 12）。跳过的候选写入 `selection_detail.skipped_variants`。
- 下载：优先 `file_url`，失败/超限时 `large_file_url`；校验 HTTP 状态、长度、MIME、二进制签名；记录 `sha256`/`md5`；网络错误按指数稍等重试。
- 复用：manifest 中存在且 `source_md5` 未变、副本仍在的作品不再下载。`ATLAS_RESUME=1` 时整位画师直接复用（本地续跑用，CI 不设）。
- 逐位画师写 manifest 并立即转换，因此中断不会丢掉已完成的画师；全部完成后清理不再属于正式索引的目录。
- 任何画师凑不满 3 张不重复作品即整体失败，不提交部分归档。

`make-display-assets.py`

- 暂存源文件 → 最长边 1600 px、WebP quality 85、单张 ≤ 4 MiB，写入 `docs/assets/artists/<Artist ID>/<Post ID>.display.webp`。
- 更新 manifest 的 `display_*` 字段与 `display_updated_at`，然后删除该画师的暂存源文件。
- 幂等：副本尺寸/大小/SHA-256 已匹配就跳过；`--only <Artist ID>` 只处理一位画师且不做全局清理；不带参数时清理未引用的副本与遗留源文件。

`validate-artworks.mjs`

- 一位正式画师对应一条归档记录，恰好 3 张，Post ID 全局唯一。
- `permission.status = granted`、`confirmed_by = repository_owner`；`source_url` 指向对应 Post。
- 副本存在、命名 `<Post ID>.display.webp`、WebP 签名正确、宽高/字节数/SHA-256 与 manifest 一致，`display_source_sha256` 与 `source_sha256` 一致。
- 画师目录里不得有其它文件；显示副本总量 ≤ 120 MiB。

## 授权记录

仓库所有者于 2026-11-17 确认当前画师的作品允许保存、转换、上传与公开显示；`permission` 字段记录的是这一声明，不是脚本自动验证出的法律许可。许可范围变化时必须停止同步并移除不再获准的资产。

## 管理流程

管理弹窗用 Fine-grained GitHub Token 访问 Contents API，只授予本仓库的 Contents: Read and write。写入前重新读取远端文件并比对 blob SHA；远端已有其他修改时停止写入并要求刷新，避免覆盖并发更新。

## 扩容原则

新增画师只增加 `data/artists.json` 记录；归档工作流会创建对应目录并选片，不需要为单个画师写专属卡片。身份不确定时先不收录，宁可少一位，也不要写错 Artist ID。
