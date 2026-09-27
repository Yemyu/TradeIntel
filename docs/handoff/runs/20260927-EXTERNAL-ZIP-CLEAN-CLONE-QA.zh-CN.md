# 外置 ZIP 数据目录：干净克隆验收（2026-09-27）

## 固定范围

本机 `codex/local-release-candidate` @ `89838a4` 用 `git clone --local --no-hardlinks --single-branch` 创建干净副本；最终 ZIP 为 `tmp/handoff-runs/trade-demo-data-20260927.zip`，SHA-256 `c847fda351cfbb93d856473cdac9b1d285c310e1ff8366a1273d5697713aa7ac`。使用 macOS Python 3.13.3；ZIP 只解到副本的 `.local/trade-data-bundle-1/`，不覆盖仓库根目录。按既定金额验收，不更改数据、预期数值或报告逻辑。未发模型 API、未写 MySQL、未推送或对外上传。

## 结果

| 检查 | 实测 |
| --- | --- |
| Git 状态 | 解压前后以及生成报告后 `git status --porcelain=v1` 均为空；数据包与报告状态在被忽略的 `.local/` 内。 |
| 数据包 | `verify --root .local/trade-data-bundle-1` 返回 `verified`：124 文件、578,630,811 字节；进口 `dd980149…`、出口 `4308e4a8…`、商品目录 `a758a023…`。 |
| 启动与页面 | `run_web.py --trade-data-root .local/trade-data-bundle-1 --port 18765` 正常启动，`/preview/` HTTP 200。启动经过同一包核验。 |
| HTTP 报告 | 用户问题→选择官方商品候选→确认范围→生成报告；2026-07 大豆进口 **46,041,287 美元**、玉米出口 **1,637,235,741 美元**、大豆双向进口/出口 **46,041,287 / 889,379,312 美元**。 |
| 重启恢复 | 停止并重启网页服务后，三份报告均可按原 ID 读取；金额、`report_sha256` 均保持一致；模型状态为 `not_requested`。 |
| 定向测试 | 干净克隆运行分根、旧查询、出口集成及数据仓库测试：26 项，25 通过、1 项因本地原始文件不存在而跳过。 |

另尝试了包含 `tests/test_web_app.py` 的 23 项集合：其中 22 项通过、1 项因测试直接读取 Git 忽略的 `tmp/trade-aware-interpretation-v1-first/run/status.json` 而报 `FileNotFoundError`。这是克隆不带临时 fixture 的旧测试环境问题；没有为刷绿复制原工作区的忽略文件，也没有改该测试。真实 `/preview/` 与报告重启恢复已通过单独 HTTP 验收，不能把这 23 项说成全绿。

## 边界

本次证实本机 macOS 的固定代码提交 + 单独 ZIP 可运行普通贸易报告，且安装数据不弄脏 Git。**不等于**普通 Git 克隆自带数据、新机器/Windows 可用、公网已部署、模型解释准确或新政策可自动发现。当前 ZIP 只在本机，原随包 README 仍写旧的“合并到根目录”方式；当前推荐步骤以 `docs/LOCAL_RUN.zh-CN.md` 为准。若未来发布新 ZIP，需要新文件名/摘要和重新验收，不能覆盖旧档案。

验收用的约 621 MB 临时克隆已移至本机废纸篓，可恢复；原仓库、最终 ZIP 和正式数据没有移动或删除。
