# Artist Atlas · 画师图鉴

**以作品为中心的个人画师索引、视觉参考档案与自动化作品归档工具。**

- 在线图鉴：https://tera-dark.github.io/artist-atlas/
- GitHub 仓库：https://github.com/Tera-Dark/artist-atlas
- 当前默认分支：main
- 当前阶段：三位画师测试与验收基线

> 本 README 同时是项目的 AI 交接手册。接手项目的 AI 应先完整阅读本文件，再检查仓库当前 main 分支中的脚本、数据和工作流；不要只依赖历史聊天摘要或旧版本说明。

---

## 1. 项目目标与当前状态

Artist Atlas 用来整理值得研究的画师及其作品。每位画师有唯一的 Danbooru Artist ID；作品通过 Danbooru Post ID 追溯来源；获得作者允许重新保存和公开展示的图片会归档到本仓库，公开网页只读取仓库内的本地图片。

当前正式图鉴包含以下 8 位画师：

| 画师 | Danbooru Artist ID | 本地图片 |
|---|---:|---:|
| zhanzhan_lan | 63362 | 3 张 |
| zhi_xu_li_ming | 408507 | 3 张 |
| z3zz4 | 261471 | 3 张 |
| dare_no_inarikami | 162585 | 3 张 |
| dabaijiang_memeda | 232766 | 3 张 |
| azling | 85638 | 3 张 |
| road_233 | 99961 | 3 张 |
| amejaga | 147594 | 3 张 |

当前归档状态为 ready：共 8 位画师、24 张图片。归档原图约 60.75 MiB，另有约 3.81 MiB 的 1600 px WebP 显示副本，网页只加载后者。旧的 63 位画师记录已经从正式索引中移除；旧候选池和核验结果已经清空。

**当前基线是以上 8 位画师，不要擅自恢复旧的 63 位名单。** 新增画师必须由仓库所有者明确要求，并确认作者允许重新保存、上传及公开展示；不要把模糊匹配到的 Artist 直接写入正式索引。

### 产品边界

- 公开页面只有一份正式画师图鉴，不展示候选池、核验批次或第二份画师列表。
- 所有画师共用同一种卡片结构；不得按某个 Artist ID 写特殊卡片。
- 每位画师默认归档 3 张热度最高、未删除、General 级别的图片作品，并排除差分与近似重复；同一张卡片的三个位不应是同一张画的微调版本。
- 公开图鉴的作品来自 GitHub 仓库本地文件，不依赖访客浏览器实时访问 Danbooru CDN。
- Danbooru 仍用于管理流程中的 Artist 身份查询、作品候选发现和原帖来源追溯。
- 项目不是下载站、排行榜或作品版权归属声明工具。不得把公开可见错误认为可自由再发布；再托管必须有作者允许。

---

## 2. 仓库目录与职责

当前重要目录如下：

    data/
      artists.json              正式画师索引，唯一的画师数据源
      artworks.json             本地作品归档清单与来源记录
      artist.schema.json        正式画师索引的数据结构
      candidates.json           旧候选数据兼容文件，目前为空
      verified-artists.json     旧核验结果兼容文件，目前为空

    docs/
      index.html                GitHub Pages 前端
      GETTING-STARTED.md        简短使用说明
      ARCHITECTURE.md           前端与归档架构说明
      assets/
        artists/
          63362/                按 Danbooru Artist ID 独立存放图片
          408507/
          261471/

    scripts/
      sync-artworks.mjs         Danbooru 作品发现、差分排除、下载、归档脚本
      image-signature.py       计算 preview 的 dHash，供差分/近重复判定使用
      make-display-assets.py    从归档原图生成 1600px WebP 显示副本
      validate-artworks.mjs    作品清单、原图与显示副本完整性校验
      validate-data.mjs        画师索引、DOM ID 和前端脚本校验

    .github/
      workflows/
        sync-artworks.yml      自动归档、提交图片并部署 Pages
        validate.yml            Push / Pull Request 数据与脚本检查
        pages.yml               手动 Pages 部署备用工作流

### 各文件的权威性

**data/artists.json 是正式画师索引的唯一数据源。** 画师名称、别名、Danbooru Artist ID、分类、标签、评分和备注都以这里为准。

**data/artworks.json 是正式作品归档清单。** 前端根据 Artist ID 找到该画师的 artworks 数组，再使用每条记录的 local_url 加载本地文件。

