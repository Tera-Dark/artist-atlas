# Artist Atlas · 画师图鉴

以作品为中心的个人画师索引：每位画师对应一个 Danbooru Artist，每张作品对应一个 Danbooru Post，网页只加载仓库里 1600 px 的 WebP 显示副本。

- 在线图鉴：<https://tera-dark.github.io/artist-atlas/>
- 仓库：<https://github.com/Tera-Dark/artist-atlas>
- 分支：`main`

当前规模：**71 位画师 / 213 张作品 / 约 37 MiB 图片**。名单以 `data/artists.json` 为准，作品以 `data/artworks.json` 为准。

> 这份 README 也是接手者的交接文档。改动前请先读完，再看当前 `main` 上的脚本与工作流；历史聊天摘要可能已经过期。

---

## 1. 它是什么

- 一片**正式**画师图鉴，只有一份网格、一套卡片模板；没有候选池、没有第二份列表。
- 每位画师固定收录 **3 张** Danbooru `rating:g` 作品：按 score 从高到低取，并排除差分（同一张画的微调版本）与近似重复。
- 作品图片归档在仓库里（`docs/assets/artists/<Artist ID>/<Post ID>.display.webp`），**只保存 1600 px WebP 显示副本**，不保存源文件。
- 公开页面不实时访问 Danbooru 图片 CDN；Danbooru 只用于管理流程中的身份查询、候选发现和原帖追溯。
- 不按单个 Artist ID 写特例卡片；新增画师只增加数据与图片目录。

边界：本项目不是下载站、排行榜，也不代表作品授权状态。**再托管必须有作者允许**，公开可见 ≠ 可以转载。

---

## 2. 目录结构

```
data/
  artists.json            正式画师索引（唯一画师数据源）
  artworks.json           作品归档清单（由同步脚本生成）
  artist.schema.json      artists.json 的结构定义

docs/
  index.html              站点：样式、脚本、数据渲染全部在这一个文件里
  GETTING-STARTED.md      面向使用者的说明
  ARCHITECTURE.md         实现细节（渲染、加载、差分、校验）
  assets/artists/
    <Artist ID>/          只放 <Post ID>.display.webp

scripts/
  sync-artworks.mjs       发现作品 → 差分排除 → 下载到暂存目录 → 逐位画师转换
  make-display-assets.py  暂存源文件 → 1600px WebP，删源文件，清理残留
  image-signature.py      180px 预览的 8×8 dHash，供差分判定
  validate-data.mjs       画师索引 + DOM id + 内联脚本语法
  validate-artworks.mjs   归档清单 + 显示副本完整性 + 总量预算

tools/workbench/          早期本地采集工具（不参与构建，见其中 README）

.github/workflows/
  sync-artworks.yml       归档 + 提交 + 部署 Pages（定时/手动/触发路径变化）
  validate.yml            每次 push 与 PR 的数据校验
  pages.yml               手动发布 Pages 的备用入口
```

权威性：`artists.json` 是画师身份的唯一来源；`artworks.json` 是作品与图片的唯一来源；`docs/assets/artists/` 只允许出现 `.display.webp`。

---

## 3. 本地开始

```bash
node --version                 # 需要 Node 22+
python -m pip install -r requirements.txt   # Pillow，用于差分哈希与 WebP 转换

node scripts/validate-data.mjs
node scripts/validate-artworks.mjs
```

本地看页面（模拟 Pages 的目录结构：站点根 = `docs/`，外加 `/data/`）：

```bash
node -e "
const http=require('http'),fs=require('fs'),path=require('path');
http.createServer((q,s)=>{
  let u=decodeURIComponent(q.url.split('?')[0]);
  if(u==='/')u='/index.html';
  const f=u.startsWith('/data/')?path.join('data',u.slice(6)):path.join('docs',u);
  if(!fs.existsSync(f)||!fs.statSync(f).isFile()){s.writeHead(404);return s.end();}
  s.writeHead(200,{'Content-Type':{'html':'text/html; charset=utf-8','json':'application/json','webp':'image/webp','svg':'image/svg+xml','md':'text/markdown; charset=utf-8'}[path.extname(f).slice(1)]||'application/octet-stream'});
  fs.createReadStream(f).pipe(s);
}).listen(8080,'127.0.0.1',()=>console.log('http://127.0.0.1:8080/'));
"
```

