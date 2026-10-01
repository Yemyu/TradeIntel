# 本地版交付核对单（2026-09-29）

> 本文记录历史安装包与分发检查，不代表当前代码状态。当前功能收尾只按[最后验收清单](FINAL_LOCAL_ACCEPTANCE.zh-CN.md)执行；下面旧端口阻碍已解除，旧包不含后续全部修复，不需要每次修复重新打包。

v4补验已完成：独立目录页面HTTP200，两个启动周期会话／报告与缺月份澄清读取8/8通过，0真实API；本地端口阻碍已通过仅本机验证权限解决。源码包哈希未变。此次未新增浏览器视觉和Windows验收。

2026-09-30当前源码候选更新为 `tmp/handoff-runs/tradeintel-local-reviewer-agent-source-20260930-v4.zip`，SHA-256 `b158ae332c54df441dfb49d63a9ae6dae8edb64f3de6f26444d1b3bca2bca27a`。已包含大豆英文别名和两字段完成合同。独立数据核验、脚本模型报告及重建Agent读取通过；环境禁止本地端口监听，本包HTTP／浏览器补验仍待做，详见[当前包记录](handoff/runs/20260930-TRADE-AGENT-V4-PACKAGE.zh-CN.md)。下方v3为历史候选，不代表当前代码。

现有精简源码 ZIP 交付的是**本机运行的美国商品贸易数据报告**，不是在线服务或每日自动更新的政策资讯。用户输入中文问题，确认商品和进出口方向后，可查看逐月金额、图表及来源。数据报告不需要 MySQL 或模型密钥；模型解读另行触发，仍须人工核对。静态 GitHub 页面只能看示例，不能代替本地服务。当前工作目录后来新增了研究助手；旧 ZIP 不含其模块，不能作为当前 Agent 版本交付。

## 交给使用者的两部分

1. **项目源码**：本机开发使用仓库代码、网页、`requirements.txt` 和[本地运行说明](LOCAL_RUN.zh-CN.md)。给他人试用前先按[外发方案](handoff/LOCAL_DATA_DISTRIBUTION_DECISION_20260929.zh-CN.md)制作并复验精简源码包，不直接打包当前整个工作目录或一键暂存；工作树还有未跟踪的实验、运行产物和课程参考。
2. **单独的数据包**：本机候选 `tmp/handoff-runs/trade-demo-data-20260927-isolated-v2.zip`，SHA-256：`1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`。解压后应有 `BUNDLE_MANIFEST.json` 和 `data/`，共 124 个已处理文件、578,630,811 字节。**普通 Git 克隆不含它，目前也没有公开下载地址。**在决定私下交付还是公开发布之前，不应声称陌生人只靠仓库就能运行。

精简源码**旧版数据报告候选**已封为 `tmp/handoff-runs/tradeintel-local-reviewer-source-20260929-v1.zip`，SHA-256：`e1f0136d8866eb518aa7f022d97ac99bceb2a57b1019e65e48aabda146661fe2`；详见[隔离复验](handoff/runs/20260929-LOCAL-REVIEWER-PACKAGE.zh-CN.md)。已只读检查其 ZIP 清单：含当时的 `web/design-preview/live.js`，但不含后来新增的 `src/tradeintel_ai/trade_agent.py`、`trade_agent_store.py` 和贸易 Agent 测试。因此它与当前工作目录不是同一产品快照；当前 Agent 须另做精简源码包并从该包独立复验。旧源码 ZIP 和数据 ZIP 仍只在本机，尚未发送、上传或公开。

**当前 Agent 源码候选**为 `tmp/handoff-runs/tradeintel-local-reviewer-agent-source-20260930-v3.zip`，SHA-256 `a233c2e3db09241ba582fc33b17e978b944ae8165363971ec4f17e6bb040791d`。它与同一数据 ZIP 在干净目录通过无密钥页面、脚本模型双报告主范围及来源标签的[离线复验](handoff/runs/20260930-TRADE-AGENT-MULTI-REPORT-FIX.zh-CN.md)。v1/v2 源码候选均已被 v3 取代但保留本机历史记录；旧数据版包仍只代表数据版。v3 只证明离线链路，不证明真实模型稳定性，也没有发送或公开。

不要随交付物发送 API 密钥、`.env`、`.local/`、`tmp/` 的其他运行记录、`output/`、原始 Census 压缩包、MySQL 数据目录或 `vendor/course-reference/`。未跟踪的 v3/v4 公告阅读实验和冻结材料须单独审查，不能用 `git add .` 顺手带入。这里是**待外发范围**，不是已发布文件清单；尚未提交、推送或公开数据包。

## 收到文件后怎么核验

在新克隆中创建项目虚拟环境，将数据包解到一个新的 `.local/` 子目录，再按[快速上手](LOCAL_RUN.zh-CN.md)运行数据包核验命令。只有返回 `"status": "verified"` 才启动本地服务；在浏览器打开 `http://127.0.0.1:8765/preview/`。建议依次试大豆进口、玉米出口、大豆进出口，再试一个目录里没有的商品：前三者应按确认后的范围生成报告，最后一个不应被硬套到其他商品。刷新或重启后，已有报告仍应能读回。停止服务用终端 `Ctrl-C`。

## 本机复核与未验收项

本轮核验了上述数据包与 ZIP 摘要；当前产品相关 Python 测试 **39/39**、页面 Node 测试 **25/25** 通过。用已核验数据包实际走本机 HTTP：页面 200，三类报告均生成，3/3 重启读回，未知商品返回需指定商品；**0 次模型调用、0 次 MySQL 写入**。这只是同一台 macOS 机器上的当前候选复核；Windows、陌生机器及公网部署没有由本轮证明。模型解释的新增帮助也未证明，不能把它写成已稳定通过的核心功能。
