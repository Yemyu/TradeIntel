# P4 出口接入：来源核查（仅事实盘点，未定实现方案）

## 本轮结论

- 项目已有 2025-01 至 2026-07 的美国进口可查询文件；尚无出口原包、出口加工文件或出口查询适配器。`trade_data_repository.py` 明确只允许 `flow=import`。
- 美国 Census 2026 年商品贸易出口月包可公开下载；2026-07 链接为 `https://www.census.gov/trade/downloads/2026/Merch/ex_m/EXDB2607.ZIP`。本轮只验证该地址返回 HTTP 200、类型为 ZIP，**没有下载或解析数据**。
- 出口使用 Schedule B，进口使用 HTSUSA。2026 Schedule B 第 12 章的大豆 1201 下有 `1201100000`、`1201900005`、`1201900095`；与现有进口 HTS10 组不同。不能将进口的完整十位码直接用作出口筛选。
- 出口月包中，`EXP_DETL.TXT` 同时含商品十位码、目的国、地区、月份、国产/再出口标记及月度出口额，适合回答“大豆出口到某国”；`EXP_COMM.TXT` 可用于独立核对按商品汇总。`EXP_CTY.TXT` 仅按目的国汇总，不含商品码，不适合回答商品×目的国问题。

## 设计阶段必须先定的事项

1. 报告默认给“总出口”（国产出口与再出口之和）还是“国产出口”；必须在报告中说清，不能把二者重复相加。
2. 美国进口和出口若做同页比较，只能分别标出方向、金额口径和分类体系；按 1201 等共同上层类别比较前，要核对两个分类版本的覆盖是否等价，不将十位码硬合并，也不将金额差直接解释为贸易差额或政策效果。
3. 选择 `EXP_DETL.TXT` 的聚合键与目的国映射，并用 `EXP_COMM.TXT` 做同月/同商品/同国产或再出口标记的金额对账；测试重复地区、未观察与真正零值的区别。
4. 原包摘要、加工版本、商品分类年份与月度缺失必须分开登记；先用一个月份的大豆最小样本验收，再扩大至所需窗口。
5. 估算月包大小、下载与存储成本，明确失败停机门；不要在方案固定前批量下载。

## 官方依据

- [Census 2026 Data Products](https://www.census.gov/foreign-trade/data/dataproducts.html)：月包入口，以及出口用 Schedule B、进口用 HTSUSA 的说明。
- [Census Export Record Layout](https://www.census.gov/foreign-trade/reference/products/layouts/exdb.html)：`EXP_DETL.TXT`、`EXP_COMM.TXT`、`EXP_CTY.TXT` 字段和固定宽度。
- [2026 Schedule B 第 12 章](https://www.census.gov/foreign-trade/schedules/b/2026/c12.pdf)：大豆 1201 的出口商品编码。

本轮未改代码、未运行测试、未调用模型 API；现有进口查询验收结果保持不变。