全量重跑归档（会按当前 score 重新选片，约 700 MiB 源文件流量，仓库只增加显示副本）：

```bash
node scripts/sync-artworks.mjs
python scripts/make-display-assets.py
node scripts/validate-data.mjs && node scripts/validate-artworks.mjs
```

源文件默认落在系统临时目录的 `artist-atlas-staging`，可用 `ATLAS_STAGING=<dir>` 指定。网络中断时加 `ATLAS_RESUME=1` 重跑：已归档且副本完整的画师直接复用，不再下载。CI 不设置该变量，所以定时任务始终重新选片。

---

## 4. 数据模型

### 4.1 `data/artists.json`

顶层：`version`（固定 1）、`updated_at`、`artists`。

| 字段 | 说明 |
|---|---|
| `id` | 内部稳定 ID，`artist-<Artist ID>` |
| `name` | 图鉴显示名 |
| `danbooru_id` | Danbooru Artist ID，正整数字符串 |
| `danbooru_name` | Danbooru 规范名 / artist tag |
| `aliases` | 别名数组，参与搜索 |
| `category` | 个人分类；空或「未分类」时卡片不显示角标 |
| `tags` | 个人风格标签 |
| `score` | 个人评分 1–10 或 `null` |
| `note` | 个人备注 |
| `added_at` / `updated_at` | ISO 时间 |

只允许以上字段，多一个都会被 `validate-data.mjs` 拒绝。图片、作品数、Danbooru 总数都不写在这里。

### 4.2 `data/artworks.json`

顶层：`version`、`status`、`updated_at`、`selection_policy`、`storage_policy`、`display_policy`、`display_updated_at`、`artists`。

每位画师记录：`artist_id`、`artist_record_id`、`artist_name`、`artist_tag`、`danbooru_name`、`danbooru_post_count`、`danbooru_aliases`、`facts_updated_at`、`selection`、`selection_detail`（候选池大小、阈值、被跳过的差分）、`permission`、`artworks`。

每张作品：

| 字段 | 说明 |
|---|---|
| `id` / `post_id` | Danbooru Post ID |
| `source_url` | 原帖地址 |
| `source_file_url` / `source_file_ext` | 源文件 CDN 地址与扩展名 |
| `source_mime_type` / `source_file_size` | 源文件类型与字节数（文件不保留） |
| `source_sha256` / `source_md5` | 追溯与「是否需要重新下载」判断 |
| `image_width` / `image_height` / `created_at` | 源图元数据 |
| `score` / `fav_count` / `selection_rank` | 选片依据 |
| `attribution` | 作者名、Artist ID、来源平台 |
| `display_url` | **网页唯一加载路径**，`assets/artists/<Artist ID>/<Post ID>.display.webp` |
| `display_variant` | 固定 `derived_1600_webp` |
| `display_mime_type` / `display_width` / `display_height` | 副本元数据 |
| `display_file_size` / `display_sha256` | 副本大小与校验和 |
| `display_source_sha256` | 生成副本时对应的源文件 SHA-256 |
| `display_generated_at` | 副本生成时间 |

`display_url` 不得换成 Danbooru CDN 地址；需要原始分辨率请走原帖链接。

---

## 5. 作品归档流水线

核心：`scripts/sync-artworks.mjs` → `scripts/make-display-assets.py` → 两个校验脚本。

