# TradeShock AI

## 当前版本（2026-10-01）

TradeShock 是本机运行的美国商品贸易研究助手。输入“最近美国大豆进口有什么变化？”，配置的模型会选择商品检索和数据查询工具，程序计算结果并展示报告与图表；同一会话可以继续问“出口呢？”。没有模型密钥也能使用数据查询模式，但需要自己确认范围。

网页分为两种用法：公开展示版阅读四个存档案例；本地版可以真正聊天，报告在对话中以卡片打开。模型设置单独放在弹窗里，不再与提问表单混在一起。两版共用贸易报告的图表和数值显示。

四个案例是：大豆进口后追问出口、豆油进口、钨与光伏材料的政策资料报告、缺月份时停止查询。前两个来自已保存的真实运行；政策报告是资料编辑稿；缺月案例展示的是程序拦截，不算模型答对。

商品不限于早期五种演示材料。进口有48个已加工月，分布在2016-01—2018-05、2025-01—2026-07；出口支持2025-08—2026-07。数据不是实时更新，缺月份不会用另一月份替代。MySQL不是网页运行前提。

真实Agent试跑发现过范围和口径问题；修复后的豆油查询通过，缺月请求被程序拦截，但模型日期选择仍有误。因此不宣称任意问题都能可靠自动回答。本轮界面改版通过相关 Python 53 项、Node 41 项回归及有限浏览器检查，没有重跑模型评测。旧 v4 源码包不包含当前界面，继续开发请使用当前项目目录。

[当前功能、使用方法与实测结果](../CURRENT_PRODUCT.zh-CN.md) · [本地安装](../LOCAL_RUN.zh-CN.md) · [展示版说明](../PUBLIC_SHOWCASE.zh-CN.md)

普通Git克隆还需要另附数据包；目前没有公开下载地址。静态展示版不提供任意提问或 API 设置，不要求访客付费。当前改版仍是本机候选，尚未公开发布；两份新案例PDF的6页排版及数值核对已通过，真实中文输入法和200%原生缩放仍待确认。以下保留历次研究记录，运行和交付范围以以上入口为准。

## 历史状态：2026-09-29（已被上方当前版本取代）

本地工作台可根据已发布的美国进口、出口商品目录提出候选，由用户确认商品、方向和月份，再生成带逐月图表与来源的报告。当前仓库另有“研究助手（使用模型）”模式，可由模型选择受限查询工具并在同一会话追问；不配模型时首次打开默认“仅查询数据（不使用模型）”。这条 Agent 链路的离线页面验收已通过，但真实模型目前只有一题开发题成功，不能宣称稳定适用于任意新问题。**此前封装的精简源码 ZIP 是 Agent 加入前的数据报告版，不能用来验收当前 Agent。**进口文件有 **48 个已加工月**（2016-01 至 2018-05、2025-01 至 2026-07，两个不连续时段）；出口文件有 **2025-08 至 2026-07 的连续 12 个月**。进口消费金额与出口 Census Schedule B 总出口额（FAS）按方向分别显示。商品名检索还需用户核对候选，不能理解为所有自然说法都能自动匹配。

通用报告的模型解读是可选试用功能：数据图表不依赖模型；模型回答可能有误，需要对照数据核实。调用会把报告事实发送给配置的服务商，可能产生费用。[现有回答复核](../handoff/runs/20260925-TRADE-AI-VALUE-REVIEW.zh-CN.md)显示：v3 六份原答和一次 v4 开发答尚未证明比数据报告多提供具体帮助，其中一份 v3 回答还混淆了最近月与整个区间的变化；这次复核不是独立盲评。MySQL 已与当前进出口文件整版对账，但网页仍以已发布文件为报告数据源。普通 Git 克隆不含通用查询所需的 124 个数据文件；[本地候选的干净克隆与完整依赖复验](../handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md)在另行补入数据包、新建 macOS / Python 3.13 虚拟环境后，已复现进口、出口、双向报告及网页重启恢复。新电脑、Windows 和公网部署仍未验收。数据补充包约 579 MB；本机原始数据目录约 9.4 GiB。先看[本地版快速上手](../LOCAL_RUN.zh-CN.md)，再看[当前状态](../handoff/STATUS.zh-CN.md)和[发布边界](../handoff/PRODUCT_RELEASE_DECISION_20260925.zh-CN.md)。