**docs/assets/artists/ 是图片二进制文件的实际存储位置。** 每位画师使用 Artist ID 作为目录名，每张图片使用 Danbooru Post ID 作为文件名。

candidates.json 和 verified-artists.json 是旧流程留下的兼容数据文件，目前数组为空，也不由 Pages 发布工作流复制到线上。validate-data.mjs 目前仍会检查这两个文件的基本结构；不要在没有调整验证器和产品设计的前提下重新启用旧候选池。

---

## 3. 数据模型

### 3.1 正式画师索引：data/artists.json

顶层结构：

- version：当前为 1。
- updated_at：索引最近更新时间。
- artists：正式画师数组。

每位画师使用以下字段：

| 字段 | 含义 |
|---|---|
| id | 仓库内部稳定 ID，格式通常为 artist-<Danbooru Artist ID> |
| name | 图鉴里显示的名称 |
| danbooru_id | Danbooru Artist ID，必须是正整数的字符串 |
| danbooru_name | Danbooru 规范名称 / artist tag 名称 |
| aliases | 作者别名数组 |
| category | 用户自定义分类 |
| tags | 用户自定义风格标签 |
| score | 个人评分，1–10 或 null |
| note | 个人备注 |
| post_count | 已收录到本仓库的作品数量（不是 Danbooru 总数；总数见 manifest 的 danbooru_post_count） |
| preview_urls | 历史预览 URL 数组，不是公开卡片高清图的权威来源 |
| preview_post_ids | 历史预览对应的 Post ID |
| danbooru_url | 对应 Artist 主页 |
| added_at / updated_at | 添加与修改时间 |
| danbooru_verified_at | 身份核验时间 |
| preview_updated_at | 历史预览信息更新时间 |
| featured | 兼容字段；当前公开页面不使用第二套精选区 |

编辑画师时必须保留稳定的 id 和 Danbooru 身份对应关系。不要把两个不同的 Artist ID 合并，也不要仅凭名称相似就覆盖已有记录。

### 3.2 作品归档清单：data/artworks.json

顶层字段：

- version：当前为 1。
- status：pending 或 ready。
- updated_at：归档清单更新时间。
- selection_policy：作品选择规则说明。
- storage_policy：原图归档规则说明。
- display_policy：网页显示副本（1600px WebP）的生成规则说明。
- display_updated_at：显示副本最近生成时间。
- artists：每位正式画师的归档记录。

每位画师归档记录包括：

- artist_id：Danbooru Artist ID。
- artist_record_id：对应 artists.json 中的内部 id。
- artist_name、artist_tag：显示名称与 Danbooru tag。
- danbooru_name、danbooru_post_count：Danbooru 规范名与作品总数（tag post_count，含各分级），用于卡片展示和风格强度判断。
- danbooru_aliases：Danbooru 返回的别名列表；前端会与 artists.json 的 aliases 合并后用于展示和搜索。
- facts_updated_at：上述资料最近刷新时间。
- selection：当前为 top_scored_general_posts_without_variants。
- selection_detail：候选池大小、差分判定阈值与被跳过候选清单（含原因）。
- permission：仓库所有者确认的再保存和公开展示许可记录。
- artworks：最多三张、当前要求恰好三张的图片记录。

每张作品记录包括：

| 字段 | 含义 |
|---|---|
| post_id | Danbooru Post ID |
| source_url | 对应 Danbooru 原帖地址 |
| source_file_url | Danbooru 图片 CDN 来源地址 |
| local_url | 仓库内相对 docs/ 的本地路径 |
| file_name / file_ext | 文件名与扩展名 |
| mime_type | 根据实际图片文件签名识别的 MIME 类型 |
| image_width / image_height | Danbooru API 返回的图片尺寸元数据 |
| file_size | 实际下载文件的字节数 |
| sha256 | 下载文件的 SHA-256 |
| downloaded_variant | original 或 large_sample |
| created_at | Danbooru 帖子创建时间 |
| archived_at | 本次入库时间 |
| score / fav_count | 选片时的 Danbooru 评分与收藏数 |
| selection_rank | 该作品在画师卡片内的排序（1–3） |
| attribution | 作者名称、Artist ID 和来源平台 |
| display_url | 网页卡片使用的 1600px WebP 显示副本路径 |
| display_variant | derived_1600_webp 或 original_fallback |
| display_mime_type | 显示副本的 MIME 类型，派生副本固定为 image/webp |
| display_width / display_height | 显示副本的实际像素尺寸 |
| display_file_size / display_sha256 | 显示副本的字节数与校验和 |
| display_source_sha256 | 生成显示副本时对应的原图 SHA-256 |
| display_generated_at | 显示副本生成时间 |

