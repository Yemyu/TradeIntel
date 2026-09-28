# 未见公告阅读提示：来源筛选与首份材料锁定

筛选时间：2026-09-28 13:48 UTC。范围与停止规则先见 [事前方案](../../../docs/handoff/ANNOUNCEMENT_READING_UNSEEN_PILOT_20260928.zh-CN.md)。本记录仅锁材料和离线请求，**不是模型语义验收，也不是省时证据**。模型 API 0 次，政策仍为 `disabled`，未启用或写入贸易数据库。

## 官方检索快照

通过 [Federal Register 公共检索 API](https://www.federalregister.gov/developers/documentation/api/v1) 按事前日期、机构、关键词和 `order=newest` 查询；机构 slug 由其官方 `/api/v1/agencies.json` 核得。各取前 50 条，合并去重后按发布日期降序、同日公告编号升序；50 条/路足够确定前 10 名，未用搜索引擎相关性排序。原始响应不重排地保存：

| 顺序 | 条件 | 官方查询 URL | 保存结果 / SHA-256 | API 匹配数 |
| --- | --- | --- | --- | ---: |
| 1 | USTR；`China tariff` | [查询 1](https://www.federalregister.gov/api/v1/documents.json?conditions%5Bagencies%5D%5B%5D=trade-representative-office-of-united-states&conditions%5Bterm%5D=China+tariff&conditions%5Bpublication_date%5D%5Bgte%5D=2025-01-01&conditions%5Bpublication_date%5D%5Blte%5D=2026-09-27&order=newest&per_page=50) | [search-ustr.json](search-ustr.json) / `7def66e952efeb99762a2f74b289d8c3a29d7d68146661f5b33ebbe23b598ce3` | 24 |
| 2 | CBP；`China tariff` | [查询 2](https://www.federalregister.gov/api/v1/documents.json?conditions%5Bagencies%5D%5B%5D=u-s-customs-and-border-protection&conditions%5Bterm%5D=China+tariff&conditions%5Bpublication_date%5D%5Bgte%5D=2025-01-01&conditions%5Bpublication_date%5D%5Blte%5D=2026-09-27&order=newest&per_page=50) | [search-cbp.json](search-cbp.json) / `75345de159522d8667a3150086f43bbb9acabae446c4f6d448965afc70a73788` | 21 |
| 3 | ITA；`China antidumping duty` | [查询 3](https://www.federalregister.gov/api/v1/documents.json?conditions%5Bagencies%5D%5B%5D=international-trade-administration&conditions%5Bterm%5D=China+antidumping+duty&conditions%5Bpublication_date%5D%5Bgte%5D=2025-01-01&conditions%5Bpublication_date%5D%5Blte%5D=2026-09-27&order=newest&per_page=50) | [search-ita.json](search-ita.json) / `12f9ee9096ed602222e69af01c2fd37461c1a0f839648dec4fb93a10500dd31a` | 874 |

合并排序的前 10 个不同编号依次为：`2026-19516`、`2026-19517`、`2026-19518`、`2026-19519`、`2026-19530`、`2026-19372`、`2026-19376`、`2026-19382`、`2026-19262`、`2026-19273`。第一份即符合本轮准入，故**后九份未打开作资格判断**；没有继续挑一个更容易的案例。项目文件检索在下载前未发现 `2026-19516` 的既有正文或评分记录；它不是本次设计中列出的已见材料。

## 锁定材料：FR 2026-19516

- [Federal Register 公告页](https://www.federalregister.gov/documents/2026/09/24/2026-19516/common-alloy-aluminum-sheet-from-the-peoples-republic-of-china-bahrain-brazil-croatia-egypt-germany)及[官方 GovInfo PDF](https://www.govinfo.gov/content/pkg/FR-2026-09-24/pdf/2026-19516.pdf)均标明已于 **2026-09-24** 发布，编号 `2026-19516`，91 FR 60591–60593；不是 public-inspection 草稿。发行机构为国际贸易署。
- 属美国进口贸易救济，涉及中国铝板与其他来源国；它处理反倾销/反补贴命令的**部分撤销和适用范围**，与已见 R2 的 Section 301 半导体行动不同。不能把这份公告解释成“中国全部铝板关税取消”或直接当作现行总税率。
- [原始 FR 文字呈现](2026-19516/source.federalregister.txt)含公告起止标记和附录 I、II；[官方 PDF](2026-19516/source.govinfo.pdf)为 3 页，公告从第 1 页中部开始、第 3 页近末结束，PDF 页面还含相邻公告，因此**模型输入不用整页 PDF 提取文本**。正文从 FR `<pre>` 提取，只去 HTML 标签/转义符，不删脚注、国家段、条件或两份附录；完整输入保存为 [source.reading.txt](2026-19516/source.reading.txt)。已对照 PDF 的公告编号、主要撤销条款、两份附录和结尾；这只是来源边界核对，不是法律效力审查。
- 原始 FR 下载件 `24,923` 字节，SHA-256 `e0689ed625bb56f564dd1063b1985bd59f8eceb32bbf6fb4f90e4084d6bf4707`；官方 PDF `229,813` 字节，SHA-256 `48a025b5cc0436cbe46636891ead9446519ad3972b48368c80e023c6007e6edb`；阅读文本 `24,741` 字节，SHA-256 `8ca8e250cec45f44dafb77b28d4e243db5439072221878ead7b85f645e5c06e0`。[API 元数据](2026-19516/metadata.federalregister.json) SHA-256 `7f9d21880a96b9f3b05fb0ac9a0a8ce29dee27345e853e5a70e9e89d34edd343`。
- [禁用状态的单来源文档存储](2026-19516/source-store.json)版本 `docver-4856274e93216a5e`，SHA-256 `9ec27097c35090c40a07a4883293732d78327ce2e652bddaf6dc9224750c75fc`；由现行 `build_document`/`build_document_store` 构建，原文连续分段，未启用政策。阅读包 [离线清单](2026-19516/offline-pack/MANIFEST.json)已用现有验证器读回：**54** 个完整段落锚点，实际请求 **27,615** 字节，低于 `28,000` 门 **385** 字节；`request_sha256=0ebde1623741467e34ef7cc7f2c9ce06046a4a9f0459e719129c3e58f57e8a39`。输入预算余量很小，提示词或源文若变，必须重新核验，不能裁剪法律条件保通过。

## 冻结边界与下一步

当前 Git 基点 `b5551385a614a048ca99c6141115fc25f8ecf118`，工作区另有既存未提交修改；本任务关键代码逐文件 SHA-256：`announcement_reading_suggestions.py` 为 `b335d0fbe9f6ea7f775367b68add36beaefa60637d91339a9216795982d30413`，`policy_documents.py` 为 `744f08e0e161eb82c57cf8a9d4ead96665438f5f15549351a27660582f1027e1`，离线准备脚本为 `c3699f2a8465a462102215acf35e16e6046cfcd45ca1520c8fca2eeb9638740a`。本次未改这些实现或旧 R2 证据。

**尚未写答前事实参考、未发模型请求、未做人类工作量实验。** 下一步先由未看模型回答的人依据这份已锁原文制作三字段原子事实参考，并逐条核对 PDF；参考和评分门摘要锁定前，不准把离线请求发给模型。开发者自行制作的参考须标“答前开发者参考”，不冒称独立法律金标。
