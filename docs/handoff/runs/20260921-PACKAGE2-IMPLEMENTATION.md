# 包2多期确定性事实与包3解释接线实施记录

日期：2026-09-21

模型建议：Luna最高。Astra已经裁定窗口、比较权限、来源结构与旧快照兼容；本轮按裁定执行代码接线。

## 本轮已完成

- `analysis_request.py` 增加月份算术、所选商品共同完整月份筛选和 `resolve_query_plan`。显示窗口与比较取数月份分离；同比基月会加入 `required_months`，不会把图表窗口外的基月误报为缺失。
- `policy_exposure_tools.get_policy_exposure_series` 增加可选 `include_origins`。默认旧返回形状不变；新路径在同一来源哈希和月度完整性检查后按原产地代码聚合，并验证来源金额守恒。窗口验收凭证优先按绑定快照窗口命名，保留旧登记窗口兼容。
- `temporal_evidence.py` 加强输入合同：拒绝错误状态、度量、来源范围、重复月份、重复商品和不完整发布序列；金额缺失不补零；未核验或不可比的跨期指标为 null 并给出原因；结果保存完整请求和 query plan。
- 新增多期 evidence 结构校验与中文开发报告渲染。报告只显示 display months，比较基月用于计算但不伪装成展示窗口；前五来源按金额排序，余项合计守恒。
- `session_brief.py` 新增 `build_temporal_session_brief`，固定绑定发布版本、复用既有查询器，并仅给六月到七月的已登记代码过渡记录授予 reviewed 权限。
- `session_store.py` 和 `web_app.py` 增加 `analysis-request-v1` 分派；旧单月/公告路径保持原合同，新的多期请求按自己的 evidence/hash 持久化，避免强塞旧 A3 catalog。
- v1 追问支持在已确认锚点上移动“上月”或明确月份，并产生候选请求；仍需再次确认。
- 新增 `public_report.py` 统一报告对象，程序事实、可选解释、观察清单和报告摘要分开保存；多期会话简报已返回该对象及可读 Markdown，便于后续一个前端同时展示事实和解释。
- `/api/session/draft` 已能读取 `temporal-report-v1` 的确定性 Markdown；仍不把它当作已审阅 AI 报告。
- 多期报告已补独立的 `temporal_draft_confirmation`：`reviewed → exportable` 和导出端点会同时核对报告对象摘要、渲染 Markdown 摘要、证据摘要、请求摘要、数据版本和响应类型；不会复用旧 A3/catalog 确认。
- 多期报告暂不允许套用 `/task/explanation/*` 的 A3 解释协议；该入口明确返回 Package3 尚未接入，避免把程序事实伪装成已审阅 AI 内容。
- 缺少比较基月或中间月份时不再让整份简报失败：服务端把缺口物化为 coverage/missing 或 comparison/unknown，并在报告中说明；展示窗口本身仍按绑定版本校验。
- `analysis-request-v1` 确认门现在只接受 registry 中 active/superseded 且通过 release 清单校验的版本；客户端不能直接注入公告 `policy_binding`，“最新可用”由服务器读取已绑定快照末月。
- 编码过渡 reviewed 记录会逐项核对绑定发布副本中的月度文件摘要；来源结构缺口会进入默认后续观察清单，不给出投资或政策动作建议。
- `public-report-v1` 在没有模型解释时也会生成有限的非建议性观察清单（下一期统计、来源结构/覆盖缺口或政策版本变化），避免报告只有数据表而没有下一步阅读入口。
- 包3已把 `public_brief_explanation.py` 合同接入多期会话解释的准备、提交、审阅和合并导出后端：模型只能引用最多六个既有观察和报告已经登记的观察项，文字禁止新增数字/日期/税号/网址/因果与建议。Luna审计补上了真实多期准备接口的字段分派，避免读取A3专用字段。

## 设计依据

详见 [Astra裁定](../ASTRA_PACKAGE2_RULING_20260921.zh-CN.md)。实际发布版本已核实为19个月、五商品、51个来源代码，2025-07基月存在；核验未调用模型API、未下载新数据。

## Luna最高审计与修复（2026-09-21）

用户担心此前误用 Luna 中推理造成遗漏；本轮按当前 Luna 最高重新核对核心链，没有调用任何模型或网络服务。

- 静态检查：`compileall`、`git diff --check` 通过。
- 定向回归：**173项全通过**，包括包1、包2、J1—J4、K1—K4、E1—E3以及本轮新增的多期公开解释链。
- 真实主案例离线贯通：多期程序报告 → public explanation prepare → chat simulation submit → 逐项审阅 → reviewed → exportable；确认了快照、证据摘要、报告摘要和最终导出的绑定关系。
- 修复一处真实错误：多期 `/api/session/task/explanation/prepare` 原先无条件读取 A3 的 `catalog_sha256/host_bindings`，现在按协议分别返回多期 `report_sha256/evidence_sha256/request_digest/data_version`，旧 A3 返回形状保持不变。
- 额外收紧：任务响应摘要必须与报告/证据本体一致；非法解释来源拒绝；快照派生字段重算；模型只能选择报告已有的后续观察项；解释目录优先包含锚点和比较观察，避免长窗口只解释早期月份。

全量 discover 仍会触发历史冻结哈希守卫、既有断言和本机 SciPy 二进制导入问题；这些不属于本轮新增，也没有改旧冻结记录刷绿。全量不应声称全绿。

## 当前限制与下一步

- 核心后端链已收口，但前端尚未按用户提供的参考网站完成展示；当前仍是单用户本地页面/接口。
- 真实 API 仍未调用；Luna最高只是开发期对话模拟，不能写成模型准确率。统一模型四题评测后置。
- 只有38180000的2026-06→07代码过渡记录可授予 reviewed；其他跨期比较保留 unknown。
- 不恢复因果识别、不新增多智能体/微调框架；新公告仍须经过登记、字段确认和贸易覆盖核对。

下一阶段：先由用户提供参考网站，再用 Luna最高实现一个简洁的首页/工作台/报告页；前端完成后才做固定四题的模型对照。若出现协议、版本绑定或统计方法判断问题，再切换 Astra 中审查。