单独的公告阅读开发诊断也做过：DeepSeek API 一次回答覆盖七项事实，但因“附件全文未提供”的无据说法未通过；GPT-6 Luna Max 聊天窗口一次回答覆盖七项，未发现无据额外说法。两者不是同渠道盲测，不能据此排名或推断一般准确率；详情见[中文模型评测](../MODEL_SELECTION.zh-CN.md)。

随后两份未见公告的正式阅读调用均未通过约定的回答合同，事后核对也发现事实遗漏；这些结果没有被修订或重试。[新 v4 阅读协议](../handoff/runs/20260929-ANNOUNCEMENT-READING-V4-OFFLINE.zh-CN.md)目前只通过离线假回答与只读页面测试，**还没有新公告上的模型效果或人工省时证据**。第一版本地版的范围见[当前决定](../handoff/PRODUCT_NEXT_DELIVERY_DECISION_20260929.zh-CN.md)，交付前核对见[本地版清单](../LOCAL_DELIVERY_CHECKLIST.zh-CN.md)：普通 Git 克隆需要另附数据包，静态 GitHub 页面只是展示，不能代替本地服务。

## 历史执行覆盖：2026-09-22（当前状态以上节为准）

产品目标是“新政策→贸易数据→有据、可读的观察简报”。范围确认、多期证据、程序报告和追问已接入服务链；浏览器与公告分流已有fixture验收。DeepSeek Flash high在明确政策输出格式后，一道已见Q3开发题通过结构、预算与AI辅助内容核查，并已接入待审阅报告预览。历史失败单独保留；单题结果不代表新问题的稳定通过率。报告仍需用户审阅。完整记录见[模型实测](../MODEL_SELECTION.zh-CN.md)。

An evidence-grounded U.S. goods-trade research assistant under development. It confirms a product and date range, then reports observed monthly imports or exports with charts and official sources. The optional model explanation remains under quality review; this is not a live news feed or a public service.

**Scope decision (2026-09-13):** self-developed causal identification has been removed from the product roadmap. Historical experiments remain available as records, not pending product requirements. [Current roadmap](../../PROJECT_PLAN.md).

[中文项目介绍与演示](../DELIVERY.zh-CN.md) · [中文操作说明](../learning/using-the-research-entry.zh-CN.md) · [Acceptance results](../experiments/product-acceptance.zh-CN.md)

[模型选择与实测对照（中文）](../MODEL_SELECTION.zh-CN.md) explains which model runs the project, which models only assist development, and why no runtime model is currently claimed to be stable. The offline execution controls and score-table generator are recorded in [the runner closeout](../handoff/runs/20260922-PUBLIC-RUNNER-CONTROLS.md).

[与 Claude/RAG/贸易智能项目的定位比较](../COMPETITIVE_POSITIONING.zh-CN.md) explains why this is not simply another document-chat demo.

The table reports task counts, pass fractions and failure types. Historical GLM-4.7 acceptance (5/6) is separate from newer Air development failures. One later GPT-6 Luna Max chat-window diagnostic on the seen R2 notice covered 7/7 reference points without an unsupported extra claim; it is not an API test or blind benchmark. Its comparison with the DeepSeek API result is confounded by channel and conversation context.

[Concise three-file showcase](../showcase/README.zh-CN.md) provides the project scope and two archived reports without internal learning notes or request captures.

## What it does

- Proposes a structured read-only trade query from a Chinese question; execution requires confirmation.
- Retrieves page-linked policy evidence using lexical/BM25 retrieval and query expansion; GLM optionally drafts cited explanations.
- Computes monthly amounts and descriptive comparisons in code, with sources and scope limitations.
- Queries the registered 2025 tungsten/wafers/polysilicon case through a read-only tool using exact HTS8 scope and monthly source fingerprints.
- Stops missing-scope and unsupported requests; checks supported explicit comparison-direction phrases.