1. **发现**：按 `danbooru_name` 生成 artist tag，请求 `<tag> rating:g order:score`，最多 120 条；要求未删除、有宽高、有 `file_url`/`large_file_url`、扩展名是 jpg/jpeg/png/webp。按 score、fav_count、Post ID 排序。
2. **差分排除**（两层）：
   - Danbooru 父子关系：父帖相同、互为父子，或向上三层能连到同一祖先；
   - 8×8 dHash：下载 180 px 预览（仅用于比较）算哈希，与已选作品汉明距离 ≤ 12 视为近似重复。
   跳过项写入 `selection_detail.skipped_variants`（原因 `variant_of_*` / `similar_to_*`）。
3. **下载到暂存目录**：优先 `file_url`，失败或超限时用 `large_file_url`；校验状态码、大小、MIME、二进制签名，算 `sha256`/`md5`。源文件从不进入仓库。
4. **逐位画师转换**：每选完一位画师就调用一次 `make-display-assets.py --only <Artist ID>`，把源文件转成最长边 1600 px、quality 85 的 WebP（单张 ≤ 4 MiB），写入 `docs/assets/artists/<Artist ID>/<Post ID>.display.webp`，更新 manifest，删除该画师的暂存源文件。这样中断后可以续跑。
5. **清理**：manifest 未引用的 `.display.webp`、已移除画师的目录、旧流程遗留的源文件都会被删除。
6. **校验**：`validate-data.mjs` + `validate-artworks.mjs` 全部通过才允许提交。

限制常量（改任何一项都要同步 manifest 文案与文档）：

| 项目 | 值 |
|---|---:|
| 每位画师候选上限 | 120 |
| 每位画师归档 | 恰好 3 张，互不为差分 |
| dHash 汉明距离阈值 | 12 |
| 单张源文件下载上限 | 32 MiB |
| 显示副本最长边 / 质量 | 1600 px / WebP 85 |
| 单张显示副本上限 | 4 MiB |
| 整库显示副本预算 | 120 MiB（项目自定，非 GitHub 限制） |
| 画师间隔 / 作品间隔 | 0.7 s / 0.2 s |

预算说明：120 MiB 只是项目自己的预算，不是 GitHub 硬限制（GitHub 为单文件 100 MB、仓库建议 ≤1 GB、Pages 站点 ≤1 GB）。调整前先看仓库体积。

失败语义：某张候选下载失败会跳过并继续；某位画师凑不满 3 张不重复的作品，整次同步失败，工作流不会提交图片。

授权：`permission` 字段记录仓库所有者确认「作者允许再保存、转换与公开显示」。它不是脚本验证出的法律许可；新增画师前必须由人确认，AI 不得自行推断。

---

## 6. 前端

`docs/index.html` 是唯一页面文件，启动时读取 `data/artists.json` 与 `data/artworks.json`，按 `artist_id` 合并。

- **加载**：首张 `loading="eager"` + `fetchpriority="high"`，其余 `lazy`；IntersectionObserver（260 px 预取距离）在 `requestIdleCallback` 里预取下一位作品；悬停/聚焦预取整卡三张。
- **切换**：`img.decode()` 后替换，旧帧保留到新帧解码完成；底部 ghost 图层做方向相关的滑动淡出（约 450 ms，只动 opacity/transform），`prefers-reduced-motion` 下瞬时切换；预加载缓存上限 8。
- **离屏卡片**：骨架微光和「读取中」脉冲只在 `data-inview="true"` 时播放，避免几十张卡片一起跑无限动画。
- **列数**：工具栏可切 2 / 3 / 4 列，默认 3；卡片最小宽度 320 px，窗口变窄自动减列，≤720 px 隐藏控件。
- **大图**：点击卡片打开弹窗，适应 / 100% / 200% 缩放，可拖动；左右按钮与方向键换图并同步卡片轮播；弹窗内保留「原帖」入口。Ctrl/Cmd/中键仍然直接开 Danbooru。
- **卡片信息**：Danbooru 作品总数（`danbooru_post_count`）、已收录数、最多 3 个别名（完整列表在 `title`）、个人评分或「已核验」标记。

本地状态：收藏 `artistAtlasFavoritesV2`、主题 `artistAtlasThemeV2`、列数 `artistAtlasColumnsV2`（均为 localStorage）；NAI5 组合只存在内存；GitHub Token 存在 sessionStorage。

