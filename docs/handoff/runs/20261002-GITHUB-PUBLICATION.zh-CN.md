# GitHub发布记录

日期：2026-10-02。按已确认的发布方案执行，没有新增模型请求、改题、修改原回答、数据或旧冻结记录。

## 已发布

- 仓库 `Yemyu/TradeIntel` 为PUBLIC，正式分支main。main通过快进包含原候选内容，没有强推、删除分支或改写历史；候选分支保留备份。
- 网站：[中文](https://yemyu.github.io/TradeIntel/?lang=zh) · [English](https://yemyu.github.io/TradeIntel/?lang=en)。静态只读四个案例，没有模型设置、提问表单或Python后台。
- [Pages构建与部署](https://github.com/Yemyu/TradeIntel/actions/runs/36968588219)在源码 `ddc65969559a2d0e9c87404f17db1609ecfca391` 上成功，两项job均success。
- [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)绑定同一完整源码SHA，包含数据ZIP与SHA256SUMS，不是空版本。后续文档收口在main正常追加；不移动已发布tag。
- About更新为美国商品贸易研究助手，homepage填实际网站，Topics包含ai-agent、tool-calling、international-trade、trade-data、data-engineering、data-visualization、python、policy-retrieval。

GitHub第一次Release创建因缩写target无效被拒绝，改用完整SHA；随后ZIP上传遇DNS错误，保留已有draft，在确认缺失资产后只上传ZIP，核对服务端摘要再公开。没有删除或重建成功版本。

## 文档与前端

两种README栏目、功能、安装命令、案例和模型成绩对应；中文版使用“快速开始”，去掉口号式栏目。新增英文LOCAL_RUN，安装页面各自链接对应语言。语言URL优先于存储偏好，切换保留case/report/hash，案例和报告链接携带语言。

新增便携构建器与Pages工作流，从已提交公开案例装配14份文件；不依赖发布者私有会话。原始存档导出器仍保留，公开结构自校验不代替原始证据核对。依赖不作全局安装。

## 验收

| 检查 | 结果 |
|---|---|
| Python界面、静态构建与报告 | 24/24 |
| 全部Node页面测试 | 59/59；是DOM测试，不冒充浏览器 |
| 最小源码副本、Python标准库构建 | 7项测试通过，14资产构建通过；没有.local或贸易数据包 |
| 原始存档导出与便携构建 | 14/14文件SHA一致 |
| 匿名读取公网资产与便携构建 | 14/14文件SHA一致，首页HTTP200 |
| 数据ZIP匿名下载 | 67,464,901字节，SHA与原包及服务端digest一致 |
| 当前模型冻结 | 312文件均未变化，清单SHA保持a0551b699e660d0ab755ae7bec895eed01df307aeb637508648b0e5c0abebaa2 |
| 暂存文件凭证形状扫描 | 首批17文件零命中；私有目录、ZIP和运行产物未暂存 |

数据ZIP SHA：`1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`。公开下载副本位于忽略目录 `tmp/handoff-runs/github-publication-20261002/downloaded-data.zip`，未进入Git。

使用自己新开的浏览器页验收，不操作用户原活动页。本地四案例、中文政策报告、英文出口报告、语言切换及刷新保持通过；390px手机布局无横向溢出（scrollWidth=clientWidth=390），验收后恢复默认视口。公网中英首页及大豆案例显示正常；进一步打开公网报告时出现ERR_CONNECTION_CLOSED，另一次公告JSON读取未完成显示“案例暂不可用”。没有绕过安全设置或据此扩大修改。公网报告浏览器检查未完整通过，不把14文件摘要匹配写成全部浏览器路径通过。

本次未重做PDF、Windows安装或全仓历史测试。此前全仓1739项中的10失败和118错误保持原记录，不刷哈希称全绿。发布后核对仓库PUBLIC、默认main、网站和Topics、Release非draft及资产摘要，临时本地服务器已停止。

## 收口

最新状态已写入STATUS、PROJECT_PLAN和PROJECT_CONTEXT_REFERENCE；[项目评价](../../PROJECT_REVIEW_20261002.zh-CN.md)包含各环节评分及与汽车市场、硬盘预警、电动车问卷、实体匹配、LoL研究的比较。对其他项目仅审阅现有材料，没有宣称重跑实验。

当前作品发布目标完成，不新增收费实验或为弱模型无限修复。公网浏览器网络中断作为验收局限保留，访客可使用公开网址；自由提问使用本地版本。
