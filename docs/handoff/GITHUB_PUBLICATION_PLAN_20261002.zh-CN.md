# GitHub 发布方案

日期：2026-10-02。GPT-6 Sol Max 完成设计；尚未修改 GitHub 设置或发布网站。下一阶段由 GPT-6 Luna Max 按本文执行。

执行更新：本方案已完成，发布与验收结果见 [发布记录](runs/20261002-GITHUB-PUBLICATION.zh-CN.md)。下文保留设计时的事实，不作为新的待办。

## 目标和范围

让访客从仓库首页看懂项目，直接阅读中英文案例和图表；需要自己提问的人可以下载数据，在本机运行助手。用户已要求公开现有仓库、发布 GitHub Pages、填写 About/网站/Topics，并整理两种语言的说明。

只做发布和阅读入口，不重测模型，不改 Agent、工具协议、原始数据或成绩，不增加云端后端、付费服务、前端框架或全球数据。当前模型测试已经收口。公开展示不提供自由提问，也不收取访客密钥。

## 已核实的事实

- 当前分支 `codex/local-release-candidate`，本地及远端为 `5340d0c8e51512a6a46911d77ae194faa080f06b`；工作区在设计入场时干净。
- `main` 本地及远端为 `a87554ccabcef20985917c067a0e6da7c1205801`，是候选分支的祖先，落后22个提交，无分叉。默认分支已经是 main，不能把“切换默认分支”误当成已经更新 main 内容。
- 仓库私有；Pages未启用；About仍是早期因果研究介绍，homepage为空，topics为空，没有Release。
- `web/design-preview/` 已有语言切换和四个案例，不是需要从零新做前端；目前没有公网部署。
- 原导出器 `scripts/build_public_showcase.py` 依赖发布者本机的原始会话。不能直接放进 GitHub Actions，假设干净克隆能访问 `.local/`。
- 已提交的四份案例与索引可直接通过现有校验函数；使用项目 Python 加 `-S`（不加载第三方site-packages）验证通过。CI可以只用Python标准库。
- 当前模型冻结312文件核验通过；本阶段不得改这些文件或刷新冻结摘要。

### 公开安全检查

检查了64个可推送提交、2219个不同blob，共133833165字节。针对API密钥、智谱密钥、GitHub令牌、私钥形状的扫描只命中一个明确的测试假密钥，未发现真实凭证。可推送分支、远端跟踪分支和标签的历史中，没有 `.local/`、`.workbuddy/`、`output/` 或根目录 `vendor/` 的文件。

最初使用 `git rev-list --objects --all` 时发现课程源码和PDF；随后逐个核对64个提交树以及Git引用，确认它们只属于 `refs/codex/turn-diffs/*` 本机检查点，不属于提交历史。这一怀疑已经排除。不要删除这些本机引用，不要因此改写历史；不得使用 `git push --mirror` 或将检查点引用推送到GitHub。

扫描不是凭证安全的绝对保证。实施收口仍要检查实际暂存文件和待发布产物，不输出密钥值；发现真实凭证则暂停公开操作，不擅自改写历史。

## 1. 分支和公开入口

正式版本使用 **main**，所有公开源码、安装和文档链接指向 main。现有候选远端分支暂留为此前版本备份，不删除，不作为第二套产品入口。

实施先在当前分支完成有限修改及验收，再提交；然后执行 `git switch main`、`git merge --ff-only codex/local-release-candidate`，只正常推送 main。无需合并提交、强推或改写历史。操作前重新核对远端：如果main出现不在候选祖先链中的新提交，停止分支操作并记录，不覆盖他人修改。

以推送后远端 main 的SHA、默认分支及实际首页内容为验收，而不是以本地提交完成为验收。候选分支是否删除不在本阶段权限内。

## 2. README：对应的中英文内容

保留根目录 `README.md` 为英文，`README.zh-CN.md` 为中文。两页第一行语言入口采用相同格式：英文页 **English** | [简体中文](../../README.zh-CN.md)，中文页 [English](../../README.md) | **简体中文**；实际根目录相对链接用文件名，不复制本文示意路径。下一行放网站、快速开始和模型测试的短链接。