不要在网格里引入 `filter: drop-shadow()` 之类的大尺寸滤镜，也不要回退到 180 px 预览图。

---

## 7. 自动化

| 工作流 | 触发 | 作用 |
|---|---|---|
| `sync-artworks.yml` | push main、手动、每周一 UTC 03:17 | 判断是否需要刷新归档 → 同步 → 转换 → 校验 → 提交 `data/artworks.json` + 图片 → 部署 Pages |
| `validate.yml` | push main、PR | 只跑 `validate-data.mjs` 与 `validate-artworks.mjs` |
| `pages.yml` | 手动 | 不重新下载，直接发布当前文件 |

push 触发时，只有改动命中 `data/artists.json`、`scripts/sync-artworks.mjs`、`scripts/image-signature.py`、`scripts/make-display-assets.py`、`scripts/validate-artworks.mjs` 或工作流自身才会重新下载作品；改 README/CSS/文档只校验并部署。

工作流用 `contents: write` + `pages: write` + `id-token: write`，`concurrency: pages` 且不取消进行中的发布。归档提交只 `git add data/artworks.json docs/assets/artists/`。

---

## 8. 运维手册

**新增一位画师**：核验 Artist ID 与别名 → 确认授权 → 用「管理图鉴」搜索并保存，或直接改 `data/artists.json` → `node scripts/validate-data.mjs` → 提交。工作流会自动补齐 3 张作品、图片和部署。

**删除一位画师**：从 `artists.json` 移除 → 提交 → 下次同步会删掉该 Artist 目录与 manifest 记录。删除前确认这是预期行为。

**重新同步作品**：Actions → Sync Authorized Artist Artwork → Run workflow。它会按当前 score 对全部画师重新选片，不是单画师刷新。

**只想改样式**：只动 `docs/index.html`，`validate-data.mjs` 会检查 DOM id 重复、`$("id")` 引用和脚本语法。

**手动发布**：Actions → Deploy Artist Atlas Pages。

排查：

- *找不到三张作品*：tag 是否准确、Artist 是否被删、120 条候选里是否有足够合格图片；脚本不会用 180 px 预览凑数。
- *三张仍太像*：看 `skipped_variants`；确实漏检可调 `VARIANT_HASH_DISTANCE`，但别调到大范围误杀。
- *副本缺失*：确认同步把源文件下载到了暂存目录、随后跑了转换脚本；不要手工伪造 `display_sha256`。
- *页面图片不显示*：检查 `display_url` 对应文件是否存在、Pages artifact 是否包含它、部署是否最新、是否缓存。
- *首屏卡顿*：Network 里确认只有 `.display.webp`；确认副本 ≤1600 px；确认没用大尺寸滤镜。
- *校验失败*：按报错修数据或重跑同步，不要删检查规则来“过”。

---

## 9. 安全与协作

- 管理窗口用 Fine-grained PAT：仅 `Tera-Dark/artist-atlas`，仅 `Contents: Read and write`。Token 存在 sessionStorage，刷新页面即失效。
- 任何凭证、Cookie、账号数据、采集结果都不得出现在仓库、日志、截图、提交信息或对话里。
- 授权只针对已确认的画师；旧确认不会自动推导到新画师。
- 改下载规则、格式、容量、选片策略或清理行为时，必须同时更新脚本常量、manifest 文案、`README.md` 与本目录下的文档。
- 交接时如实报告 commit、Actions 状态与部署结果；工作流没跑完不要说已经上线。

---

## 10. 记录

- 首次归档：`74edfd1828a90af6ddcf78e14717c9d668656613`（旧策略：最新三张 + 保留源文件），仅作历史参考。
- 71 位画师扩容与 WebP-only 归档：`e0a3766`，随后由 CI 生成 `8aaea07`。
- 核对方式：`validate-artworks.mjs` 输出画师数、图片数与副本总量；线上以 Pages 部署记录为准。
