# v3 未见公告：来源筛选与离线材料

日期：2026-09-29。本记录是**答前材料锁定**，不是模型语义成绩、法律结论或真人省时证据。模型 API 0 次；新公告仅保存为 `disabled`，没有进入政策检索或贸易报告。

## 固定顺序与资格

沿用 [上一轮的三路官方检索快照与固定排序](../../announcement_reading_v2/unseen-20260928-screen/SCREENING.zh-CN.md)，已消费的首份 `2026-19516` 不再作为未见案例。下一位是 `2026-19517`；没有为寻找复杂题或容易题而跳位，也没有重跑搜索更换候选。项目文件检索仅见旧快照中的元数据及本次新增保存件，未见既有正文、参考答案或模型评分；同旧案的铝板命令、R2 的 Section 301 行动不是同一调查或决定性条款。

[Federal Register 公告页](https://www.federalregister.gov/documents/2026/09/24/2026-19517/n-cyclohexylbenzothiazole-2-sulfenamide-from-the-peoples-republic-of-china-postponement-of)和[GovInfo 官方 PDF](https://www.govinfo.gov/content/pkg/FR-2026-09-24/pdf/2026-19517.pdf)对应正式发布的 `2026-19517`，**2026-09-24**，91 FR 60600，国际贸易署、调查号 `A-570-234`。这份公告涉及中国来源 CBS 商品的美国反倾销调查，动作是**将初裁期限由 2026-10-14 延后 14 天至 2026-10-28**；并未作出反倾销税率初裁。它是进口贸易救济流程的正式公告，可检验“没有税率/例外时不编造”的处理，但**不是复杂的税率/多来源国/追溯条款样本**；即使后来答对，也不能推广为复杂新政策已读准。

## 原文边界与保存件

官方 PDF 共 1 页，页面上方还有前一则公告、右侧还有后一则公告。PDF 目视核对了本公告起止、题名、调查号、日期、初裁延期、文末和脚注 1—4；模型输入只取 Federal Register 按公告编号提供的单份完整 `<pre>` 正文，经 HTML 标签/实体解码，不裁剪脚注。公告自身无另附决定含义所需附件；文中引用的发起公告和申请信是背景出处，未冒充已随本案提供。若以后要求据这些背景文件做更广泛法律判断，须另外取原件。

| 保存件 | 用途 | 字节 | SHA-256 |
| --- | --- | ---: | --- |
| [metadata.federalregister.json](2026-19517/metadata.federalregister.json) | 官方 API 元数据与来源 URL | 3,508 | `7dd36159b6ae53ab22e6ae20fbc329b962d62581f7d58d80862e730517028190` |
| [source.federalregister.txt](2026-19517/source.federalregister.txt) | 官方单公告原始 HTML 包装文本 | 4,672 | `b6d7dc8d6ed4f10d102962495c5d502fc4ebe8dce35a57365a8600be98457050` |
| [source.govinfo.pdf](2026-19517/source.govinfo.pdf) | 官方版原件，含同页相邻公告 | 186,193 | `998eac7cd03c3ca133cd454beabf019a26e09f4fd5512e1435de693391651ac3` |
| [source.reading.txt](2026-19517/source.reading.txt) | 不含相邻公告的完整阅读输入 | 4,501 | `50ed2786ae6044f2f6bba64c10551b753eae671c2ef8dd3da0fb3facec13ce64` |
| [source-store.json](2026-19517/source-store.json) | 单来源、禁用状态、连续分段的文档存储 | — | `2e33448cb5ff1c0f7d426e4a97d1842b2faebc3b5d0e8c0ccaef80b0f42f5f0a` |

提取由 `scripts/prepare_announcement_reading_v3_source.py` 完成；它要求正文编号与结尾编号一致，拒绝覆盖既存文件。`doc_version=docver-e95b289ffe15d6cc`。原件及提取文本变动会改变哈希和文档版本，不能沿用旧参考或请求。

## 离线容量与尚未通过的门

[离线包清单](2026-19517/offline-pack/MANIFEST.json)读回验证：完整消息 **7,438/32,000 UTF-8 字节**，21 个段落锚点，所有锚点拼接还原全文；请求文件 SHA-256 `ea5ee9942da48d668788ef8835106b2eacde530c03d7409bf6ad43fe311a441f`，v3 源码 SHA-256 `947c54c78718f331b42efa8a83b5ba0cc394643e18cdb52571700d6bdbaaf05b`。**实际服务商 POST 尚未构造，34,000 字节门未验证**；这不是发请求许可。

新增来源准备测试 3 项与现有 v3 测试 10 项共 **13/13 通过**；离线包独立读回通过。PDF 原件、旧 `2026-19516` 冻结包与旧模型结果未改，未调用模型 API、未写 MySQL、未提交推送。`pytest` 未安装，测试使用项目 `.venv` 的 `unittest`，不因此修改依赖。

**下一步**先在任何模型回答前，按本公告原文逐条写答前开发者事实参考：调查性质、延期动作与新旧日期、国家/商品范围、没有税率初裁的边界，以及十个通用检查点的适用/未载事项；不能把“未提”自动写成“不适用”。参考与评分冻结后，再另做真实 POST/费用/一次性账本的假服务验收；真实收费调用仍须单案授权。
