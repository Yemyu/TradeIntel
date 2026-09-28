# S2 贸易覆盖与新公告确定性报告

日期：2026-09-20  
执行模型：Luna 最高  
范围：离线、服务器端已登记数据；0 次真实模型/API 调用；未修改旧冻结记录；未提交/推送。

## 完成内容

- `src/tradeintel_ai/announcement_report.py`：建立公告候选字段 → 服务器贸易覆盖 → `evidence-bundle-v2` → A3 事实目录的确定性链。
- `announcement_flow.check_trade_coverage`：只接受月份和来源案例请求，金额、来源版本、覆盖状态由已登记的只读查询生成；结果原子保存到公告存储。
- `web_app.py` 增加 `POST /api/announcements/coverage/check`；导入页面增加月份和“核对贸易覆盖”按钮。
- 导入页对 `hts_codes`、`rates`、`entry_events` 先按 JSON 解析再提交，避免浏览器表单把结构化字段降成字符串而误判覆盖。
- 会话证据/报告路径按 `policy_binding` 选择公告自己的候选事实，不再强行调用主案例固定政策事实；没有 exact 覆盖时拒绝金额报告。

## 覆盖边界

- `whole_hts8 + China + 已发布月份 + 来源表存在` → `exact`，但只表示统计范围内的美国消费进口金额。
- 来源表缺少公告税号 → `none`，保留 `missing_codes`，不把主案例其他商品当替代。
- ex/文字限定/HS6/部分 HTS10 → `partial` 或保持未知，不能扩成完整 HTS8。
- 贸易金额不是逐票法律适用税基、税款、损失，也不产生因果结论。

## 验收

- Python 定向回归：S2 + S1/K/J 共 92 项通过。
- 页面回归：4 项通过，覆盖按钮请求的月份和显示状态已验证。
- 全量 `unittest discover`：1115 项；3 failures、48 errors 与历史冻结守卫/既有失败/SciPy ABI 环境问题一致，不能写成全量全绿。新增 S2 测试不在失败集合中。

## 尚未完成

当前使用合成公告做跨边界验收；还需要一份未参与开发的官方新公告及逐字段参考，完成 R2 迁移复核。R2 通过后，由 Astra 冻结 S3 的模型、端点、题目、预算和停止条件；在此之前不调用真实模型。
