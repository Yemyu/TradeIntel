# MySQL 镜像整版验收

日期：2026-09-25。状态：**通过**。

## 结果

- 批量装载命令按独立月份执行，计划 60 月，完成 60/60；每个月均写入后逐行读回，差异 0。已存在的 2026-07 月份只做核对，不重复写入。
- 进口版本 `dd9801492e80268e51480b08c2edcbf495aba3ce01b7ee64739566f67a151ef8`：48 月、840,463 条 CSV 行、1,680,926 条 SQL 行。
- 出口版本 `4308e4a820cd86bb6a19e223b4ae887fe0a030eef4a8af0c1ce96cb8c30a4b9f`：12 月、3,769,576 条 CSV 行、3,769,576 条 SQL 行。
- 批量完成后又做了一次完整只读复核：两套版本的所有月份、商品键、伙伴键、金额、NULL/真零、观察标志、来源摘要和月汇总全部一致。复核耗时约 55 秒。
- 复核通过后才向 `trade_mysql_mirror_verification` 写入两条整版记录；写入后读回字段与审计摘要一致。当前整版验收标记数为 2。
- 旧 `trade_monthly` 保留且只读核对仍为 1,600,952 行；新镜像明细总行数分别为 1,680,926 和 3,769,576。没有删除、截断或替换旧表，也没有改系统 MySQL 设置。

## 审计文件

- 批量过程：`tmp/handoff-runs/mysql-mirror-batch-20260925.json`
- 完整复核（未写标记）：`tmp/handoff-runs/mysql-mirror-finalize-readonly.json`
- 完整复核并写标记：`tmp/handoff-runs/mysql-mirror-finalize-20260925.json`
- 进口版本逐月摘要：`tmp/handoff-runs/mysql-mirror-verification-import-dd9801492e80.json`
- 出口版本逐月摘要：`tmp/handoff-runs/mysql-mirror-verification-export-4308e4a820cd.json`

## 验证

定向 MySQL 镜像测试 14 项通过，装载、批量装载和验收脚本均可编译，`git diff --check` 通过；全程模型 API 调用 0 次。网页报告仍以经过发布审计的文件快照为数据源，MySQL 当前是已验收的查询副本，不会被悄悄当成另一套实时数据。

## 后续边界

当前版本已经完成数据库同版验收。以后 Census 发布新月份时，应先生成新的文件清单和版本号，再运行离线审计、逐月装载、逐行读回，最后才写新的整版验收记录；旧版本保留，不能覆盖。整版验收不等于公网部署，也不代表模型解释质量已经通过。

本轮未提交、未推送。