This is an AI application, not a trained foundation model. There is no fine-tuning, multi-agent deployment or accepted causal-effect estimate. The policy corpus covers indexed narrative text from two historical notices, not a complete tariff database or current legal guidance. Runtime model results and limits are recorded in the [model comparison note](../MODEL_SELECTION.zh-CN.md).

## View results without running anything

- [Real policy + trade report](../experiments/phase-0140-live/combined-report.zh-CN.md)
- [New-policy exposure report (2026-07)](../../data/processed/policy_exposure/report_2026_07.zh-CN.md)
- [New-policy 19-month exposure summary](../../data/processed/policy_exposure/window_summary_2025-01_2026-07.zh-CN.md)
- [Query-tool learning note](../learning/policy-exposure-query-tool.zh-CN.md)
- [Review and limitations](../experiments/phase-0140-live/README.zh-CN.md)
- [Fixed six-scenario acceptance, including the failure](../experiments/product-acceptance.zh-CN.md)

The fixed development acceptance recorded 5 passes and 1 failure (supported tasks: 2/3; boundaries: 3/3), using 7 GLM-4.7 calls / 14,640 reported tokens. This small assistant-designed and assistant-reviewed set is not independent accuracy. A later offline direction-guard fix does not change the model result. Earlier no-evidence controls also answered the repeated policy facts correctly: no RAG accuracy uplift is claimed.

## Run on a prepared checkout

Install dependencies only in the project virtual environment; skip creation if a working `.venv` already exists:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Prepared local trade tables, policy text and manifests are also required. Package installation alone does not rebuild the data. An isolated working-tree export with a new Python 3.12 virtual environment passed the offline demo on the same macOS machine after supplying the two policy PDFs, source manifest and omitted trade panel. Cross-platform installation and full data rebuild remain unverified. [Exact requirements and review](../RELEASE_REVIEW.zh-CN.md).

Check the four files omitted from a normal Git checkout without downloading or changing anything:

```bash
.venv/bin/python scripts/verify_portable_data.py
```

This older check covers only the four policy-reference files in `PORTABLE_DATA_MANIFEST.json`; `"status": "ready"` does not certify the general trade reports or the rest of the checkout. Missing, mismatched or incomplete manifests return a non-zero exit. The source-manifest hash binds archived metadata including its retrieval timestamp; downloading the same PDFs again can produce different metadata and requires review rather than blindly changing the expected hash.

To make a plain folder containing those four files, without overwriting an existing path:

```bash
.venv/bin/python scripts/prepare_portable_data_bundle.py --output tmp/portable-data-bundle
```

The folder is a data supplement, not a standalone project or a zip archive. It contains no API configuration, credentials, Census ZIP archives, or temporary run records. Copy its `data/` directory into a prepared checkout and run the verification command again.

The general U.S. trade workspace uses a separate, larger supplement: 124 processed data/index files (about 579 MB), covering 48 import months, 12 export months and the matching product catalogs. The source bundle is local and ignored by Git at `tmp/handoff-runs/trade-demo-data-20260925/`; the current locally verified ZIP is `tmp/handoff-runs/trade-demo-data-20260927-isolated-v2.zip` (SHA-256 `1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`). Neither is publicly hosted or included in a normal clone. [Local setup instructions](../LOCAL_RUN.zh-CN.md) recommend unpacking the ZIP into a separate ignored directory and passing `--trade-data-root` to the web server, so the code checkout stays untouched. To generate and verify a fresh copy from the full published files already present in this checkout, choose a new output directory:

```bash
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py create --output tmp/handoff-runs/trade-demo-data
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root tmp/handoff-runs/trade-demo-data
```

