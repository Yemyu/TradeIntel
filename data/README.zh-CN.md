# 数据

[English](README.md) | **简体中文**

[项目介绍](../README.zh-CN.md) · [本地运行](../docs/LOCAL_RUN.zh-CN.md) · [数据下载](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)

本地应用读取已处理的美国 Census 进出口数据。当前 Release 将124个数据文件与源码分开提供：48份进口月表、12份出口月表、60份商品分类索引、3份清单和1份中文商品检索索引。

## 范围与口径

| 数据 | 可用月份 | 分类与金额 |
|---|---|---|
| 美国进口 | 2016年1月至2018年5月、2025年1月至2026年7月，共48个不连续月份 | HTS10；消费进口金额，美元 |
| 美国出口 | 2025年8月至2026年7月，连续12个月 | Schedule B10；出口总额，FAS口径，美元 |
| 贸易伙伴 | 全部来源／目的地汇总，或中国 | 中国是美国统计中的伙伴，不是中国海关报告方 |

商品检索使用已发布的月度分类，不限于展示案例。进出口的商品分类和金额口径不同，应用分别展示，不直接相减当作贸易差额。缺失月份保持缺失。金额变化描述贸易活动，不能直接确定数量、价格变化或政策因果效果。

## 下载与核验

从 [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002) 下载 `trade-demo-data-20260927-isolated-v2.zip`。ZIP约64 MiB，解压后约579 MB，另外含 `BUNDLE_MANIFEST.json` 和简短中文说明。

SHA-256：

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

按[本地运行说明](../docs/LOCAL_RUN.zh-CN.md)将ZIP解到新的目录。在仓库根目录使用项目环境核验：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
```

返回 `"status": "verified"` 后继续。数据根目录必须同时包含 `BUNDLE_MANIFEST.json` 和 `data/`。核验检查清单、允许路径、文件大小、摘要及数据版本，不下载数据、不调用模型。日常查询读取文件，不要求MySQL。数据包不含应用源码、模型凭据、原始Census ZIP或完整政策文档数据库。

## 来源与目录

月度清单记录官方来源URL和原包摘要。已发布文件的摘要及商品分类版本用于复核查询。

| 位置 | 内容 |
|---|---|
| [processed/trade_hts10/manifest.json](processed/trade_hts10/manifest.json) | Census进口来源；HTS10月表通过Release提供 |
| [processed/trade_scheduleb10/manifest.json](processed/trade_scheduleb10/manifest.json) | Census出口来源、月表路径和摘要 |
| [processed/trade_classification/manifest.json](processed/trade_classification/manifest.json) | 与进出口版本绑定的月度商品分类 |
| `processed/policy/`、`processed/policy_exposure/` | 登记政策案例的元数据、结果及版本记录 |
| `processed/analysis/`、`processed/causal/`、`candidates/` | 早期研究结果和候选案例记录；部分仍被现有工具或测试读取 |
| `raw/` | 本地来源材料；原始压缩包不在贸易数据Release中 |
| `sample/` | 合成教学样例，与真实贸易观察数据分开 |

官方原包示例：[2026年7月进口](https://www.census.gov/trade/downloads/2026/Merch/im_m/IMDB2607.ZIP)、[2026年7月出口](https://www.census.gov/trade/downloads/2026/Merch/ex_m/EXDB2607.ZIP)。各月份的完整来源记录见上述清单。

政策检索只读取已登记并启用的文档。贸易数据包不提供完整政策库，也不能证明每笔交易适用某项公告。早期匹配和因果研究记录用于保存研究过程，因果识别不是当前应用功能。维护数据时保留来源记录与版本摘要，先核验新数据包，再调整应用的数据根目录参数。
