# MySQL 同版前置核查（2026-09-24）

只读检查，未启动服务、未写数据库。

- 客户端 `/usr/local/mysql/bin/mysql`、`mysql_config_editor` 的 `tradeintel` 登录路径存在，用户为 root；本机 socket `/tmp/mysql.sock` 和 127.0.0.1:3306 都无法连接，未发现 `mysqld` 进程。安装方式含 Oracle MySQL 的 launch daemon，不应擅自改系统服务。
- 当前已发布文件：进口 `census-us-import-hts10` 版本 `dd9801492e80268e51480b08c2edcbf495aba3ce01b7ee64739566f67a151ef8`，48 个已加工月；出口 `census-us-export-scheduleb10` 版本 `4308e4a820cd86bb6a19e223b4ae887fe0a030eef4a8af0c1ce96cb8c30a4b9f`，12 个连续月。
- `db/schema.sql` 有 `trade_dataset_release`、`trade_dataset_month` 和 `trade_import_hts10_monthly`，但无通用 Schedule B 出口明细表。`scripts/load_mysql.py`、`scripts/load_quality_mysql.py` 是旧政策/质量数据路径，不承担当前双向快照装载。
- 进口月 CSV 包含中国/全部来源消费进口额与 observed 状态；出口月 CSV 包含 `scheduleb10`、目的地代码、本国产品 FAS、再出口 FAS、总出口 FAS 与观察状态。不能把两个方向的编码、金额口径或来源视为同一种字段。
- 两份清单的已加工行数分别为进口 840,463 行（48 个月）和出口 3,769,576 行（12 个月）。现有进口表按 `CHINA`/`ALL_ORIGINS` 分行保存，因此完整镜像预计需要 1,680,926 条进口行；这只是装载规模估计，并非 MySQL 已装载记录数。
- 当前产品查询仍以已发布 CSV 为准。即使后续建立 MySQL 镜像，也须把“版本记录已建”和“全部月份通过逐月对账、可查询”分成不同状态；不能因插入版本记录就切换产品读取来源。

下一步先决定最小 schema/装载/对账约束：版本与月清单先绑定，按各方向已有指标存入，检查月数、行数、金额汇总与源文件摘要，失败不发布为可查询副本。设计确定后再实施；用户启动现有 MySQL 前，只能进行离线测试。
