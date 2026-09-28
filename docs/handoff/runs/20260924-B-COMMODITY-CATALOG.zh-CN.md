# B 包：官方商品目录接入（2026-09-24）

## 结果

普通商品查询不再只认“大豆/玉米”。从已核验的 Census 月包读取 `HSDESC.TXT`（HS2/4/6 英文标题）和 `CONCORD.TXT`（进口 HTS10、出口 Schedule B 十位码），为已发布的 **48 个进口月 + 12 个出口月**建了独立目录；每月记录原包 URL、原包 SHA、两个成员的 SHA、目录文件 SHA、加工数据中实际出现的编码数。仅索引 `queryable_aggregate` 月份，未把保留原包但未发布的月份当可查数据。构建时逐月确认加工数据里的商品编码都存在于同月 `CONCORD`。最新目录版本：`a758a0236d12bea52cae670b99b05997a1b1c14d8442bcda7ea05bb3b436a632`。

中文搜索索引来自[财政部 2026 年进出口税则公告](https://gss.mof.gov.cn/gzdt/zhengcefabu/202512/t20251231_3981044.htm)附 PDF（本地 SHA256 `76af4db0b3af966ef4f95f4ffc6b4b2e34f1a95ef47f68e7299670a18b337d57`）。按表格标题严格提取 1,223 个 HS4 中文标题；当月美国目录有 1,243 个 HS4，其中 1,223 个与中文索引同码（约 98.4% 的**标题编码覆盖**，不等于日常中文提问成功率）。已逐项核对咖啡、茶、小麦、大豆、玉米、棉花等 9 个标题和来源页；另抽样检查 20 个自动提取项、渲染检查 PDF 第 158 页。其余自动提取标题在页面标明“以美国官方英文范围为准”，不把中国税则当作美国分类或税率依据。索引仍有未覆盖、同义词和跨年口径边界。

接口 `/api/trade/prepare` 对有候选的商品返回 `needs_product_choice`，卡片显示完整中文标题、美国官方英文范围、编码、方向、十位细码数和原包链接。用户选择后，服务端用 `selected_product_id + catalog_version` 再验问题、方向和所有目标月份的官方描述；报告入口必须携带同一选择和数据版本。篡改 ID、改方向、目录版本变化、缺目录文件或跨月描述不稳定均拒绝。月度金额仍由现有版本固定的数据仓库计算，模型不挑码、不改数字。

独立原包对照：2026-07 美国茶（HS4 0902）进口消费额，`IMP_COMM` 求和与查询均为 **55,602,508 美元**；2025-08 美国未梳棉（HS4 5201）出口额，`EXP_COMM` 求和与查询均为 **248,490,501 美元**。实际工作台走通“最近美国汽车进口有什么变化？”→选 HTS 8703 → 2025-08 至 2026-07 共 12 月数据报告；2026-07 为 **14,829,260,571 美元**，刷新仍可恢复所选范围和报告。新报告标题改用用户问题，正文不重复粘贴超长商品标题，完整范围放在报告末尾可展开查看。

## 验证与边界

- Python 定向 27 项（包含新目录 5 项、旧查询/出口/仓库回归）和 Node 页面 5 项通过；`git diff --check` 通过。浏览器实测候选→确认→报告→刷新。0 次模型 API 调用，未提交推送。
- 中文搜索是“标题和少量经核实的日常同义词”匹配，不是大模型自动归类。泛词会给多张候选卡；查不到明确说不可用，不猜测编码。进口 HTS 与出口 Schedule B 十位码分离；共同 HS4/HS6 才能用于双方向同码查询。
- 2016—2018 的进口月包已索引但与 2025—2026 **不连续**；中文索引依据 2026 年税则只作搜索辅助，历史范围仍逐月以美国官方标题校验。目录若重建，旧确认版本不能直接出新报告。八位 HTS 范围由当月十位码归并，页面明确标为推导范围，不伪称独立官方标题。
- 英文切换目前主要覆盖静态页面；本轮新增的动态候选/新报告控件仍以中文交互为主。模型解释、多模型统一验收、MySQL 同版核验和公共部署不属于本包完成项。

## 重建与复核

保留原包及加工数据齐备时：

```bash
/Users/ye/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/extract_mof_hs4_index.py --source data/raw/trade-classification/china-2026-tariff.pdf --output data/processed/trade_classification/zh_hs4_2026.json
PYTHONPATH=src .venv/bin/python scripts/build_trade_classification_catalog.py
PYTHONPATH=src:. .venv/bin/python -m unittest tests.test_trade_classification_catalog tests.test_trade_data_repository tests.test_trade_export_integration tests.test_trade_query_flow -q
node --test tests/trade_explanation_ui.test.cjs
```

原始 PDF 与月度压缩索引均属本地可重建材料，不放入 Git；只保留清单、中文搜索索引及解析代码。构建器的月度文件采用内容哈希文件名，先写完全部文件再发布清单。开发期间产生的旧无版本文件 60 份已清除；可从原包重建，不影响当前版本。
