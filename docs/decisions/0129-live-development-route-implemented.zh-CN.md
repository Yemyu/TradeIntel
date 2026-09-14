# 0129：真实开发模式首轮接线（0130复核未通过）

更正：下文是首轮实现记录，完成与审核描述已被[0130复核](0130-live-review-audit.zh-CN.md)撤销。原自动审核是关键词/来源匹配，会误判否定句，并对无证据B不公平；未实现宿主提交与恢复。本次已撤除自动批准并阻断live入口，预检ready=false。旧661项工程测试通过不能证明语义正确。不得按下文旧说明启动真实批次；无需用户重复授权，下一步为实现修复。

日期：2026-09-13。实现与离线回归；本轮未调用外部模型 API。

## 结论

0128 规定的 `live_development` 已接入现有严格运行器。它不是第二套框架，也不是把离线 fixture 改名为真实成绩：

- 默认 `synthetic` 仍然只使用测试模型，旧离线演示和旧测试行为不变；
- 只有显式 `run_mode="live_development"`、`strict_protocol=True`、`external_calls=True` 才允许真实 provider；
- live 模式拒绝 `fixture_review`、默认离线审核人和离线子审核人，账本会记录 `run_mode`、`external_calls`、`reviewer_type`、调用预算和 token 预算；
- 规划阶段切换为 `planner_source_kind="live"`，政策主组与无证据 B 组都走同一个脱敏捕获边界；
- 四个已知开发场景由代码冻结：贸易比较、政策日期/税率、政策+贸易组合、信息不足澄清；
- 真实配置只保存端点身份、模型名、温度、超时、是否存在密钥等非秘密字段，URL 中的查询参数和密钥不会写入快照或响应；
- 新入口默认只做零网络预检，`--execute` 才会开始一次新的有界批次。输出目录不可复用，失败或停止不能原地重跑。

## 审查标签

新增的 `ai_assisted` 审查会阅读实际计划、交付、政策主张和证据：结构审查检查任务/范围，政策审查要求实际主张绑定实际检索片段，事实审查把检索窗口重新绑定到冻结官方来源并检查允许表述。它仍不是独立人工金标，也不把结构通过改成模型准确率；`semantic_accuracy_measured` 保持 `false`，人工复核状态仍需披露。

## 预算与停止

真实开发默认最多 4 次规划、2 次带证据政策回答、2 次无证据 B 回答，共 8 次尝试；累计已报告 token 达到 20,000 后禁止下一次调用。任一传输/结构/截断/快照/未知用量或主组业务错误都会停止，不自动重试。B 组出现有效但不正确的内容会记录为基线观察；B 基础设施失败会停止批次。

## 零网络预检

```bash
source .venv/bin/activate
export TRADEINTEL_MODEL_BASE_URL='https://open.bigmodel.cn/api/paas/v4'
export TRADEINTEL_MODEL_NAME='你的模型名'
export TRADEINTEL_MODEL_API_KEY='只在本地环境设置，不要粘贴到 Git 或聊天'
PYTHONPATH=src python scripts/run_live_development_0128.py \
  --output /tmp/tradeintel-live-preflight-0128
```

预检只读取配置、冻结四题和代码/数据哈希，不发送请求，也不创建批次目录。确认打印出的模型、端点和预算后，才在新的输出目录加 `--execute`。本仓库本轮只验证了预检和 fake-provider 单元路径，没有宣称真实模型成绩。

## 验收结果

- 新增 9 项 live 路由/审核/脱敏/预审材料测试；
- 全部工程测试：661 项通过，0 外部 API；
- 当前项目仍不能声称因果估计、未见题准确率、人工独立金标或生产级无人审查；
- 下一步应由 Astra 中审查预检产物和实际模型配置，再由用户明确允许启动这一次有界真实批次。若模型配置或预检发现冲突，先停下，不修改历史题文刷结果。
