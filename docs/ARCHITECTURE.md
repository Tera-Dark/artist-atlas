# Artist Atlas · 前端与数据结构

> 当前状态：三位画师的统一卡片验收版

## 产品边界

Artist Atlas 是个人画师与视觉参考档案。它只维护一份正式画师索引，不在公开浏览页展示候选列表、核验批次或第二套作品目录。

当前验收数据仅保留三位画师：zhanzhan_lan、zhi_xu_li_ming、z3zz4。验收完成前，不恢复旧名单，也不执行批量导入。

## 单一数据流

data/artists.json
       |
       v
页面读取唯一正式索引
       |
       +---- Danbooru Posts API
       |       最新 3 张 rating:g 作品
       |       large_file_url 优先，其次 file_url
       |
       v
统一画师卡片与作品轮播
       |
       +---- 本地收藏 / 主题 / NAI5 组合
       |
       +---- 管理弹窗
                 |
                 v
       GitHub Contents API 写回
                 |
                 v
       data/artists.json
                 |
          CI 校验 / Pages 部署

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
- 每位画师最多展示 3 张最新 General 作品。
- 作品展示优先使用 Danbooru 的 large sample，缺少 sample 时使用原图；不将 180×180 preview 用作主展示。
- 图片保持原始长宽比完整显示，不使用强制裁切。
- 左右按钮和圆点控制同一卡片内部的作品索引。
- 点击作品打开对应 Danbooru Post；资料入口打开 Artist 页面。
- 图片请求失败时展示明确的错误提示与 Artist 主页链接。

## 状态与持久化

浏览器本地状态：
- 收藏列表：localStorage。
- 主题偏好：localStorage。
- NAI5 组合与强弱：当前页面会话内存。

仓库正式资料：
- 画师名称、别名、Danbooru Artist ID。
- 分类、风格标签、个人评分与备注。
- 作品 Post ID 和来源 URL。
- 添加与更新时间。

不将远程作品文件下载或重新托管到仓库。

## 管理流程

管理弹窗使用 Fine-grained GitHub Token 访问 Contents API。建议仅授权本仓库的 Contents Read and write 权限。

提交前重新读取远端文件并比对 blob SHA；若远端已有其他修改，则停止写入并要求刷新，避免覆盖并发更新。

## 质量检查

使用 node scripts/validate-data.mjs 检查正式数据、重复身份、DOM ID、页面脚本语法。

GitHub Actions 在 main 分支推送和 Pull Request 时执行校验。GitHub Pages 发布工作流应在部署前执行同一校验。

## 后续扩容原则

只有在三张卡片的作品清晰度、信息层级、桌面与移动端布局、轮播与管理流程完成验收后，才恢复完整名单。扩容时只增加正式索引数据，不为单个画师写专属卡片结构。