不要把 local_url 或 display_url 改成 Danbooru CDN 地址。local_url 是逐字节保存的原图归档，display_url 是供网页加载的派生副本，例如 assets/artists/63362/12268629.display.webp。卡片只加载 display_url，原图不会被访客浏览器下载。

`display_variant` 为 `original_fallback` 时表示源文件是动图或无法解码，此时 display_url 与 local_url 相同，卡片会回退到原图以保证不丢失动画或格式。

### 3.3 授权记录的意义

当前 8 位画师的作者再保存、上传及公开展示许可已经由仓库所有者确认。data/artworks.json 中的 permission 字段记录这一确认及时间。

这条记录是仓库所有者提供的确认信息，不是脚本自动向 Danbooru 或画师验证出来的法律授权证明。AI 不得自行推断新画师也拥有相同授权。

**新增任何画师前，必须先确认该画师对应作品允许被下载、复制、上传到公开 GitHub 仓库并由 GitHub Pages 展示。** 仅有 Danbooru 公开页面、General 标记、作者别名或可下载 URL 都不等于获得再托管许可。

当前同步脚本会为正式索引中的画师写入仓库所有者确认的许可记录。因此，不能把未经确认的画师先加入 artists.json 再指望系统自动阻止。没有明确授权时，不要把该画师加入会触发归档的正式索引。

---

## 4. Danbooru 作品发现与下载规则

核心实现位于 scripts/sync-artworks.mjs。

### 4.1 发现条件

脚本按画师的 danbooru_name（没有时使用 name）生成 artist tag，并请求 Danbooru Posts JSON API。核心查询逻辑相当于：

    <artist_tag> rating:g order:score

每位画师请求最多 120 条候选帖子，按 score 从高到低排序。筛选条件包括：

- rating 必须是 g，也就是 General。
- 帖子不能已删除。
- 必须有正数的图片宽度和高度。
- 必须提供 file_url 或 large_file_url。
- 文件扩展名必须是 jpg、jpeg、png、webp 或 avif（排除 gif，避免把动图原图拉进卡片）。

**当前策略是热度优先 + 去重，不是按时间取最新。** 脚本以 `order:score` 拉取最多 120 条 General 候选，按 score、fav_count、Post ID 依次排序；从高到低检查候选，跳过与已选作品构成差分的帖子，直到选满三张。

差分与近重复通过两层判断：

1. Danbooru 父子关系：父帖相同、互为父子，或向上三层内能连到同一祖先，视为同一组差分。
2. 感知哈希：下载 180×180 preview（仅用于比较，不提交），计算 8×8 dHash；与已选作品的汉明距离 ≤ 12 视为近似重复。

被跳过的候选会写入 manifest 的 `selection_detail.skipped_variants`，包含 post_id、score 和原因（`variant_of_*` 或 `similar_to_*`）。修改阈值时必须同时调整脚本常量、`selection_policy` 文案和本节说明。

### 4.2 图片来源优先级

每条候选帖子按以下顺序下载：

1. 原始文件 file_url，记录为 original。
2. 原图无法下载、超过单文件限制或文件检查失败时，尝试 large_file_url，记录为 large_sample。
3. 不使用 180×180 preview_file_url 作为仓库主展示图。

下载保留原文件字节，不进行压缩、裁切或格式转换。最终文件扩展名根据实际图片文件签名识别，而不是盲目相信 URL 后缀。

### 4.2.1 网页显示副本

原图动辄 1–13 MiB、数千万像素，直接解码会让页面卡顿。因此下载完成后必须运行 `python scripts/make-display-assets.py`：

- 从 local_url 指向的归档原图生成最长边 1600 px、WebP quality 85 的显示副本，命名 `<post_id>.display.webp`，与原图放在同一画师目录。
- 原图字节完全保留，不做任何修改；显示副本是额外的派生文件。
- 动图或无法解码的源文件回退为 original_fallback，不改变原始作品。
- 单张显示副本上限 4 MiB；超过上限同样回退原图。

### 4.3 请求与容量限制

当前脚本的限制：

