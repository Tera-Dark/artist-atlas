# Artist Atlas · 画师图鉴

**画师发现、作品采集与灵感整理工作台。**

Artist Atlas 是一个面向插画创作者与美术爱好者的本地工具，用于从画师推荐笔记中整理画师信息与作品链接，建立可浏览的个人参考库，并辅助核验画师身份。

> **项目形态说明：** 当前版本是运行在 Windows 本机的 Python 桌面/本地 Web 工具，不是纯静态网页。它需要本地 Python、Chrome/Chromium 和 Playwright；GitHub Pages 不能直接运行采集后端或访问本机浏览器。仓库先用于源码托管与项目介绍，在线演示/Pages 入口需要后续单独制作。

## 功能概览

- **画师发现：** 从小红书画师推荐类笔记中采集画师署名与作品信息。
- **作品归档：** 按画师整理作品，支持画师改名、合并与图片归属调整。
- **重复检测：** 结合图片 ID 与画面指纹，减少重复收录。
- **身份核验：** 对接 Danbooru，核对画师名称、别名与条目；不确定时保留候选，不擅自认定。
- **搜图辅助：** 可选接入 SauceNAO，为无法确认的条目提供反向搜图线索。
- **可视化浏览：** 提供画师卡片与在线图廊浏览方式。

## 从源码运行

\`\`\`powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python 工作台.py
\`\`\`

启动后，程序会在本机启动 Web 服务并尝试打开浏览器。详细操作请查看 [使用说明.md](使用说明.md)。

## 目录结构

\`\`\`text
artist-atlas/
├── 工作台.py
├── 工作台界面.html
├── 采集引擎.py
├── 语义映射.json
├── 测试套件.py
├── 应用图标.ico / .png / .svg
├── 使用说明.md
├── requirements.txt
└── .gitignore
\`\`\`

## 运行测试

\`\`\`powershell
python 测试套件.py
\`\`\`

随包测试套件包含 267 项检查。原始源码压缩包未包含部分被测试引用的 Windows 辅助文件（启动脚本、重新归类工具、快捷方式工具），因此这几项相关检查会因文件缺失而失败；其余测试可用于验证已提供模块。

## 隐私与版权

- 小红书登录态、采集结果、Danbooru / SauceNAO 凭证均应保存在本机，不要提交到公开仓库。
- 不要上传 `_profile/`、`_accounts/`、`账号.json`、`d站凭证.json`、`搜图凭证.json` 或个人采集数据。
- 本项目用于个人研究、画师发现与作品参考整理。采集到的作品版权仍归原作者所有。请尊重原作者署名、平台规则及作品授权范围，不要未经许可转载、商用或重新分发作品。

---

**Artist Atlas — Discover artists, collect inspiration, and build your own searchable art reference library.**
