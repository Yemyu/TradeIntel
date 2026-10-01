# 2026-09-29 本地版薄收口与当前候选复核

本轮只执行[已定交付清单](../PRODUCT_NEXT_DELIVERY_DECISION_20260929.zh-CN.md)：对齐入口、核当前候选、列外发范围。没有新模型请求、MySQL 写入、提交、推送或删除旧实验。

## 已做

- `README.md`、`PROJECT_PLAN.md`、`docs/DELIVERY.zh-CN.md` 顶部按当前产品能力表述；旧计划保留但标明历史。静态首页区分示例与本地可运行工作台，动态工作台不再显示“仅预览”。
- [一页本地交付核对单](../../LOCAL_DELIVERY_CHECKLIST.zh-CN.md)分清源码和单独数据包、启动与拒绝样例、可选模型和未验收范围；未虚构公开下载地址。
- 已查看 `git status`/已跟踪文件与未跟踪目录。`src/`、`web/`、`scripts/run_web.py`、数据包核验脚本和本地运行说明属于候选源码；`.workbuddy/`、`output/`、`vendor/course-reference/`、临时运行材料及未跟踪 v3/v4 试验不能一键加入外发。未移动、删除或发布任何文件。

## 验收结果

| 项目 | 本轮结果 |
|---|---|
| 数据包 | `trade_demo_data_bundle.py verify` 返回 `verified`，124 文件、578,630,811 字节；进口、出口、商品目录三类版本均匹配。 |
| ZIP | `trade-demo-data-20260927-isolated-v2.zip` SHA-256 为 `1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`，与本地运行说明一致。 |
| Python 主线 | `tests.test_trade_query_flow`、`test_trade_data_repository`、`test_trade_export_integration`、`test_announcement_trade_bridge`、`test_trade_explanation_v4`，39/39 通过。 |
| 页面 | `trade_explanation_ui`、`announcement_import_ui`、`session_flow_ui` 的 Node 测试，25/25 通过。 |
| 本机真实数据 HTTP | `/preview/` 返回 200；大豆进口 2026-07 为 46,041,287 美元，玉米出口 1,637,235,741 美元；大豆双向分别为进口 46,041,287、出口 889,379,312 美元。三份报告均为 `not_requested` 模型状态；服务重启后 3/3 可按报告编号读取。未知商品返回 `needs_product`，未错误匹配。 |
| 修改检查 | `git diff --check` 与页面脚本语法检查通过。 |

HTTP 验收仅绑定本机 `127.0.0.1` 临时端口，报告记录保存在临时目录，退出后自动清理；未访问外部模型或服务。最初验收脚本误以为响应中有嵌套 `report`，又误以为双向报告有单一 `summary`；核对实际协议后修正脚本，最终完整链路通过。这两次是验收脚本字段错误，未据此改产品或掩盖正式失败。

## 仍需决定

普通 Git 克隆不含 124 文件数据包；目前只有本机 ZIP，没有可给使用者的公开获取地址。数据包要私下交付还是公开发布，需要另定渠道并复核来源、再分发范围和拟外发文件。此轮未做 Windows、异机、公网或模型实际增益验收；静态 GitHub 页面仍只能看示例。不要把本轮本机通过写成“全部可上线”。
