# MySQL 数据层

这一目录保存数据库结构和验证查询。它们不会自动删除数据库或清空表。

## 安全配置登录路径

不要把密码写进项目文件，也不要把密码发到聊天中。在自己的终端里执行下面的命令，密码会由 MySQL 隐藏输入：

```bash
mysql_config_editor set --login-path=tradeintel \
  --host=localhost --user=你的MySQL用户名 --password
```

完成后可以用下面的只读命令检查连接：

```bash
mysql --login-path=tradeintel --batch --skip-column-names \
  -e 'SELECT VERSION(), CURRENT_USER();'
```

## 建表

```bash
mysql --login-path=tradeintel < db/schema.sql
```

核心表是：

- `policy_event`：一行一项政策事件；
- `policy_product`：一行一项政策中的一个 HTS8 商品；
- `trade_monthly`：一行一个“月份 × 原产国 × HTS10 商品”观察值。

质量参考表是：

- `origin_dimension`：稳定国家代码、当前显示名和历史别名；
- `policy_origin_mapping`：政策目标国到 Census 国家代码的显式映射；
- `hts8_coverage`：818 个政策商品各自的贸易覆盖状态。

贸易表的组合主键是 `(year, month, origin_code, hts10)`。它把项目已经确定的数据粒度变成数据库约束。

## 验证

```bash
mysql --login-path=tradeintel tradeintel < db/verification_queries.sql
```

查询 5 应该没有返回重复键；查询 3 应该返回 0 个孤立政策商品。导入完整 48 个月后，查询 4 应该显示 48 个月。

## 导入原则

先用一个小的月度文件验证字段和关联，再导入完整面板。重复运行前先检查表是否为空；本项目不默认执行 `DROP` 或 `TRUNCATE`，避免误删已有数据。

## 加载并验证质量参考表

质量审计完成后运行：

```bash
python scripts/load_quality_mysql.py --login-path tradeintel
mysql --login-path=tradeintel tradeintel < db/quality_verification_queries.sql
```

这个过程只写入三张小型质量参考表，不重新导入或清空 `trade_monthly`。重复加载前，脚本会检查目标表是否为空；只有确认内容可以替换时才使用 `--replace`。