| 项目 | 当前值 |
|---|---:|
| 每位画师查询候选帖子 | 最多 120 条 |
| 每位画师最终归档 | 恰好 3 张，且互不为差分 |
| 差分判定：dHash 汉明距离 | ≤ 12（64 位） |
| 单张图片最大文件 | 32 MiB |
| 整批归档最大文件总量（原图 + 显示副本） | 180 MiB |
| 单张显示副本最大文件 | 4 MiB |
| 显示副本最长边 / 质量 | 1600 px / WebP 85 |
| 不同画师请求间隔 | 约 1.2 秒 |
| 连续作品下载之间隔 | 约 0.3 秒 |

脚本设置了可识别的 User-Agent，并仅接受 HTTPS Danbooru 域名及其子域名作为图片下载来源。

下载后会检查：

- HTTP 响应是否成功。
- 响应体是否为空、是否超过大小上限。
- Content-Type 是否合理。
- 文件二进制签名是否确实是支持的图片格式。
- 图片文件的实际字节数。
- API 返回的宽高元数据是否有效。

如果某张候选作品下载失败，脚本会记录 warning 并跳过该候选，继续检查下一条；如果某位画师最终凑不满三张不重复的作品，整个同步任务失败，不会进入 GitHub 提交步骤。

当前总归档上限为 180 MiB，校验器会把原图与显示副本一起计算。同步脚本会为每张作品预留 1 MiB 显示副本额度，避免原图刚好占满上限后校验失败。不要为了绕过限制而无审查地提高容量；调整限制前应先检查仓库体积、Pages 发布大小和下载可靠性。

### 4.4 清理规则

每次成功同步都会重新生成完整 artworks manifest，并按当前正式画师目录清理旧图片：

- 每位仍在 artists.json 中的画师目录，只保留本次选中的三张原图与对应显示副本。
- 不再属于正式索引的 Artist ID 目录会被删除。
- 已存在但不再入选的旧 Post 图片会被删除。
- `make-display-assets.py` 会清除 manifest 未引用的 `.display.webp` 文件。
- 如果同步未成功，GitHub Actions 不会执行归档提交步骤。

**注意：从 artists.json 删除画师后，下一次成功归档会清除其图片目录。** 删除前先确认这是预期行为；如需保留历史图片，应先修改清理策略和校验器。

---

## 5. 前端如何读取本地图片

前端位于 docs/index.html。

公开页面启动时会读取：

1. data/artists.json：画师名称、身份、分类、标签、备注等信息。
2. data/artworks.json：该画师的三张本地作品路径和来源 Post ID。

前端根据 artist_id 匹配归档记录，默认读取 artwork.display_url（最长边 1600 px 的 WebP 显示副本）；只有显示副本缺失或标记为 original_fallback 时才读取 local_url。作品链接打开对应的 Danbooru 原帖；DANBOORU PROFILE 链接打开 Artist 主页。

公开卡片不会为每位画师实时调用 Danbooru Posts API 获取主图。管理弹窗在搜索新 Artist、预览候选作品时仍会向 Danbooru API 发出请求；这属于管理流程，不是公开图鉴的图片加载来源。

### 图片加载策略

- 第一张卡片使用 `loading="eager"` 和 `fetchpriority="high"`；其余卡片 `loading="lazy"`，不进入视口不下载。
- IntersectionObserver 在卡片接近视口时预取下一张作品，并在 `requestIdleCallback` 中执行，避免和首屏渲染争抢主线程。
- 悬停或键盘聚焦卡片时预取该卡片全部三张显示副本，点击箭头或圆点时基本无需等待。
- 切换作品时通过 `img.decode()` 等待新图解码，旧图保持显示直到解码完成，不会出现空白闪动；新图解码失败时回退原图，再失败才展示错误状态。
- 切换成功后播放一次方向相关的交叉动画：旧帧由底层 ghost 图层滑出淡出，新帧滑入淡入（约 450 ms，只动 opacity/transform）。旧帧在动画结束前始终兜底显示，即使标签页被节流也不会出现空白；`prefers-reduced-motion` 下直接瞬时切换。
- 预加载缓存只有 8 个条目，避免解码后的位图无限占用内存。
- 环境模糊背景只在主图加载完成后设置，离屏卡片不会提前发起图片请求。
- 原图从不进入网格加载路径；需要原图时使用卡片上的 Danbooru 原帖链接。

