# T1固定验收与干净目录复现

## 一条命令

在项目根目录运行：

```sh
.venv/bin/python scripts/check_t1_product.py --clean
```

这是当前单月贸易研究产品的程序验收，不是历史全仓库验收或真实AI评分。脚本里的GROUPS是固定测试目录；不是每轮手工挑几个通过的测试。新增功能时应先调整对应职责目录，再运行。未纳入的测试模块逐项列在report.json的unclassified_test_modules，不能算通过。已确认的历史2018/v21入口另外注明排除原因，其余不擅自统一称为历史测试。

| 职责 | 本次Python测试数 |
|---|---:|
| 请求与解析 | 23 |
| 政策事实与来源 | 12 |
| 计算与输出结构 | 7 |
| 业务完整链路 | 23 |
| 审阅与导出 | 13 |
| 数据版本与链接 | 11 |
| 候选案例隔离 | 1 |
| 网页服务接口 | 10 |

此外运行1项Node DOM测试。DOM替身测试不等于真实浏览器视觉或下载验收。

## 资源清单与隔离方式

复制目录：src、scripts、tests、web、data/processed/policy、data/processed/policy_exposure、data/candidates/solar2024。复制单文件：requirements.txt、data/raw/policy/review2025/cbp-63577329.html、docs/experiments/solar-brief-pilot-v1.zh-CN.md。

每次把这些目录展开成逐文件SHA-256清单，复制后再次校验。包含当前尚未提交的代码，所以该结果不意味着GitHub已经拥有相同版本。不会复制.git、.venv、项目tmp、用户配置或.env；遇到符号链接及明显密钥文件拒绝复制。原工作区数据不修改。临时副本在运行结束后自动清理，报告及日志写入项目tmp/t1-check-*，不覆盖上次结果。

子进程只继承显式白名单环境变量，使用临时HOME及只指向副本的PYTHONPATH。Python外网连接被审计钩子阻断，仅允许本机回环HTTP用于接口测试。模型边界使用模拟响应，不提供真实API密钥。

运行环境复用本项目.venv的Python及已安装Node，不安装工具到系统。因此这是**同一机器的干净代码/数据目录复现**，不是空白机器、全新依赖环境或容器证明。当前Python 3.12.13、Node 24.17.0。迁移时先在项目虚拟环境安装requirements.txt依赖；Node需单独可用，缺少Node则UI验收不通过，而非跳过当成功。

资源缺失时按报错中的路径恢复对应项目文件/完整发布目录，再运行；不能创建空文件冒充恢复。发布目录内哈希由业务版本校验继续检查。当前这套T1不需要旧2018因果面板；scripts/verify_portable_data.py与prepare_portable_data_bundle.py处理旧四文件便携包，不能替代这里的资源清单。官方原始资源地址可查对应policy_corpus.json/source.json；重新获取后必须通过原文哈希核验，不能为了通过测试改成新哈希。

## 2026-09-15执行结果

首次运行100项Python检查出现3个错误：复制清单遗漏solar-brief-pilot-v1.zh-CN.md，相关测试会验证协议指纹。补齐该资源后仍运行原集合，没有删除失败测试或修改其断言。

第二次：100项Python测试全部通过、0跳过；1项DOM测试通过。162个其余Python测试模块未分类、未运行，不计入通过率。报告保留全部名单和文件哈希。

- 首次日志：tmp/t1-check-wd_3m0ec/python.log
- 最终报告：tmp/t1-check-kwa5oq1l/report.json
- 最终Python日志：tmp/t1-check-kwa5oq1l/python.log
- 最终DOM日志：tmp/t1-check-kwa5oq1l/ui.log

## 意义及下一步

这证明当前固定T1集合不需要用户私人旧运行文件即可在代码数据副本中跑通；不证明模型解释一定正确，不证明全部仓库测试通过，也没有完成浏览器下载核验。

G1检查点C已有执行证据，A/B已有前序修复；仍待Astra中最终审查是否按原标准采纳G1。之后才进入既定G2真实模型对照，不新增实验方向、不扩充因果任务。本轮无外部模型调用，无提交或推送。
