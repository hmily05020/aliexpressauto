# AliExpress 店小秘自动上架助手

这是一个用于店小秘速卖通采集箱商品自动编辑的桌面工具。当前主版本使用 Python、Tkinter 和 Playwright 连接 Chrome 调试端口完成页面自动化。

## 主要能力

- 连接本机 Chrome 远程调试端口 `9222`
- 从店小秘速卖通采集箱按顺序打开商品编辑页
- 支持采集箱搜索词过滤后批量处理
- 自动选择类目、属性模板、运费模板、服务模板
- 批量填写 SKU 价格、货值、库存、重量、尺寸、物流属性
- 支持单 SKU 和多 SKU 物流属性填写
- 详情图保留/删除策略可配置
- 产品视频可选择保留或删除
- AI 文本优化标题和 SKU 名称，并提取车型、年份、产品属性
- AI 主图换背景，支持火山 Seedream / GeekNow 等图片接口
- 海关监管支持按预设下拉、仅点击添加/更新、完全跳过
- 支持立即发布或保存并移入待发布

## 源码结构

```text
automation_gui.py        # Tkinter GUI
main_automation.py       # Playwright 自动化主流程
config.py                # 默认配置和运行时配置加载
requirements.txt         # Python 依赖
ShopAutomationGUI.spec   # PyInstaller 打包配置
assets/                  # 图标资源
```

## 本地运行

```bash
pip install -r requirements.txt
python automation_gui.py
```

程序会在用户文档目录创建运行数据：

```text
%USERPROFILE%\Documents\ShopAutomationGUI\
```

其中 `runtime_config.json` 保存用户自己的参数和 API Key。这个文件不会提交到仓库。

## 打包 Windows EXE

```bash
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ShopAutomationGUI --icon "assets\ae_icon.ico" --add-data "assets;assets" --collect-data playwright --hidden-import main_automation --hidden-import config --hidden-import playwright.async_api --hidden-import PIL.Image --hidden-import PIL._tkinter_finder automation_gui.py
```

打包产物位于 `dist/`，不会提交到仓库。

## 配置和安全

仓库不包含任何 API Key、登录 Cookie、Chrome 用户资料、运行日志、截图、输出图片或打包产物。以下内容会被 `.gitignore` 排除：

- `runtime_config.json`
- `automation.log`
- `last_error_traceback.log`
- `output/`
- `chrome-debug-profile/`
- `build/`
- `dist/`
- `*.exe`
- `*.zip`
- `*.rar`
