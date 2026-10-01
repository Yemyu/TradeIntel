# 本地版交付方式：先做可复验的私下试用包

日期：2026-09-29。本文件是**交付方案**，不是已上传、已发给别人或已取得所有再分发许可的声明。第一版继续定位为本机商品贸易数据报告；静态展示页与实际 Python 服务是两件事。

## 推荐路线

**先制作两件彼此独立的本地候选文件，交给指定试用者的方式由用户决定；本阶段不上传。**

1. 精简源码包：只包含运行普通商品报告必需的 `src/`、`web/`（保留现有第三方许可文件）、`scripts/run_web.py`、`scripts/trade_demo_data_bundle.py`、`requirements.txt` 和专门写给试用者的简短说明。不要直接打包整仓：现有 1,703 个已跟踪文件中有大量历史研究/内部材料；当前另有未跟踪的课程参考、冻结实验和 PDF 产物。候选源码包要从显式清单建立，在干净目录用现成的三条真实问题和未知商品反例复验；任何缺失依赖都先查明，不暗中把整个仓库塞回去。
2. 数据包沿用已核验的 `trade-demo-data-20260927-isolated-v2.zip`，**不提交进 Git**。ZIP 67,464,901 字节（约 64.34 MiB），SHA-256 `1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`；124 个数据文件共 578,630,811 字节。ZIP 完整性和成员 SHA 已核对；包内是加工后的月度数据与商品索引，不含原始 Census ZIP、MySQL 文件或课程源码。接收者先核验再启动本地服务。

选择这条路线，是因为它能先检验“别人拿到文件能否运行”，又不需要在仓库里混入大数据、付费课程或内部实验。**不等于已经允许公开转发源码和数据**，也不改变仓库当前可见性。试用者、传输渠道和是否公开由用户另定。

## 公开发布留到第二步

如果以后选择公开提供数据，技术上可以考虑 GitHub Release **附件**而不是普通 Git 文件：GitHub 文档称单个 Release 附件上限为 2 GiB，现有 ZIP 约 64 MiB；普通 Git 文件超过 100 MiB 会被阻止，而且 GitHub 建议生成数据放在 Git 之外。[Release 限额](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)、[仓库大文件建议](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。这仅说明技术容量合适，不说明可以直接公开该包。

来源方面，包内美国数据可追溯到 Census 月度公开下载，中文 HS4 索引还记录了中国财政部页面/PDF。美国 Census 关于贸易数据的常见问题称发布其数据无需另申请许可，并要求使用者清楚标注数据来源及对自身分析负责；这**不能直接推定包里财政部索引或其他加工材料都能按同一规则公开再分发**。[Census 贸易数据问答](https://www.census.gov/foreign-trade/statistics/dataproducts/uto-help/faq.html)、[Census 引用指南](https://www.census.gov/about/policies/citation.html)。公开前逐项核对包内来源及拟发布文本，不将“可追溯”写成“已获授权”。

当前仓库根目录没有 `LICENSE`，只有 `web/design-preview/vendor/` 下的第三方许可。GitHub 文档指出，没有仓库许可证就不能把代码称为已开源；不能因用户购买课程就自动给参考源码加 MIT 许可。用户若想给**自己有权授权的代码**选 MIT，应先把第三方/课程来源与仓库内容边界核清，再由用户明确决定。[GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。

## 下一执行包的验收门

- 只在新的隔离目录生成候选源码包；原工作树、旧冻结件和现有数据不删不覆盖。显式清单必须排除 `.env`、`.local/`、`tmp/`、`.workbuddy/`、`output/`、`vendor/course-reference/`、未审阅的公告 v3/v4 实验与旧答。
- 对**实际候选包**检查文件清单、路径、明显凭证、第三方许可和摘要；现有工作树的文本扫描未命中高置信密钥模式，但没有覆盖二进制与 Git 历史，不能替代候选包检查。
- 在干净目录、独立虚拟环境、另附数据包条件下，运行数据 `verify` 和普通进口/出口/双向报告及未知商品拒绝、重启读回。测试结果按原样记录；当前 macOS 成绩不冒称 Windows 可用。
- 通过后只把候选路径、摘要和运行说明交给用户确认。**没有用户明确指示，不上传 Release、不改仓库可见性、不添加总许可证、不发送给第三方。**

若最小源码包无法在不加入大量历史文件的情况下启动，停止扩大复制，先定位缺失依赖；若发现付费课程代码、未清来源材料或凭证，停止外发并返回审查。静态 GitHub Pages 只能展示示例，不能代替这套本地服务。
