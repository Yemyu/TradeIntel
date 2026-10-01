# 美国重测：工具决策、候选与金额预留

RecordingModel 补录tool消息反馈（名称/调用ID/公开content），不记录assistant reasoning。audit_query_actions 根据真实search_products返回候选核对原始query_trade的商品、方向、伙伴、固定窗口；错误企图不会被后续正确查询掩盖。无法解析的候选为unknown；不把该局部检查当完整模型决策评分，finish/边界语义仍待审阅。

政策字段候选写入隔离runtime/policy-field-candidate.json：13字段，9known带原文完整引文；title/publication_date/exceptions/revisions明确unknown。商品采用text_limited精度，不冒称整税号适用。尚未submit、confirm或enable，生产与隔离公告均未因此启用。

RequestLedger.reserve_money 使用显式Decimal美元预留、文件锁、未知结果不释放，拒绝未授权/非有限/非正数/超预算。金额预留只是基础组件，尚未给真实请求确定可验证的保守上界，也未与wire预留原子合并；绝不使用byte/4伪造严格账单上限，live入口继续关闭。

验收：25项重测组件+其余相关回归，共46项通过，git diff --check通过。0API、未提交推送。

之前OFFLINE_SNAPSHOT绑定当时源码；本轮脚本变化后该快照应当失效，不重写旧哈希。正式就绪时需新版本快照，另纳入政策字段候选文件；原快照保留为证据。

本步结果：工具反馈/错误企图审计、13字段候选和金额预留基础完成，46项相关测试通过。
下一步：完成边界/finish审阅材料与最终离线清单，明确剩余人工许可后收口准备阶段。
下一步模型：GPT-6 Luna Max；原因：已有规则下整理和接线，不修改评测设计；切换：无需。