卡片布局可以在工具栏切换每行 2 / 3 / 4 列，默认 3 列，选择保存在 localStorage（artistAtlasColumnsV2）。每张卡片有最小宽度（320 px），窗口变窄时会自动减少实际列数，保证可读性；窄屏会隐藏该控件。卡片正文展示 Danbooru 作品总数（danbooru_post_count）与常用别名，别名最多显示 3 个，完整列表放在 title 中。

图片无法读取时，卡片会展示错误状态和画师主页链接。不要通过回退到 180×180 小缩略图来掩盖仓库路径或部署问题。

所有画师共用统一卡片结构。新增画师只增加数据记录和图片目录，不为某位画师另写专属 HTML/CSS/JS。

### 浏览器本地状态

- 收藏：localStorage。
- 主题：localStorage。
- NAI5 组合与强弱：当前页面会话内存，刷新后不保证保留。
- GitHub Token：管理窗口连接后存入 sessionStorage；不要读取、打印、截图、提交或向其他 AI 泄露 Token。

---

## 6. 自动化工作流

### 6.1 主流程：sync-artworks.yml

文件：.github/workflows/sync-artworks.yml

这个工作流同时负责作品归档和 GitHub Pages 发布。

触发方式：

- main 分支任何 push 都会启动此工作流。
- Actions 页面手动运行（workflow_dispatch）会强制重新同步作品。
- 每周一 UTC 03:17 定时运行。

Push 触发后会检查本次提交修改的路径：

| 本次变化 | 是否重新下载作品 |
|---|---|
| data/artists.json | 是 |
| scripts/sync-artworks.mjs | 是 |
| scripts/image-signature.py | 是 |
| scripts/make-display-assets.py | 是 |
| scripts/validate-artworks.mjs | 是 |
| .github/workflows/sync-artworks.yml | 是 |
| 只有 README、前端样式或其他普通文件变化 | 否，仍会校验并部署 |

正常执行顺序：

1. Checkout main 完整历史。
2. 判断是否需要刷新作品归档。
3. 如需刷新，安装 Python 与 Pillow（差分判定和显示副本生成都要用）。
4. 运行 scripts/sync-artworks.mjs：按 score 拉取候选、排除差分、下载三张原图。
5. 运行 python scripts/make-display-assets.py 生成 WebP 显示副本。
6. 运行 scripts/validate-data.mjs。
7. 运行 scripts/validate-artworks.mjs。
8. 只有两个校验成功，才将 data/artworks.json 和 docs/assets/artists/ 提交到 main。
9. 组装 Pages 静态站点：复制 docs/、data/artists.json 和 data/artworks.json。
10. 上传 Pages artifact。
11. 部署 GitHub Pages。

同步工作流拥有 contents: write、pages: write 和 id-token: write 权限，用来提交归档文件和部署站点。工作流使用 pages concurrency group 且 cancel-in-progress 为 false，避免并发发布互相取消。

由同步脚本自动提交的图片和 manifest 不会改变 artists.json；后续普通发布应跳过作品下载，只运行校验和部署。不要移除同步判断，否则每次普通 README 或 CSS 修改都会重新抓取所有图片。

### 6.2 质量检查：validate.yml

文件：.github/workflows/validate.yml

在 main 分支 push 和 Pull Request 时执行：

    node scripts/validate-data.mjs
    node scripts/validate-artworks.mjs

第一项检查 artists.json、旧兼容 JSON 的基本结构、重复 ID / 别名、URL、页面 DOM ID 和内联 JavaScript 语法。

第二项检查 artworks manifest、每位画师的三张作品、授权确认字段、来源 Post URL、本地路径与原图完整性，并校验每张作品的 WebP 显示副本存在、尺寸、字节数、文件签名和 SHA-256，以及原图 + 显示副本的总体积。

任何一项失败都应先修复，不能通过删掉校验步骤来“让 CI 变绿”。

### 6.3 手动发布备用流程：pages.yml

文件：.github/workflows/pages.yml

此工作流目前只有 workflow_dispatch 入口，是手动 Pages 部署备用方案。它会先执行两个验证脚本，再复制 docs、artists.json 和 artworks.json 并部署 Pages。

它**不会下载或更新图片**。只有归档已经处于 ready 且校验通过时，才使用此备用工作流发布网页。

日常首选 sync-artworks.yml。不要把 pages.yml 当成图片同步工作流。

---

## 7. 常见操作手册

### 7.1 新增一位画师

这是最重要的扩容流程：

