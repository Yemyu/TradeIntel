# TradeIntel

[English](README.md) | **简体中文**

[案例演示](https://yemyu.github.io/TradeIntel/?lang=zh) · [快速开始](#快速开始) · [模型测试](docs/MODEL_SELECTION.zh-CN.md) · [下载数据](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

TradeIntel 是一个美国商品贸易 AI 研究助手。用商品名称或编码提问，可以查询进出口、比较不同月份，也可以接着追问或查阅相关政策。模型负责选择查询工具，程序读取贸易数据、计算金额，并生成带图表和出处的报告。

公开网站提供四个已保存的案例。要自己提问，可以在本机运行项目，配置自己的模型 API；不配置模型时，也能手动选定范围，生成数据报告。本地使用不需要购买云服务器，也不要求连接 MySQL。

## 功能

- **找商品**：按名称或官方编码检索商品目录。确有歧义时会询问，不把相近商品自动当成同一种。
- **查进出口**：分别查看进口和出口，比较已有月份，查询全部贸易伙伴汇总或中国。
- **继续追问**：在同一对话中换方向、商品、伙伴或时间。
- **查政策资料**：检索本地登记的公告，保留适用条件和出处。
- **读报告**：查看图表、计算摘要和逐月金额表，打印或保存 PDF。
- **不用模型也能查数**：自己确认查询范围后生成报告，不需要 API Key。

## 案例演示

| 案例 | 可以看到什么 |
|---|---|
| [大豆进出口](https://yemyu.github.io/TradeIntel/?lang=zh&case=soybean-trade#cases) | 先问进口，再追问出口；两种方向各有报告 |
| [豆油进口](https://yemyu.github.io/TradeIntel/?lang=zh&case=soybean-oil#cases) | 将豆油与原料大豆区分，查询对应商品 |
| [钨与光伏材料](https://yemyu.github.io/TradeIntel/?lang=zh&case=policy-materials#cases) | 一份整理好的关税公告与相关商品进口报告 |
| [缺少月份](https://yemyu.github.io/TradeIntel/?lang=zh&case=missing-month#cases) | 所问月份没有收录时，说明缺口，不换成其他月份交差 |

这些链接可以直接打开案例对话和图表。公开网站不调用模型，也不是在线聊天服务。下载源码后，可以这样阅读同样的案例：

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

打开 `http://127.0.0.1:8000/`，即可按对话和图表阅读，不需要贸易数据包或API Key。前两个案例来自模型参与的查询；政策案例是资料编辑报告；缺月案例展示程序保护。

实际使用时，你可以先问“最近美国大豆进口有什么变化？”。助手查找商品、确认数据可用时间，查询后显示摘要和报告卡片。继续问“出口呢？”，不必重新输入商品。打开报告能看逐月图表、金额和来源，返回后可以接着聊。

## 快速开始

需要 Python 3.12、项目源码和独立的[贸易数据包](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)。包内有124份数据文件，解压后约579 MB，ZIP约64 MiB。**克隆仓库不会同时下载这个包。** 本地安装已在 macOS 验证，Windows 尚未验证。

在仓库根目录使用已有虚拟环境，或新建环境安装依赖：

```bash
git clone https://github.com/Yemyu/TradeIntel.git
cd TradeIntel
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

在 Release 下载 `trade-demo-data-20260927-isolated-v2.zip`，核对 SHA-256：

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

将下面的 `/path/to/` 换成下载文件所在目录。数据核验返回 `"status": "verified"` 后再启动。

把数据包解到一个新的、被 Git 忽略的目录，例如 `.local/trade-data-bundle-1/`。下面的目录必须同时包含 `BUNDLE_MANIFEST.json` 和 `data/`：

```bash
mkdir -p .local
unzip /path/to/trade-demo-data-20260927-isolated-v2.zip -d .local/trade-data-bundle-1
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

打开 `http://127.0.0.1:8765/preview/`，终端需要保持运行，Ctrl-C停止。端口占用时用 `--port` 指定其他空闲端口，不要关闭其他应用。

在“模型设置”选择服务商，填写它支持的型号和自己的 API Key 后保存。保存本身不发请求；“测试连接”会发一个短请求，可能收费。随后在聊天框提问。没有密钥时选择“数据查询”，自己确认商品和月份即可。密钥由本地服务保存，不会发布到展示网站。

完整步骤见[本地使用指南](docs/LOCAL_RUN.zh-CN.md)。GitHub Pages 可以展示案例，但不能运行这个 Python 后端，也不会替访客支付模型费用。

## 模型测试

测试关注三件事：任务是否完成，不支持的请求是否处理正确，生成报告的数据能否核对。

| 模型／推理 | 测试方式 | 正常任务完成 | 边界题处理 | 报告核数 |
|---|---|---:|---:|---:|
| GPT-6.1 Sol／Low | Codex对话桥接 | 9/9 | 3/3 | 9/9 |
| GPT-6.1 Sol／Medium | Codex对话桥接 | 9/9 | 3/3 | 10/10 |
| DeepSeek-V4.1 Flash／high | API | 8/9 | 2/3；一题跳过 | 14/14 |
| GPT-6 Luna／Max | 恢复后Codex对话桥接 | 7/9 | 2/3 | 8/8 |

这是当前工具协议v3修复后的结果。Sol两组完成了整套任务；DeepSeek的钨政策题未完成。Luna恢复后在天然橡胶题停在澄清，税率题的解释没有进入公开回答。Low把进出口合在一份报告里，Medium分开保存，所以报告数量不同。[完整测试页](docs/MODEL_SELECTION.zh-CN.md)解释配置、核验、中断记录和历史GLM/DeepSeek/GPT结果。GPT组是对话桥接测试，不代表已在网页验证GPT API接入。

## 数据范围

| 内容 | 已收录范围 |
|---|---|
| 美国进口 | 48个月：2016年1月—2018年5月、2025年1月—2026年7月 |
| 美国出口 | 2025年8月—2026年7月，连续12个月 |
| 商品 | 已发布的官方商品目录，不限于早期五种演示材料 |
| 贸易伙伴 | 全部来源／目的地汇总，或中国 |
| 政策 | 本地登记并启用的文档 |

最新收录月是2026年7月。“最近”按已有数据理解，指定缺失月份则提示缺数据。进口采用消费进口额，出口采用FAS口径的总出口额，两者分别展示，不相减冒充贸易差额。金额变化也不能直接当成数量、价格变化或政策效果。

## 工作流程

模型负责决定下一步：找哪个商品、查询哪个方向和时间、是否需要查政策，以及返回哪些报告。工具会检查商品编码、月份、伙伴和引用是否有效。

金额不是模型凭记忆填写的。程序读取处理后的美国人口普查局贸易数据，计算总额、月份变化并绘制图表；目前公开报告的摘要也由这些计算结果生成。政策资料使用关键词/BM25检索，范围是本地登记并启用的文档，不是自动搜索整个互联网。

对话和报告保存在本地，可以重新打开。MySQL 用于数据工程和核对，日常网页读取已核验的数据文件，不要求使用者再连接 MySQL。仓库保留早期因果研究和报告写作实验，但它们不是当前助手使用的前提。

缺失值不按零处理；要改查缺少数据之外的其他月份，需要明确确认。

## 文档

| 目录 | 内容 |
|---|---|
| `src/tradeintel_ai/` | Agent、查询工具、校验、报告存储和本地服务 |
| `scripts/` | 数据处理、核验、启动和评测命令 |
| `web/design-preview/` | 双语展示页、聊天和报告阅读 |
| `tests/` | Python与页面回归测试 |
| `evals/` | 测试题、输出要求和冻结参考 |
| `data/` | 来源信息与处理结果，大数据另行提供 |
| `docs/` | 使用说明、评测、数据说明和开发记录 |

[当前功能](docs/CURRENT_PRODUCT.zh-CN.md) · [展示版](docs/PUBLIC_SHOWCASE.zh-CN.md) · [模型测试](docs/MODEL_SELECTION.zh-CN.md) · [开发记录](docs/handoff/STATUS.zh-CN.md)

页面和报告的定向测试（部分Python测试需要发布者的本地数据和原始存档）：

```bash
node --test tests/report_view.test.cjs tests/public_cases_ui.test.cjs tests/trade_explanation_ui.test.cjs tests/announcement_import_ui.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_public_showcase test_trade_agent_report_view
```

旧版介绍保存在[文档存档](docs/history/README.before-public-edit-20261001.md)。

[测试说明](docs/TESTING.md)列出当前回归命令、本地材料要求，以及历史全套测试尚未通过的项目。
