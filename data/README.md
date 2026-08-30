# 数据来源与保存策略

## 1. 项目使用的官方贸易数据

本项目使用美国 Census 的 **Merchandise Trade Imports** 数据。它提供按美国 HTS 商品编码、原产国和月份划分的进口记录，并包含进入消费金额、数量和其他贸易字段。

- 数据说明页：[Census Merchandise Trade Imports](https://www.census.gov/foreign-trade/data/IMDB.html)
- 官方文件 URL 模式：`https://www.census.gov/trade/downloads/{year}/Merch/im_m/IMDB{YY}{MM}.ZIP`
- 研究范围：2016 年 1 月至 2019 年 12 月
- 当前样本：
  - [2018 年 7 月官方压缩包](https://www.census.gov/trade/downloads/2018/Merch/im_m/IMDB1807.ZIP)
  - [2018 年 7 月盘点报告](./processed/trade/census_2018_07_inventory.json)

## 2. 为什么不把 ZIP 提交到 GitHub

每个月的 ZIP 都包含完整进口明细，48 个月合计约 7.5GB。它们是公开历史文件，不适合放进 Git 仓库，也没有必要长期占用项目目录。

处理方式是：

1. 需要处理某个月时，按上面的官方网址下载；
2. 读取期间保持原文件不变；
3. 在结果中记录 URL、文件名、下载时间、文件大小和 SHA-256；
4. 处理成功后可以删除本地 ZIP；
5. 以后重新下载时，先比较 SHA-256。不同就说明官方文件发生了修订或下载不一致，不能静默覆盖旧结果。

因此，项目追溯依赖的是“官方链接 + 版本指纹 + 解析规则”，而不是把原始压缩包永久放在仓库里。

## 3. 当前结果里的来源字段

当前样例结果表包含：

- `source_url`：官方来源网址；
- `source_file_name`：原始文件名；
- `source_sha256`：下载文件的 SHA-256 校验值。

盘点报告还记录文件大小、下载时间、所需的 ZIP 内部文件和定长字段布局。

## 4. 什么时候需要重新下载原始文件

- 发现解析程序可能读错字段；
- 结果与其他官方总量无法对账；
- Census 发布修订版；
- 需要向审阅者展示某一行原始记录；
- 需要复现实验或进行数据审计。

这些情况都可以通过官方 URL 重新取得文件，不要求平时一直保存本地压缩包。

## 5. 批量整理 48 个月

使用项目中的可恢复脚本：

```bash
python scripts/build_trade_panel.py --start 2016-01 --end 2019-12
```

它逐月下载和处理，成功后删除本地 ZIP，保留每个月的来源清单和汇总结果。脚本可以重复运行：已经完成且来源未变化的月份会跳过，不会重复追加记录。

## 6. 数据质量层

完整面板生成并导入 MySQL 后，运行：

```bash
python scripts/audit_data_quality.py --mysql-login-path tradeintel
```

质量层会生成一份机器可读报告、一份中文报告、稳定国家代码维表、政策目标国映射和 818 个政策 HTS8 的覆盖表。`pass_with_review` 表示核心结构通过，但存在必须披露或限制使用的复核项；它不是无条件通过。

当前发现两个历史国家名称变化，并把 `86011000` 标记为“未观察、待复核”。后续国家分析必须按 `origin_code`，不能按历史名称拆分。

## 7. 描述性政策基线

质量审计通过后，可以运行：

```bash
python scripts/analyze_policy_case.py
```

程序把政策 HTS8 清单、目标原产国和 2018-07-06 生效日期连接到贸易面板，输出：

- `processed/analysis/policy_case_monthly.csv`：按月的中国、其他国家和全部国家金额；
- `processed/analysis/policy_case_country_change.csv`：各原产国的生效前后平均变化；
- `processed/analysis/policy_case_summary.json`：窗口定义、统计结果和限制。

这些是描述性结果，不是因果估计；2018 年 7 月被单独标为过渡月。
