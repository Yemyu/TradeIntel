# MySQL 镜像：表结构与离线核验器

日期：2026-09-25。范围是实现方案中的数据库表定义和不连接数据库的文件校验，不包含真实装载。

## 完成内容

- `db/schema.sql` 新增出口 Schedule B 月度明细表：一行对应一个月份、商品码和目的地；未观察的国产/再出口金额存 `NULL`，观察到的零保留为 `0`，总额须等于可观察分项。另加版本级验收记录，预计 SQL 行数与实际读回行数相等后才能登记。
- 新增 `trade_mysql_mirror.py` 与 `check_trade_mysql_mirror.py`。校验器逐月检查两套清单、加工文件摘要、月份、商品编码、重复键、观察状态、来源摘要和金额汇总，并提供导入用的规范化行映射；进口文件的一行会扩成中国与全部来源两行。
- 完整离线结果写入 `tmp/handoff-runs/mysql-mirror-offline-audit-20260925.json`。状态明确标为 `offline_file_audit_passed_not_mysql_verified`。

## 验收结果

- 8 项镜像规则单测全部通过：未观察不补零、观察到的零保留、重复 HTS10 拒绝、观察标志与明细数量不一致拒绝、出口金额不平拒绝、审计后文件改动拒绝。
- 当前 60 个月文件全量扫描通过。进口：48 月、840,463 条 CSV 行→预计 1,680,926 条 SQL 行，版本 `dd9801492e80268e51480b08c2edcbf495aba3ce01b7ee64739566f67a151ef8`。出口：12 月、3,769,576 条 CSV 行→3,769,576 条 SQL 行，版本 `4308e4a820cd86bb6a19e223b4ae887fe0a030eef4a8af0c1ce96cb8c30a4b9f`。审计摘要 `c5f661ff8110000924d0a838eb045c48d9910609a6d9662ad6c031fb626024ba`。
- MySQL 服务没有运行，因此没有在真实服务上执行 DDL、建表、导入或读回。阶段结束前再次用现有登录路径分别检查默认 socket 与 `127.0.0.1:3306`，两处都拒绝连接；未启动系统服务。API 调用为 0。旧装载脚本没有使用。

## 下一步

先做连接只读预检：若用户已启动本机 MySQL，则核对实际版本、现有 `tradeintel` 表的 `SHOW CREATE TABLE` 与剩余空间；如服务仍未运行，停在这里并请用户启动。结构兼容确认后，各装载 2026-07 进口/出口一月并逐行读回，再决定是否执行 60 月全量。遇到已有不一致行或表结构差异，不自动清理或覆盖。

## 2026-09-25 只读连接预检复查

- 现有登录路径可经 TCP 连接，服务器 MySQL 9.7.0，账号 `root@localhost`。`tradeintel` 当前 6 张旧表；未发现新镜像表。旧 `trade_monthly` 主键为年月、来源、HTS10，约 1,575,933 行、数据 356 MiB、索引 122.41 MiB；不修改旧表，后续使用独立的版本化镜像表。
- MySQL 数据目录所在卷约有 142 GiB 可用；`trade_monthly` 等旧表结构可读，root 具备建表与写入权限。`db/schema.sql` 仅含 `CREATE DATABASE/TABLE IF NOT EXISTS`，未见 DROP/UPDATE/INSERT 等破坏性语句。
- 当前项目虚拟环境没有 `mysql-connector`、`PyMySQL` 或 `MySQLdb`；MySQL `local_infile=OFF` 且 `secure_file_priv=NULL`，不能直接走 `LOAD DATA LOCAL INFILE`/服务器文件导入。原[设计](../MYSQL_TRADE_MIRROR_DESIGN_20260924.zh-CN.md)已经选定 CLI 分批 `INSERT`，上轮称“尚未决定 CLI 还是连接依赖”是误记；本轮仍未执行 DDL 或写入。
- 本轮相关镜像单测 8 项通过，`git diff --check` 通过。下一阶段需先锁定单月试载的可回退、可复核流程，再执行 2026-07 单月真实写入与逐行读回；全量 60 个月仍须等待试载验收。

## 同日方案复核

- [设计文档](../MYSQL_TRADE_MIRROR_DESIGN_20260924.zh-CN.md)已补单月试载执行细则：采用既定 CLI 分批 `INSERT`，每方向每月一个事务，按主键逐行读回；月记录只代表可查询，全月全行通过后才写整版验收标记。
- 复核 MySQL 9.7 `CHECK` 规则后，修正 `db/schema.sql`：`observed=1` 时金额显式 `IS NOT NULL`，防止空金额使约束表达式得到 `UNKNOWN` 并被接受。修改尚未施加到数据库。
- 当前工具执行环境对本地 socket 与 TCP 连接都返回权限错误 `(1)`；这不同于此前服务未启动时的拒绝连接。此前只读预检成功的数据仍有效，实际试载阶段需要可连接本机 MySQL 的执行环境。未执行数据库写入。
