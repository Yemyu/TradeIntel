# 本机数据补充 ZIP 核验（2026-09-27）

## 范围

把现有 `trade-demo-data-bundle-1` 做成**仅在本机保留**的 ZIP，方便以后给干净克隆补齐数据。本步不决定能否公开分发，也没有上传、模型调用、MySQL 操作或外网请求；原始数据目录未改动。

## 产物与核验

- 本机文件：`tmp/handoff-runs/trade-demo-data-20260927.zip`（Git 忽略目录，未提交）。
- ZIP 大小：67,464,723 字节；SHA-256：`c847fda351cfbb93d856473cdac9b1d285c310e1ff8366a1273d5697713aa7ac`。
- 内含 126 个普通文件：`BUNDLE_MANIFEST.json`、`BUNDLE_README.zh-CN.md`、`data/` 下 124 个文件。没有符号链接或越过解包目录的路径。
- `unzip -tq` 全部通过。逐一解压到临时目录后，运行 `scripts/trade_demo_data_bundle.py verify --root <解压目录>` 返回 `status: verified`，124 个数据文件、578,630,811 字节、进口/出口/商品目录三个版本核验通过。
- 解包核验用的临时副本与空暂存目录已清理；本机最终 ZIP 和既有原始数据目录保留。

这只证明**该本机 ZIP 可无损解包并通过项目清单校验**。还没有决定外部分发范围和渠道，也未测试 Windows 或任何公网部署。下一步需要另行确定这些边界；不能把本机 ZIP 当作已经公开发布的数据包。
