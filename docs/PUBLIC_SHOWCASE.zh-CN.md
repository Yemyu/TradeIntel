# 四案例展示版

日期：2026-10-01。当前为本机静态候选，尚未推送或发布。

访客可阅读项目介绍、案例中的问答和步骤、完整报告与图表。这里不接收自由提问，也没有模型设置。要真正使用助手，请按[本地安装说明](LOCAL_RUN.zh-CN.md)运行项目，再配置自己的模型 API；数据查询模式不需要模型或 MySQL。

## 案例

| 案例 | 展示内容 | 记录类型 |
| --- | --- | --- |
| 大豆进口，接着问出口 | 同一会话换方向；全部来源与附加中国来源的报告分开 | 已保存的真实运行 |
| 豆油不是原料大豆 | 1507 商品组的十二个月进口金额 | 已保存的真实开发检查 |
| 钨和光伏材料 | 五类商品的政策背景、进口金额及中国份额 | 存档资料编辑稿，不是 Agent 新回答 |
| 所问月份还没有数据 | 所问八月缺数据，不能改查七月充当答案 | 程序拦截；模型曾选错月份 |

金额、月份和来源来自原有记录。翻译版供阅读，不是另一次模型调用。这四案不能作为通用准确率排名。

## 本机查看

最终候选：`tmp/handoff-runs/showcase-20261001-u2-final/site/`。构建审计在其同级 `audit/`，**不要把 audit 上传为网站**。

```bash
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --verify tmp/handoff-runs/showcase-20261001-u2-final/site
PYTHONPATH=src:. .venv/bin/python scripts/serve_public_showcase_qa.py --site tmp/handoff-runs/showcase-20261001-u2-final/site
```

打开 `http://127.0.0.1:8897/TradeIntel/preview/`。这个地址只用于本机检查，不是公网链接。服务同时支持根目录与仓库子路径；不启动模型或数据库。

构建器只导出允许字段和 14 份静态资源，不包含 live.js、提问表单、API Key、本机路径、原始模型回答或未审阅草稿。原件摘要不符、字段越界、可疑凭证或已存在输出目录都会拒绝，不覆盖旧文件。`--verify` 依赖本机原件，仅用于发布者核对候选；它不是访客安装命令。

若需要重新构建，选择一个不存在的输出路径：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --output tmp/handoff-runs/showcase-new/site
```

## 发布前仍需完成

两份新案例报告的实际PDF已验收：大豆出口与钨/光伏各3页，排版、所选数据和来源核对通过，见[打印记录](handoff/runs/20261001-U2-PRINT-PDF.zh-CN.md)。真实中文输入法及200%原生缩放仍待用户反馈；有限桌面/手机页面与自动测试不代替这两项实际操作。

普通 Git 克隆仍缺 124 文件数据包，尚无公开下载地址。正式发布时应提供已核验包及 SHA，并核对源码与数据对应版本；不能放一个空下载按钮。当前没有付费云服务器、公共数据库或访客模型账单。上传网站与数据包需另行确认，本轮没有执行。
