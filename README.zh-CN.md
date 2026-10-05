# TradeIntel — 国际贸易研究助手

[🌐 English](README.md) | **🇨🇳 简体中文**

[案例演示](https://yemyu.github.io/TradeIntel/?lang=zh) · [📊 示例报告](https://yemyu.github.io/TradeIntel/?case=policy-materials&report=r1&lang=zh#report) · [快速开始](#快速开始) · [模型测试](docs/MODEL_SELECTION.zh-CN.md) · [下载数据](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

TradeIntel 是一个开源贸易研究 Agent。用商品名称或编码提问，可以查询进出口数据和相关政策，再接着问其他方向、伙伴或月份。

当前版本收录美国进出口数据，支持全部贸易伙伴汇总及中国伙伴查询；最新收录月为2026年7月。下方的数据范围表列出具体区间。

AI 理解问题、接续追问，并根据工具返回的结果决定继续查什么。程序核对查询范围与数据，计算金额，生成带图表和出处的报告。

公开网站提供四个已保存的案例。要自己提问，可以在本机运行项目，配置自己的模型 API；不配置模型时，也能手动选定范围，生成数据报告。

## 功能

- **找商品**：按名称或官方编码检索商品目录。确有歧义时会询问。
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

这些链接可以直接打开案例对话和图表，不需要安装、贸易数据包或 API Key。公开网站不调用模型，也不是在线聊天服务。前两个案例来自模型参与的查询；政策案例是资料编辑报告；缺月案例展示程序保护。从源码副本阅读案例的步骤见[本地使用指南](docs/LOCAL_RUN.zh-CN.md#查看已保存案例)。

实际使用时，你可以先问“最近美国大豆进口有什么变化？”。助手查找商品、确认数据可用时间，查询后显示摘要和报告卡片。继续问“出口呢？”，不必重新输入商品。打开报告能看逐月图表、金额和来源，返回后可以接着聊。

## 快速开始

需要项目源码和独立的[贸易数据包](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)。包内有124份数据文件，解压后约579 MB，ZIP约64 MiB。**克隆仓库不会同时下载这个包。** 建议使用 Python 3.13，完整安装记录使用 macOS 和 Python 3.13.3。会话与报告存储依赖 POSIX 的 `fcntl` 模块，当前不支持原生 Windows。

首次安装时，克隆源码并创建项目环境。下面两次版本检查应输出 Python 3.13.x：

```bash
git clone https://github.com/Yemyu/TradeIntel.git
cd TradeIntel
python3.13 --version
python3.13 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
```

在 Release 下载 `trade-demo-data-20260927-isolated-v2.zip`。将 `/path/to/` 换成下载文件所在目录，在 macOS 核对 SHA-256：

```bash
shasum -a 256 "/path/to/trade-demo-data-20260927-isolated-v2.zip"
```

摘要应为：

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

把数据包解到 `.local/` 下的新目录，Git 会忽略该目录。数据根目录必须同时包含 `BUNDLE_MANIFEST.json` 和 `data/`：

```bash
mkdir -p .local
unzip "/path/to/trade-demo-data-20260927-isolated-v2.zip" -d ".local/trade-data-bundle-1"
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root ".local/trade-data-bundle-1"
```

核验返回 `"status": "verified"` 后启动：

```bash
.venv/bin/python scripts/run_web.py --trade-data-root ".local/trade-data-bundle-1"
```

打开 `http://127.0.0.1:8765/preview/`，终端需要保持运行，Ctrl-C 停止。端口占用时用 `--port` 指定其他空闲端口。

在“模型设置”选择智谱 GLM、DeepSeek 或千问，填写该平台支持的型号 ID 和自己的 API Key 后保存。保存本身不发请求；“测试连接”会发一个短请求，可能收费。随后在聊天框提问。没有密钥时选择“数据查询”，自己确认商品、方向和月份即可。密钥由本地服务保存。

完整步骤见[本地使用指南](docs/LOCAL_RUN.zh-CN.md)。GitHub Pages 可以展示案例，但不能运行这个 Python 后端。

## 模型测试

测试关注三件事：任务是否完成，不支持的请求是否处理正确，生成报告的数据能否核对。

GPT 模型通过 Codex 聊天测试，DeepSeek 和 GLM 使用应用 API。GPT 成绩不代表本地应用已支持 GPT API。

| 模型／推理 | 正常任务完成 | 边界题处理 | 报告核数 |
|---|---:|---:|---:|
| GPT-6.1 Sol／Low | 9/9 | 3/3 | 9/9 |
| GPT-6.1 Sol／Medium | 9/9 | 3/3 | 10/10 |
| DeepSeek-V4.1 Flash／high | 8/9 | 2/3；一题跳过 | 14/14 |
| GLM-5.3-Flash／High | 8/9 | 2/3；R06程序预检、P02依赖跳过 | 10/10 |
| GPT-6 Luna／Max | 7/9 | 2/3 | 8/8 |

每组计划使用9道正常题和3道边界题。Sol两组完成了整套任务；DeepSeek与GLM的钨政策题均未交付报告，GLM还因前置题未完成而跳过税率追问；Luna在天然橡胶题停在澄清，税率解释没有出现在回答中。一题可以生成多份报告，所以报告数量不同；跳过题不会算作模型答错或答对。[完整测试页](docs/MODEL_SELECTION.zh-CN.md)列出题目、评分标准、配置和主要问题。

## 数据范围

| 内容 | 已收录范围 |
|---|---|
| 美国进口 | 48个月：2016年1月—2018年5月、2025年1月—2026年7月 |
| 美国出口 | 2025年8月—2026年7月，连续12个月 |
| 商品 | 已收录数据对应的官方商品目录 |
| 贸易伙伴 | 全部来源／目的地汇总，或中国 |
| 政策 | 本地登记并启用的文档 |

最新收录月是2026年7月。“最近”按已有数据理解，指定缺失月份则提示缺数据。进口采用消费进口额，出口采用 FAS 口径的总出口额，两者分别展示，不能直接相减作为可比的贸易差额。金额变化也不能直接当成数量、价格变化或政策效果。

当前版本先使用美国进出口数据。后续考虑加入中国及其他国家的数据，需要先完成数据采集，并核对商品分类和统计口径。

## 工作流程

助手使用工具调用循环：

1. 模型识别商品、方向、伙伴和时间，追问时参考前一轮上下文。
2. 模型查商品目录和可用月份，再调用贸易或政策工具。工具读取记录，检查查询范围，并计算金额。
3. 模型读取返回结果，决定继续补查、有歧义时询问，还是提交本轮报告与引用，完成任务。
4. 程序检查报告引用，保存结果，展示图表、摘要、详细数值和出处。

需要补查时，第3步会回到第2步。例如，查询进口后再查出口，或检索相关政策公告。模型选择返回哪些报告，程序决定页面优先展示哪一份。

程序读取处理后的美国人口普查局贸易数据，计算总额和月份变化；目前公开报告的摘要也由这些计算结果生成。政策资料使用关键词/BM25 检索，范围是本地登记并启用的文档及相关条件。

对话和报告保存在本地，可以重新打开。缺失数据不按零处理；改查其他月份需明确确认。

MySQL 用于数据工程和核对，日常网页读取已核验的数据文件，不需要数据库服务。

## 文档

| 目录 | 内容 |
|---|---|
| `src/tradeintel_ai/` | Agent、查询工具、校验、报告存储和本地服务 |
| `scripts/` | 数据处理、核验、启动和评测命令 |
| `web/design-preview/` | 双语展示页、聊天和报告阅读 |
| `tests/` | Python与页面回归测试 |
| `evals/` | 测试题、输出要求和冻结参考 |
| `data/` | 来源信息与处理结果，大数据另行提供 |
| `docs/` | 使用说明、评测和数据说明 |

[文档导航](docs/README.zh-CN.md) · [功能与数据范围](docs/CURRENT_PRODUCT.zh-CN.md) · [展示版](docs/PUBLIC_SHOWCASE.zh-CN.md) · [模型测试](docs/MODEL_SELECTION.zh-CN.md)

页面和报告的定向测试（部分Python测试需要发布者的本地数据和原始存档）：

```bash
node --test tests/report_view.test.cjs tests/public_cases_ui.test.cjs tests/trade_explanation_ui.test.cjs tests/announcement_import_ui.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_public_showcase test_trade_agent_report_view
```

[测试说明](docs/TESTING.zh-CN.md)列出回归命令和本地材料要求。
