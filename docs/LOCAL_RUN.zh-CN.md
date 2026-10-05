# 本地运行

[English](LOCAL_RUN.md) | **简体中文**

[项目介绍](../README.zh-CN.md) · [当前功能](CURRENT_PRODUCT.zh-CN.md) · [模型测试](MODEL_SELECTION.zh-CN.md) · [下载数据](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

看案例不需要安装。要自己提问，需要运行本地服务，并使用自己的模型 API Key；数据查询模式无需模型密钥。

## 首次安装

建议使用 Python 3.13。[完整安装记录](handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md)使用 macOS 和 Python 3.13.3。会话与报告存储依赖 POSIX 的 `fcntl` 模块，当前不支持原生 Windows。

克隆当前 main 分支并创建项目环境。下面两次版本检查应输出 Python 3.13.x：

```bash
git clone https://github.com/Yemyu/TradeIntel.git
cd TradeIntel
python3.13 --version
python3.13 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
```

在 [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002) 下载 `trade-demo-data-20260927-isolated-v2.zip`。包内有124份加工数据文件，ZIP 约64 MiB，解压后约579 MB；克隆仓库不会同时下载该包。ZIP 还含 `BUNDLE_MANIFEST.json` 和一份中文说明，没有项目源码、原始 Census 压缩包、模型密钥、MySQL 数据库或政策文档数据库。

将 `/path/to/` 换成下载文件所在目录，在 macOS 核对 ZIP 的 SHA-256：

```bash
shasum -a 256 "/path/to/trade-demo-data-20260927-isolated-v2.zip"
```

摘要应为：

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

在仓库根目录，把数据解到 `.local/` 下的新目录，Git 会忽略该目录；随后核验：

```bash
mkdir -p .local
unzip "/path/to/trade-demo-data-20260927-isolated-v2.zip" -d ".local/trade-data-bundle-1"
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root ".local/trade-data-bundle-1"
```

返回 `"status": "verified"` 后继续。`--root` 和 `--trade-data-root` 都指向同时包含 `BUNDLE_MANIFEST.json` 和 `data/` 的目录；已解好的目录包可以直接按同样步骤核验使用。核验在离线环境下完成。

## 启动网页

```bash
.venv/bin/python scripts/run_web.py --trade-data-root ".local/trade-data-bundle-1"
```

打开 `http://127.0.0.1:8765/preview/`。终端需要保持运行，Ctrl-C 停止服务。端口被占用时，选择空闲端口：

```bash
.venv/bin/python scripts/run_web.py --port 8898 --trade-data-root ".local/trade-data-bundle-1"
```

对应地址为 `http://127.0.0.1:8898/preview/`。服务用于本机运行，默认监听 `127.0.0.1`。

## 配置模型

在聊天页面打开“模型设置”：

1. 选择取得密钥的平台：智谱 GLM、DeepSeek 或千问。
2. 选择预设型号，或输入该平台支持的型号 ID。页面目前为 DeepSeek 提供推理设置。
3. 填入自己的 API Key 并保存。密钥由本地服务保存，不发布到展示网站；同平台换型号可以保留密钥，换平台需新密钥。
4. 可选“测试连接”：它发送短请求，服务商可能收费。成功表示连接可用，报告质量另行评估。

保存设置、看案例和读已有报告不发模型请求。助手提交问题会调用所选平台，并向其发送问题和工具查询结果，按服务商规则计费。

[模型测试](MODEL_SELECTION.zh-CN.md)中的 GPT 成绩来自 Codex 聊天，不代表本应用已支持 GPT API。

## 提问与读报告

先问“最近美国大豆进口有什么变化？”，完成后接着问“出口呢？”。用底部“发送”或 Enter 提交；Shift+Enter 换行。打开回复下方的报告卡片，查看图表和逐月金额，再返回聊天继续追问。

换商品时直接说“改看豆油进口”。商品或范围有歧义时需要确认。选择“数据查询”则由你确认商品、方向和月份，不需要模型密钥。

对话和报告可在刷新后恢复。查看案例、打开报告和切换语言不会重新发送请求；页内往返保留未发送草稿，整页刷新不保存草稿。

## 查看已保存案例

[公开网站](https://yemyu.github.io/TradeIntel/?lang=zh)可以直接阅读四个已保存的对话和图表，无需安装。从源码副本阅读时，在仓库根目录执行：

```bash
python3.13 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

打开 `http://127.0.0.1:8000/`。这个静态预览不需要贸易数据包或API Key，只展示已保存案例；自己提问时使用上方的本地应用。

## 维护已有安装

复用项目的 `.venv`，用 `.venv/bin/python --version` 核对解释器。`requirements.txt` 变更时，用 `.venv/bin/python -m pip install -r requirements.txt` 更新该环境。

更新数据包时，解到新目录并核验，再将 `--trade-data-root` 指向新目录重启服务。保留上一版数据包用于回退。

GitHub Pages CI 使用 Python 3.12 和标准库构建静态展示页；这项检查与 Python 3.13.3 的完整本地安装记录不同。

## 数据与常见问题

- **“最近”到哪一天？** 目前末月是2026年7月，不是实时数据。进口有48个不连续月份，出口为2025年8月至2026年7月。
- **所问月份没有数据怎么办？** 页面提示缺口；需要改查其他月份时请明确提出，不会自动用最新可用月替代。
- **金额等于数量吗？** 不等于。金额可能受数量和价格共同影响；报告不直接推断政策效果。
- **启动失败？** 检查数据根目录、核验结果和端口。数据包核验失败时，核对 ZIP 摘要，再解到一个新目录。
- **模型请求失败？** 检查服务地址、型号和密钥；未知结果不会自动重复请求，避免重复费用。
- **为什么没有政策检索结果？** 只有已登记并启用的公告能检索，贸易数据包不提供完整政策库。展示页的编辑报告不等于新登记的政策文档。

[macOS 安装核验记录](handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md) · [展示页说明](PUBLIC_SHOWCASE.zh-CN.md) · [公开网站](https://yemyu.github.io/TradeIntel/?lang=zh)