两页必须采用相同顺序、功能事实、安装命令、案例和成绩；自然中文不要求逐字翻译。英文说明不能将中文长指南当成英语指南。增加 `docs/LOCAL_RUN.md`，与现有中文指南对应；更新两种语言的互链。

| 英文栏目 | 中文栏目 | 内容 |
|---|---|---|
| Introduction（标题下的正文，不另加栏目） | 项目介绍（标题下的正文，不另加栏目） | 美国商品贸易研究助手；AI调用查询工具，程序计算金额并生成图表；公开案例与本地使用的区别 |
| Features | 功能 | 商品检索、进口/出口、追问、登记政策、报告/PDF、无模型数据查询；不写成全网自动更新 |
| Demo | 案例演示 | 四个真正可打开的网页案例；展示实际提问、查询过程和报告，不再把JSON文件当主要演示入口 |
| Quickstart | 快速开始 | 克隆main、Python环境、Release数据下载和摘要、解压到新目录、核验、启动、模型设置与首次提问 |
| Model tests | 模型测试 | 当前四组v3成绩原样保留，链接对应语言长页；渠道、未完成项说明一次即可 |
| Data coverage | 数据范围 | 美国报告方；48个不连续进口月、12个出口月；全部伙伴汇总或中国；末月2026-07 |
| How it works | 工作流程 | 问题→模型选工具→程序检索/计算/检查→报告和追问；说明关键词/BM25政策检索的真实范围 |
| Documentation | 文档 | 安装、模型配置/结果、测试、源码目录；历史记录只留低优先级入口 |

开头可采用以下内容，实施时允许自然调整但不得增加能力承诺：

> TradeIntel is an AI research assistant for U.S. goods trade. Ask about a product's imports or exports, compare available months, and read related policy notices. The model selects query tools; Python calculates the figures and builds reports with charts and source references.

> TradeIntel 是一个美国商品贸易 AI 研究助手。用商品名称或编码提问，可以查询进出口、比较不同月份，也可以接着追问。模型负责选择查询工具，程序计算金额并生成带图表和出处的报告。

不用“一句话介绍”“三分钟看成果”“赋能”“闭环”“连接政策与数据”等包装词；不用连续短口号代替解释。明确快速开始所需条件，不承诺几分钟安装完。保留金额与数量、进口消费额与出口FAS口径的区别，不扩充投资或因果结论。

不批量改写历史文档。此前版本已有Git记录，无需再为这次README改写复制一份全量存档。根许可证未确定，不新增MIT或其他授权声明；已有前端第三方许可证保留。

### 结构参考

只学习入口组织和说明方式，不复制宣传句或功能承诺。2026-10-02通过GitHub API核对星数：

