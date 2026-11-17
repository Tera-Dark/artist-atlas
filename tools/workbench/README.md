# 采集工作台（旧版本地工具）

这是项目早期的本地采集工具：用浏览器自动化在小红书等站点收集画师线索，再人工整理成候选名单。它**不参与**在线图鉴的构建、归档和发布流程，也不读取 `data/artists.json`。

保留它的原因是：新增画师时，可以先用它把可疑线索攒起来，再逐个去 Danbooru 核对 Artist ID，最后通过图鉴的「管理图鉴」或直接编辑 `data/artists.json` 加入正式索引。

## 运行

```powershell
pip install -r tools/workbench/requirements.txt
python -m playwright install chromium
python tools/workbench/工作台.py
```

启动后浏览器会自动打开本地工作台界面（默认 http://127.0.0.1:8765）。

## 数据与隐私

- 登录态、凭证、采集结果都写在工作台所在目录（`_accounts/`、`采集结果/`、`*凭证.json`），已被 `.gitignore` 排除。
- **不要把凭证、Cookie、采集结果提交到仓库。**
- 工作台采集到的数据只是线索，不会自动同步到在线图鉴；身份必须以 Danbooru Artist 条目为准。
- 抓取第三方平台时请自行遵守该平台的用户协议与 robots 规则。

## 文件

| 文件 | 说明 |
|---|---|
| `工作台.py` | 本地服务 + 界面后端入口 |
| `工作台界面.html` | 单页界面 |
| `采集引擎.py` | 站点抓取逻辑 |
| `测试套件.py` | 本地自测脚本 |
| `语义映射.json` | 人工确认过的别名纠正规则 |
| `应用图标.*` | 桌面快捷方式与 favicon 资源 |