1. 先在 Danbooru 核验准确 Artist 身份，确认 Artist ID、规范名称和别名。名称相似不代表同一画师。
2. 在添加前确认这位作者允许将其作品下载、重新保存、上传到公开 GitHub 仓库，并通过 GitHub Pages 展示。不要把“公开可看”当成授权。
3. 使用网页「管理图鉴」中的搜索功能，选中正确的 Danbooru Artist，填写图鉴显示名称、分类、别名、风格标签、个人评分和备注。
4. 保存后检查 data/artists.json 是否只新增了正确记录，内部 id 是否稳定，danbooru_id 是否唯一。
5. 提交到 main。artists.json 的变化会自动触发 sync-artworks.yml。
6. 在 Actions 中检查同步任务是否完成发现、下载、两个校验、图片提交和 Pages 部署。
7. 检查 docs/assets/artists/<Artist ID>/ 是否有三张原图和三个 `.display.webp`，检查 data/artworks.json 是否有对应 manifest 记录与 display 字段。
8. 打开在线页面强制刷新，确认图片是本地 display 路径、轮播三张作品正常、原帖链接正确，浏览器 Network 中不出现原图文件。

其他 AI 直接编辑仓库时，也必须遵守以上顺序。不要先写假图片 URL，也不要只在 artists.json 里伪造 preview_urls。

### 7.2 手动重新同步作品

优先通过 GitHub 网页操作：

1. 打开仓库 Actions。
2. 选择 Sync Authorized Artist Artwork。
3. 点击 Run workflow，目标分支选择 main。
4. 等待工作流完成。
5. 检查三个关键阶段：Discover and archive、Validate catalogue and archived image files、Deploy updated Artist Atlas。
6. 检查 data/artworks.json 的 updated_at、每位画师的三个 Post ID 以及图片目录。

手动运行会对当前所有正式画师重新按 score 选取作品并排除差分。它不是只刷新某一位画师的按钮。

### 7.3 本地运行同步

需要 Node.js 22 或兼容当前脚本所使用的原生 fetch、ES Module 能力，以及 Python 3.10+ 与 Pillow 10+（生成 WebP 显示副本）。需要运行机器能访问 Danbooru API 和 CDN。

    node --version
    python -m pip install "Pillow>=10"
    node scripts/sync-artworks.mjs
    python scripts/make-display-assets.py
    node scripts/validate-data.mjs
    node scripts/validate-artworks.mjs
    git status --short
    git diff --stat

本地运行只会在工作区生成或更新图片和 manifest，不会自动帮你执行 git commit / push。确认检查通过、变更范围正确后，再提交：

    git add data/artworks.json docs/assets/artists/
    git commit -m "Archive latest authorized artist artworks"
    git push origin main

如果只是本地修改页面、README 或其他不需要重新下载图片的文件，正常提交 push 即可；主同步工作流会跳过作品下载步骤，继续校验和发布。

### 7.4 删除一位画师

1. 在管理界面删除，或从 data/artists.json 移除对应记录。
2. 检查这是否也意味着删除其作品归档。
3. 提交到 main。
4. 同步脚本会重新构建 manifest，并清除不再属于正式画师的资产目录。
5. 检查 CI 和部署结果。

如果只想暂时隐藏画师但保留其图片，不要直接删除正式记录；应先设计明确的隐藏字段和清理策略。

### 7.5 修改卡片或页面样式

只修改 docs/index.html 及必要的说明文档。确保：

- 页面仍只有一个正式画师卡片网格。
- 所有画师使用同一模板。
- 不把候选池重新加回公开主页面。
- 作品图片仍通过 data/artworks.json 的 display_url 加载，原图保留在 local_url。
- 保留懒加载与解码调度：首屏只加载可见卡片的显示副本，切换作品时旧图保持到新图解码完成。
- 离屏卡片的骨架微光与加载指示不应持续播放动画；只在卡片进入视口时启用，避免无意义的重绘开销。
- 不重新引入以 Danbooru preview_file_url 作为主图的逻辑。
- 不为单个 Artist ID 添加专属样式分支。
- 保持每行 2 / 3 / 4 列的切换能力与 320 px 最小卡片宽度；不要用固定的 auto-fill 列宽覆盖用户选择。
- 保留页首 SVG 图标精灵与 keyed 局部渲染：只更换图库集合时才重建网格，不要退回“每次交互整页重绘”。
- 不要对大图主图使用 `filter: drop-shadow()`；大尺寸滤镜会明显拖慢移动端渲染。