To use it in a separate checkout, unpack the ZIP to a separate directory containing `data/` and `BUNDLE_MANIFEST.json`, verify with `PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root /path/to/unpacked-bundle`, then start the page with `.venv/bin/python scripts/run_web.py --trade-data-root /path/to/unpacked-bundle`. This verifies data bytes and versions only; it does not install dependencies or prove a clean-machine deployment. The supplement excludes raw Census ZIPs, MySQL files, credentials, source code and historical run records. See the [isolated demo verification](../handoff/runs/20260925-TRADE-DEMO-BUNDLE.zh-CN.md).

From the repository root, in an interactive terminal:

```bash
TRADEINTEL_MODEL_TIMEOUT=180 .venv/bin/python scripts/run_unified_research.py --question '只列出2018-09与2018-10中国的美元消费进口额，商品用第一批关税政策整体范围；逐月列数，不比较，不估计因果。' --confirm
```

Review the preview; type `yes` only if correct. The final output prints the report path under `tmp/unified-research/`. This example makes one planning call; a policy question with `--generate` can make an additional generation call. Preview-only mode still calls the planner; restarting creates a new attempt.

The CLI reads private project-local provider configuration when present, otherwise environment settings and a hidden key prompt. Never commit keys, `.local/`, or private raw runs. The everyday report reads prepared files; it does not require an active MySQL login.

To run the deterministic new-case query without an API key:

```bash
.venv/bin/python scripts/run_policy_exposure_query.py --origin China --start 2025-01 --end 2026-07 --output tmp/policy-exposure-query.json
```

This produces verified descriptive amounts and source references. It does not call an LLM and does not estimate a policy effect.

To open the local Chinese page (no public deployment):

```bash
.venv/bin/python scripts/run_web.py
```

Open `http://127.0.0.1:8765/preview/`. This unified page combines project introduction, the general trade question workspace and report reading. Queries are deterministic after the user confirms the official product and date range; they read the published import/export files and do not download new data. The separately registered 2025 Section 301 case remains a bounded policy-data route, not a general policy updater. Model explanations are optional drafts and still need content-quality review.
See the [Chinese question-entry guide](../learning/business-question-entry.zh-CN.md).
The complete Chinese workflow (fixed data version → AI review → export) is in [full workflow guide](../learning/full-workflow.zh-CN.md).
The three AI-demo buttons are explicit, bounded GLM runs; the browser never
receives the project-local API key. A successful run returns a review-required
Markdown report, while a failed run remains a local diagnostic record. See the
[Chinese page learning note](../learning/web-demo.zh-CN.md) for the complete
workflow and interpretation of the numbers.

The fixed `--exposure-demo` route now uses an evidence-only JSON report contract: the model selects investigation priorities while code renders computed facts and provenance. Invalid free-form output is retained but not delivered. This interim constrained mode has offline tests, not a new live-model success claim. [Chinese explanation](../learning/policy-exposure-report-boundary.zh-CN.md).

## Zero-network engineering demo

```bash
.venv/bin/python scripts/run_strict_offline_demo.py --output tmp/delivery-offline-demo
```

Use a fresh output path. Prepared local data are still required. Responses and review labels are fixtures, not real model answers or a quality benchmark. [Explanation](../experiments/phase-0126-offline-demo/README.zh-CN.md).

## Limitations and remaining work

The original plan included causal research, but this is no longer a product requirement. No accepted causal estimate is claimed, and descriptive changes must not be called tariff effects. This is currently a bounded prototype requiring scope and citation review, not an unattended production analyst.

The new-case live demo (`--exposure-demo`) obtained correct tool-derived amounts, but its economic interpretation failed review (unsupported supply/capacity claims). See the [Chinese review](../learning/policy-exposure-live-review.zh-CN.md). The local page now provides a bounded query/AI-demo entry and displays the sealed update pointer, but it does not make free economic interpretation reliable or collect data online. Remaining work includes evidence-bounded interpretation, cross-period comparability, limited task evaluation and broader policy coverage. Existing reports, page tests and tool tests do not complete these goals. No public deployment or publication is implied.

[Project plan](../../PROJECT_PLAN.md) · [Long-term context](../PROJECT_CONTEXT_REFERENCE.zh-CN.md) · [Historical README](../../README.history.md)