- [Dify](https://github.com/langgenius/dify)：157706 stars；中英文介绍、安装与文档入口分开。
- [RAGFlow](https://github.com/infiniflow/ragflow)：91590 stars；功能、快速开始和使用说明有明确栏目。
- [Open WebUI](https://github.com/open-webui/open-webui)：153759 stars；英文功能、安装、模型连接和指南分别介绍。

## 3. 双语前端与可部署构建

继续使用现有HTML/CSS/JavaScript，不再另建展示项目。保留地球国家标记、案例阅读、图表、折叠来源和打印布局。公开版导航为“项目 / 案例 / 示例报告”，本地版保留聊天工作台。

现有语言按钮要覆盖首页、四案例、报告、按钮、图表单位、空状态和安装链接；不是只切首页标题。新增明确语言URL `?lang=zh` / `?lang=en`：有效URL参数优先于已保存偏好，之后才是默认中文；切换语言保留case、report及hash，生成的案例链接也带当前语言。刷新、复制链接到新页面都能打开对应语言。没有有效lang时保持既有偏好；不把中文存档翻译冒充新的英文模型运行。

英文安装入口指向 `docs/LOCAL_RUN.md`，中文指向 `docs/LOCAL_RUN.zh-CN.md`，二者都在main。源码链接指向仓库main。更新“数据包未公开”等过时文本，但只有数据Release实际发布后，才声称下载可用。

### 构建路线：复用已提交的公开案例

新增小型 `scripts/build_github_pages.py`，作为**可在干净克隆运行**的静态装配命令；不重做原始记录导出器，不增加数据库或前端构建依赖。

- 读取 `web/design-preview/` 的公开四案例和索引，复用原导出器的ASSETS、IDS、JSON解析与字段校验函数。
- 复制允许的8个页面/样式/脚本/第三方许可证资产；从HTML明确移除workspace和live.js。标记缺失、重复或不符合预期则受控拒绝，不用宽泛正则继续发布。
- 政策data.json只取已有4个公开字段（data_version、note、rows、source_sha256）；与原导出器一致，不带本机source路径。
- 输出准确14个文件：上述8资产、data.json、cases/index.json、四份case JSON。拒绝符号链接、额外文件、私有字段、凭证形状和错误金额摘要；不发布audit、私有会话、model配置、原始回答或自由提问表单。
- 输出指定的新目录，例如 `tmp/pages-build/site`；存在则拒绝，不递归删旧目录。文件复制属于构建产物，源码编辑仍用apply_patch。
- 不调用原导出器的make_cases/verify（这些依赖私有原记录）；CI做公开结构与金额自洽校验。发布者本机仍先用原导出器核对原案例，然后比较两种构建的14资产逐文件SHA。两种检查各自说明作用，不将公开JSON自校验冒充原始证据核验。
- 新测试 `tests/test_github_pages_build.py` 用临时目录/公开fixture，可在无.local、无数据包、无第三方Python包时通过。覆盖缺资产、含live/workspace、篡改case、私有路径、额外文件和符号链接的拒绝。

README中四个网页入口采用最终Pages根路径，例如 `https://yemyu.github.io/TradeIntel/?lang=en&case=soybean-trade#cases`，中文用lang=zh。网站最终路径必须以部署返回值为准；不要多加源码旧preview子路径。

## 4. Pages、About和数据下载

### Pages工作流

新增 `.github/workflows/pages.yml`，使用[官方Pages自定义工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。仅main的push或手动workflow_dispatch发布，防止备份分支覆盖正式页面。仅构建输出site目录能上传，不得将仓库根目录传给upload-pages-artifact。

Python 3.12，使用标准库，无pip/npm安装。先跑独立构建测试和构建，再上传14资产。build权限contents:read；deploy权限pages:write和id-token:write，needs:build，environment为github-pages；并发组pages避免两次部署相互覆盖。部署job显式限制main，拒绝手动从其他分支发布。

以下官方标签与提交于设计日已查询；实施使用完整SHA锁定（注释标明版本），不额外追逐升级：

| Action | 已核对的版本 | 提交SHA |
|---|---|---|
| actions/checkout | v7 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| actions/setup-python | v6 | ece7cb06caefa5fff74198d8649806c4678c61a1 |
| actions/configure-pages | v5 | 983d7736d9b0ae728b81ab479565c72886d7745b |
| actions/upload-pages-artifact | v4 | 7b1f4a764d45c48632c6b24a0339c27f5614fb0b |
| actions/deploy-pages | v4 | d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e |

采用已有gh账户Yemyu，不切换其他账户。按用户授权将仓库改公开，以Actions作为Pages构建源；推送main并观察对应SHA的部署。失败记录具体Actions日志，不把后端启动或本地HTTP200当成公网成功，不转用付费托管。

### About

- Description：`AI research assistant for U.S. goods trade, with product lookup, policy retrieval and charted reports.`
- Website：Pages实际成功地址（预期 `https://yemyu.github.io/TradeIntel/`）。
- Topics：`ai-agent`, `tool-calling`, `international-trade`, `trade-data`, `data-engineering`, `data-visualization`, `python`, `policy-retrieval`。

不再使用早期trade-policy shocks/trade diversion因果项目介绍；不添加没实现的multi-agent、fine-tuning或global-data标签。

### 首次Release与数据

用户要求补齐展示信息；发布一个包含真实数据资产的首次Release，避免普通访客拿到源码却无法使用。标签拟 `showcase-20261002`，绑定本次最终main提交；标题 `TradeIntel — showcase and local data (2026-10-02)`。标签已存在但内容不匹配时停止，不覆盖或移动标签。Packages没有真实包就留空，不虚构npm/PyPI发布。

复用已核验原文件 `tmp/handoff-runs/trade-demo-data-20260927-isolated-v2.zip`，67464901字节；SHA-256为 `1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`。ZIP路径无越界或符号链接，124份数据大小与摘要全部符合清单；另外两份文件是BUNDLE_MANIFEST.json和BUNDLE_README.zh-CN.md（总126个文件）。不要误报“ZIP额外文件=坏包”。原README中的TradeShock是历史名称，不改原ZIP以保持摘要；Release及新安装文档使用TradeIntel。

Release附ZIP和校验值文本，提供中英文说明：数据范围、解压到新独立目录、先verify再run_web、API由本地用户配置、不含政策原文数据库/原始Census ZIP/模型密钥/MySQL数据。源码由GitHub自动生成，不重复上传含本地配置的源码压缩包。

先重核ZIP摘要，再上传，核对GitHub资产名称、大小和实际下载摘要；通过后更新README/安装/前端的下载链接，不能只验证自己磁盘上的文件便称公网下载成功。无Release权限时不继续造链接，记录阻碍。

## 5. 实施顺序和验收

本阶段只交设计。后续切换GPT-6 Luna Max后，按以下顺序一次执行并收口：

1. 改双语README与对应安装指南、前端语言链接/文案；新增便携构建、独立测试和Pages工作流。三份长上下文仅更新顶部当前状态，不追加新的重复执行入口。
2. 本机跑原导出器的构建及复验，用新空目录；新Pages构建与原导出14文件SHA一致。无私有存档的最小检出文件集合也能跑新构建/测试，不以当前完整工作区假装干净克隆。
3. 跑 `node --test tests/*.test.cjs`（当前56项基线），相关页面/原导出Python测试及新增独立构建测试；新增双语参数与保留case/report的正反例。核对两份README栏目、安装命令、四组模型成绩和数据日期完全对应；检查涉及文档的相对链接、JS语法与git diff。
4. 核对312冻结仍一致、生产src和旧原答/数据无差异、实际暂存文件无密钥/私有目录/大数据ZIP。全仓1739项已知失败不属于本发布改动，不为了本任务重跑或刷绿全部历史实验。
5. 本地新开专用浏览器页，检查桌面与390px的首页、四案例和报告；中英文互切/刷新/分享深链接、图表单位、来源折叠、回案例和打印预览。不要使用用户当前活动页，不重发模型请求。
6. 提交有限修改，main快进并推送。公开仓库、启用Actions Pages、发布真实数据Release、填写About/Website/Topics；既有授权不反复询问。任何需要强推、删除、付费或真实模型实验的变化不在本方案内。
7. 以公网匿名读取仓库和网页为准，确认四案例JSON、脚本与许可证可访问，/api/路径没有应用服务，公开页面没有模型输入/密钥框。观察对应main SHA的Actions成功，再核验双语深链接与Release下载摘要。只有两者实际可用，才删掉当前说明中的“尚未公开”。
8. 更新 `docs/PUBLIC_SHOWCASE.zh-CN.md`、`docs/CURRENT_PRODUCT.zh-CN.md` 及三份长上下文顶部状态；在 `docs/handoff/runs/20261002-GITHUB-PUBLICATION.zh-CN.md` 保存实际提交、部署、Release和验收记录。必要的发布状态更新可正常再提交推送，不为一行状态创建新设计阶段。

验收通过后任务结束：交付一个main正式入口、可用的双语Pages、可下载的核验数据包和对应说明，不自动恢复模型优化、添加案例或收费部署。若遇现成方案没覆盖的局部衔接故障，保存最小复现后重新判断是否需要GPT-6 Sol High，不因文件多自动升级。
