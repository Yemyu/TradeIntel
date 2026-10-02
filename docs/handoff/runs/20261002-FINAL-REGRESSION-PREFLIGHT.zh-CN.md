# 最后有限复测：离线准备与暂停点

日期：2026-10-02。按公开介绍与最后复测方案执行离线准备，建议档位 GPT-6 Luna Max。外部模型 API 0 次，没有提交推送，没有安装依赖。

## 安全进度

新目录 `tmp/handoff-runs/us-agent-final-regression-20261002-v3/`，使用原解释器 `.venv/bin/python` 与核验数据包 `tmp/handoff-runs/trade-demo-data-20260925`。

运行现有 `prepare-final`，生成十二轮/七会话的全新 request/session IDs，从 R01 开始，没有拼接旧成绩。问题文件和评分门不改；测试基准日期仍为 2026-10-01，数据截至 2026-07。

候选政策摘要与旧用户确认完全一致：`1ecacb7396265fefbc4540c3a7f0e63c91f82f103054c2bc3d291d33658810e6`。复制旧 approval 字段至新包 inputs/policy-existing-approval.json，再运行既有 submit/confirm 路径启用新隔离副本。保留原授权消息摘要与确认者，未虚构新的人工逐字核查，也未把政策确认当付费许可。

生成 OFFLINE_SNAPSHOT.json，绑定实际源码、政策、参考和数据，live_ready=false。**没有 FROZEN_MANIFEST.json，没有收费 permit，没有发送账本或模型答案。**

## 实际验收及两个局部问题

1. 现有 acceptance 跑 120 项：118 项通过、2 项报错，回执完整保留在 inputs/OFFLINE_ACCEPTANCE.json，passed=false，107.588 秒。两处均是 ContinuationTests 复制旧 v5 并按原父冻结校验，报 Ancestor evidence changed。
2. 只读逐文件核对，变化的是此前已修复的 trade_agent.py、trade_agent_tools.py、trade_classification_catalog.py；不是本轮又改了这三个文件。旧 v5 应继续拒绝新源码，不改父哈希刷绿。旧 FROZEN_MANIFEST SHA：`1c2cce88c83169c786a2c518fee2610821ef4b1eb1448f7f967585d84166e3dc`。
3. 新增 v3 catalog/policy merge 两套合同回归独立运行，15/15 通过，24.778 秒，不算真实模型成绩。
4. 新 prepare-final 使用 build_reference 的默认 core12，核数参考只有 2025-08 至 2026-07。旧 v5 曾改为 manifest_available，支持48进口月/12出口月；新批从 R01 完整开始，也可能输出更长历史附加报告。当前新参考不足，不能再次将无法核验误判成模型错数据。已有构建器支持 manifest_available，无需新增数据或评测框架。

这是预检发现的评测接线问题，未发送模型请求，不能给新准确率。未跑全仓测试、浏览器、PDF；文案阶段验证保持有效。

## 配置与价格核对

只读核对本地配置：base_url=https://api.deepseek.com，model=deepseek-flash，temperature=0，timeout=90，thinking enabled，reasoning_effort=high，max_tokens=8192；密钥存在，未打印或写入实验材料。

通过官方中文价格页核对并下载原 HTML 至 inputs/price-source-20261002.html：[DeepSeek 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)。页面列 deepseek-flash 对应 DeepSeek-V4.1-Flash；高峰缓存未命中输入2元/百万、输出8元/百万，空闲价减半。正式发送仍须核最新文档/响应与账户，本轮不验证密钥连通，不把网页价格当实际扣费。web读取超时后使用curl访问官方站，不发送凭证。

## 下一阶段最小动作

建议 GPT-6 Sol High：故障已有明确日志与复现，只需处理现行验收入口与历史冻结测试的局部依赖，不必重设计产品或升级 Astra。

- 确定最小方式让**新完整十二轮验收**使用自包含 fixture；保留旧 v5 新源码应拒绝的断言，不简单删掉失败或刷新原哈希。现有续批模拟通路测试也要保留，不因这次不续批便取消安全测试。
- 让新完整批次显式采用 manifest_available 核数参考，并回归原核心金额不变、历史附加报告可核对、未知仍未知、评分参考不进入模型输入。
- 评测源码改变后创建另一新目录，保留本次失败回执和离线快照；统一验收通过再正式 freeze。
- 准备新 freeze 绑定的有限许可请求：单 DeepSeek Flash/high，十二轮、48 HTTP、120分钟、10元人民币规划门，6轮/12工具/8192输出，异常停止无自动重试。未获得新明确许可就不调用。旧 v5 不重启，旧许可不复用。

本轮不实施上述局部修改；先在阶段交接时等待手动切换确认。不可改变问题/采纳门、生产工具协议、调用上限、原数据、历史答案和冻结记录，不新增模型横评、国家或架构。

本步结果：新离线包和失败证据已保存，118/120及新合同15/15，正式冻结暂停，0模型API。
下一步：修正评测入口的历史依赖与参考覆盖，重新离线验收后冻结。
下一步模型：GPT-6 Sol High；原因：两处可复现的评测接线需局部判断；切换：请切换后确认。