修改后运行两个校验脚本，再提交。普通页面变化会触发检查和 Pages 部署，但不会重新抓取作品。

### 7.6 手动发布 Pages（备用）

只有归档 manifest 已经 ready、且两个校验脚本通过时才使用：

1. 打开 Actions → Deploy GitHub Pages。
2. 点击 Run workflow。
3. 选择 main 分支。
4. 等 validate 和 deploy 两个 job 成功。

这个工作流只发布已有文件，不会运行图片下载。

---

## 8. 本地校验与验收清单

每次涉及正式数据、图片或前端的改动至少检查：

    node scripts/validate-data.mjs
    node scripts/validate-artworks.mjs

归档校验通过的预期条件：

- manifest status 是 ready。
- 每个正式画师都有且只有一条归档记录。
- 每位画师恰好 3 张作品。
- Post ID 不重复。
- source_url 指向精确的 Danbooru Post。
- attribution 中的 Artist ID 与正式索引一致。
- permission.status 为 granted，confirmed_by 为 repository_owner。
- 每个 local_url 都位于对应 Artist ID 目录。
- 本地文件存在且大小匹配。
- 实际文件签名与 mime_type 匹配。
- SHA-256 与 manifest 一致。
- 每张作品都有 WebP 显示副本，display_source_sha256 与原图一致。
- 显示副本路径位于对应 Artist ID 目录、文件签名与 MIME 匹配、字节数与 SHA-256 一致。
- 原图 + 显示副本总大小不超过 180 MiB。

前端验收还应检查：

- 三位画师卡片均显示本地归档图片。
- 每张卡片可以在三张作品之间切换（箭头、圆点、键盘方向键、触摸滑动）。
- 图片按原始比例完整呈现，长图不被上下裁切。
- 360–430px 窄屏下头部操作、筛选控件和卡片底部按钮不溢出、不重叠，触控目标不小于 44px。
- 深色与浅色主题下的文字、边框、浮层和图片背景均可读。
- 点击作品打开正确的 Danbooru Post。
- 画师主页链接打开正确 Artist ID。
- 收藏、搜索、排序、主题和 NAI5 组合正常。
- 首次打开时只请求 `.display.webp`，不请求原图；卡片切换时旧图保留直到新图解码完成，没有空白闪动。
- 桌面和手机端没有第二个画师列表、布局错位或图片空白。

---

## 9. 故障排查

### 找不到三张作品

检查 Danbooru tag 是否准确、Artist ID 是否对应、是否有足够的 rating:g 图片帖子，以及最多 120 条按 score 排序的候选中是否存在合格文件。脚本不允许用 180×180 preview 凑数。

### 三张作品仍然太像（差分漏检）

先看 manifest 中 `selection_detail.skipped_variants` 是否记录了跳过项。若确实漏检，可能是差分之间没有父子关系、dHash 距离又刚好高于 12。可以适度提高 `VARIANT_HASH_DISTANCE`，但不要为了“看起来不同”而把阈值拉到会误杀不同作品的程度；调整后同时更新 README 与 selection_policy。

### 原图过大或下载失败

单文件上限 32 MiB。脚本会尝试 large_file_url；如果两者都无法下载，会继续检查其他高分候选。不要把 URL 改成 preview_file_url 来绕过限制。

### 显示副本缺失或页面仍加载原图

先确认已运行 `python scripts/make-display-assets.py`，再检查 data/artworks.json 中每张作品的 display_url 是否存在。如果 display_variant 是 original_fallback，说明源文件是动图或无法解码，页面会有意回退原图。不要手工伪造 display_sha256 或 display_file_size；应该重新生成。

### 首屏或切换作品仍然卡顿

1. 在浏览器 Network 面板确认卡片栏截的是 `.display.webp` 而不是 `.jpg/.png` 原图。
2. 确认 make-display-assets.py 生成的副本尺寸不超过 1600 px；如果改过 MAX_EDGE，需要重新生成全部副本。
3. 不要对主图添加 `filter: drop-shadow()` 等大尺寸滤镜，它会再次触发离屏栅格化。
4. 确认懒加载与预取逻辑未被绕过（离屏卡片不应提前请求环境背景）。

### 图片文件存在但页面不显示

依次检查：

1. data/artworks.json 中 local_url 是否正确。
2. 对应 docs/assets/artists/<Artist ID>/<Post ID> 文件是否真实存在。
3. Pages artifact 是否包含 docs/assets 和 data/artworks.json。
4. 图片相对路径是否以 docs/ 为基准正确。
5. GitHub Pages 是否已部署最新 commit。
6. 浏览器是否仍缓存旧页面；强制刷新后再检查 Network / Console。

