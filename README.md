# Artist Atlas · 画师图鉴

**画师发现、作品采集与灵感整理工作台。**

Artist Atlas 是面向插画创作者与美术爱好者的 Windows 本地工具：从画师推荐笔记整理画师信息与作品链接，建立可浏览的个人参考库，并辅助核验画师身份。

> GitHub Pages 提供项目介绍和使用文档。采集工作台依赖本机 Python、Chrome/Chromium 与 Playwright，页面本身不会在线采集，也不会访问你的本机浏览器。

**项目主页：** <https://tera-dark.github.io/artist-atlas/>

## 功能

- 从小红书画师推荐类笔记中整理画师署名与作品信息。
- 按画师归档作品，支持改名、合并与图片归属调整。
- 结合图片 ID 与画面指纹减少重复收录。
- 可选连接 Danbooru 核验画师名称与条目；不确定时保留候选。
- 可选接入 SauceNAO，为无法确认的条目提供反向搜图线索。
- 通过画师卡片与在线图廊浏览个人参考库。

## 从源码运行

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python 工作台.py
```

详细操作、配置方法和常见问题见 [使用说明](使用说明.md)。源码目录中的 `测试套件.py` 可用于本地检查。

## 目录结构

```text
artist-atlas/
├── .github/workflows/pages.yml
├── docs/index.html             # GitHub Pages 静态介绍页
├── 工作台.py                   # 本地服务入口
├── 工作台界面.html             # 本地工作台前端
├── 采集引擎.py
├── 测试套件.py
├── 语义映射.json
├── 应用图标.ico / .png / .svg
├── 使用说明.md
└── requirements.txt
```

## 隐私与版权

- 小红书登录态、采集结果、Danbooru / SauceNAO 凭证均应保存在本机，不要提交到公开仓库。
- 不要上传 `_profile/`、`_accounts/`、`账号.json`、`d站凭证.json`、`搜图凭证.json` 或个人采集数据。
- 采集到的作品版权归原作者所有。请遵守平台规则和作品授权范围，不要未经许可转载、商用或重新分发作品。
