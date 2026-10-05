# 测试说明

[🌐 English](TESTING.md) · [项目介绍](../README.zh-CN.md) · [模型结果](MODEL_SELECTION.zh-CN.md)

工程测试检查查询工具、报告存储、HTTP接口和页面。模型评测另行检查具体模型的任务完成情况；单元测试中的预设回复不算模型评测成绩。

## 页面测试

在项目根目录使用项目环境执行：

```bash
node --test tests/*.test.cjs
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_chat_workspace_assets test_trade_agent_report_view
```

Node测试使用DOM模拟环境，不是完整浏览器。页面导航、手机布局和PDF检查另行执行，见[展示页说明](PUBLIC_SHOWCASE.zh-CN.md)。

## 数据与Agent回归

部分Python测试需要已核验的贸易数据包或保存的评测记录，这些文件不随Git提交。缺少数据时，相关测试可能跳过；原始案例导出测试还需要对应会话。解释测试结果时，应先核对前置文件，不把跳过项当作通过。

本地文件齐全时执行：

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest \
  test_us_agent_retest test_us_retest_final \
  test_trade_agent_catalog_contract test_trade_agent_policy_merge_contract \
  test_trade_agent_mainline test_trade_agent_boundaries \
  test_trade_agent_request test_trade_agent_language \
  test_trade_agent_report_view test_trade_agent_metrics \
  test_chat_workspace_assets test_public_showcase
```

10月2日检查中，这组135项Python测试通过，网页路由测试另行执行。[仓库检查记录](handoff/runs/20261002-REPOSITORY-REVIEW-AND-PUSH.zh-CN.md)记载该次运行及环境。

## 独立静态网站构建

Pages构建只需要已提交的公开案例和Python标准库；CI使用Python3.12：

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-build/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-build/site
```

输出目录必须尚不存在。构建检查14份公开资源，并排除本地应用设置和会话。网站检查不会增加模型评测成绩。

## 完整测试集

包含早期实验和因果研究的测试命令：

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest discover -s tests
```

完整测试集尚未全部通过。10月2日运行了1,739项测试，记录10项失败和118项错误，包含子测试。已记录的问题包括冻结实验输入、日期相关授权测试资料，以及该环境中的四项SciPy导入错误，详情见仓库检查记录。

当前Agent回归是单独的一组检查，不表示上述问题已修复。测试和冻结证据继续保留。

## 模型评测

上述工程测试命令不调用模型API。模型评测使用固定题目、数据版本、配置、参考核验与调用预算。[模型测试](MODEL_SELECTION.zh-CN.md)列出五组配置的成绩、设置和评分方法。

## 文档检查

```bash
PYTHONPATH=src:.:tests .venv/bin/python -m unittest test_public_documentation
```

检查现行公开指南的本地链接、语言对应文件，以及私人计划文件是否退出跟踪。