### 校验器失败

根据错误类别排查。缺少图片、大小不匹配、文件签名不匹配或 SHA-256 不匹配时，重新下载或恢复正确文件；来源 URL、Artist ID 或本地路径错误时，修复 manifest。不要移除校验规则以掩盖问题。

### 页面发布成功但图片没更新

确认最新同步工作流中图片提交步骤成功，且 Deploy updated Artist Atlas 使用的是包含新 manifest 和本地图片的工作区。仅有一个较早的 Pages 成功记录，不代表最新图片已经发布。

---

## 10. GitHub Token 与安全要求

管理界面使用 GitHub Contents API 写入 data/artists.json。维护者使用 Fine-grained Personal Access Token 时建议：

- Repository access：Only select repositories。
- 只选择 artist-atlas。
- Contents：Read and write。
- 其他权限：No access。

Token 只允许保存在当前浏览器会话中。不得写入 README、脚本、Git 历史、Issue、日志、截图或提交内容。不要要求用户把 Token 直接发给 AI。

GitHub Actions 的同步工作流使用仓库级 workflow permissions；不要把写权限扩大到不必要的 scope。

---

## 11. AI 接手项目的工作规则

任何接手本仓库的 AI，都应遵循：

1. 先阅读 README，再读取 main 分支当前版本的目标文件；如果 README、ARCHITECTURE 和代码不一致，以实际代码和工作流为准，并修正文档。
2. 修改前确认当前分支、最新 commit 和工作流是否有正在运行的任务。不要在归档或 Pages 发布尚未完成时并发覆盖同一文件。
3. 将 data/artists.json 视为正式画师身份数据源，将 data/artworks.json 视为归档 manifest；不要混用历史 preview_urls 和本地高清图片路径。
4. 新增画师前核对 Artist ID，并确认作者允许重新保存、公开上传及展示。当前三位授权不能自动推导到其他作者。
5. 不要伪造 Post ID、原帖、图片 URL、授权字段、分辨率、文件大小或 SHA-256。
6. 不要将外部图片 URL 直接写成 local_url；local_url 必须对应真实存在于 docs/assets 的文件。
7. 不要未经用户要求恢复之前移除的 63 位画师，也不要重新引入候选池到公开主页面。
8. 修改下载规则、图片格式、大小上限、选图策略或清理行为时，必须同步检查校验器、manifest、工作流和本文档。
9. 提交前运行两个校验脚本，检查 git diff，确保没有 Token、无关图片、临时文件或意外的大批量删除。
10. 完成后给出实际 commit、Actions 运行状态和部署结果。工作流尚未结束时，不得声称已经成功部署。

### 推荐的交付回报格式

- 修改了哪些文件。
- 当前正式画师数量和归档图片数量。
- 两个校验脚本是否通过。
- 图片归档工作流是否成功。
- Pages 部署是否成功。
- 对应 GitHub commit 和 Actions 链接。
- 任何未完成项或限制。

---

## 12. 当前归档的核对记录

当前归档按「score 最高 + 排除差分」选出，8 位画师共 24 张图片，均使用 original 文件：

| 画师 | Post ID | Danbooru score |
|---|---|---|
| zhanzhan_lan | 7393663、7285602、5354639 | 58、48、46 |
| zhi_xu_li_ming | 8651495、7285475、8850377 | 25、23、21 |
| z3zz4 | 9554645、7993061、8478598 | 95、83、77 |
| dare_no_inarikami | 5411612、5613595、5172771 | 41、34、34 |
| dabaijiang_memeda | 5222946、5783656、10725966 | 58、40、25 |
| azling | 8438161、3131685、3960592 | 128、108、43 |
| road_233 | 7878821、7775178、9513467 | 61、45、43 |
| amejaga | 5877695、9020130、4511847 | 80、70、59 |

- 在线图鉴：https://tera-dark.github.io/artist-atlas/
- 首次归档（已被本轮选片取代，仅作历史参考）：commit 74edfd1828a90af6ddcf78e14717c9d668656613，工作流 44005634050。

这些记录反映的是本地工作区当前状态。每次推送后应重新检查最新 Actions 与 commit，不要把本表当成远端已部署的证明；远端是否更新以 Pages 部署记录为准。
