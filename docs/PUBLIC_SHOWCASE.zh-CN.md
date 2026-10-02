# 案例展示页

[项目介绍](../README.zh-CN.md) · [本地运行](LOCAL_RUN.zh-CN.md)

展示页提供项目介绍、四个案例的问答和查询步骤，以及图表报告。不需要API Key，也不产生模型费用。自己提问需要本地运行；静态网站不能运行Python后端。

## 四个案例

| 案例 | 内容 | 类型 |
|---|---|---|
| 大豆进口，接着问出口 | 在同一对话中换方向，分别读进口和出口报告 | 保存的模型参与查询 |
| 豆油不是原料大豆 | 按名称查询豆油1507，查看十二个月进口变化 | 保存的模型参与查询 |
| 钨和光伏材料 | 五类商品的公告背景、金额和中国来源份额 | 资料编辑报告 |
| 所问月份还没有数据 | 所问八月未收录，模型改查七月被程序拦截 | 没有生成报告 |

金额、时间、来源和运行身份保留原记录。英文对话是中文记录的阅读翻译，不是另一轮模型回答。各模型任务表现集中在[模型测试页](MODEL_SELECTION.zh-CN.md)查看。

## 打开源码中的页面

用静态网页服务打开 `web/design-preview/`，可阅读四个案例；不要把静态页面中的提问入口当成本地服务。正式公开构建会移除提问和模型设置。

公开网站：[中文](https://yemyu.github.io/TradeIntel/?lang=zh) · [English](https://yemyu.github.io/TradeIntel/?lang=en)。语言切换保留当前案例和报告，刷新后仍使用链接指定的语言。

正式源码使用 `main`。`codex/local-release-candidate` 保留为此前候选版本，不是另一套使用入口。

## GitHub Pages构建

Actions从已提交的公开案例构建网站，不需要发布者的私有会话、数据补充包或API Key。下面的命令只需Python3.12标准库，输出目录必须不存在：

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-build/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-build/site
```

`.github/workflows/pages.yml` 只发布这14个静态文件。它检查公开记录的结构和金额自洽，不代替下方发布者对原始存档的核对。2026-10-02发布时，两种构建的14份文件SHA逐一一致；公网文件也已与核验产物比较。

## 发布者构建和核验

以下命令依赖发布者本机的原始存档，访客无需执行。选择不存在的新输出目录：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --output tmp/handoff-runs/showcase-new/site
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --verify tmp/handoff-runs/showcase-new/site
PYTHONPATH=src:. .venv/bin/python scripts/serve_public_showcase_qa.py --site tmp/handoff-runs/showcase-new/site
```

打开 `http://127.0.0.1:8897/TradeIntel/preview/` 检查仓库子路径。构建只包含14份允许的静态资源，不带live.js、提问表单、密钥、私有路径、原始模型响应或待审阅草稿。审计保存在同级audit目录，不上传到网站。源文件变化、字段越界或输出目录已存在时，构建会拒绝，不覆盖旧文件。

## 交付状态

完整本地查询需要[Release中的数据补充包](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)，包含124个数据文件、清单和说明。ZIP约64 MiB，已核对公网下载与原包SHA一致；安装步骤见本地运行指南。普通Git克隆仍不含这些数据文件。

已有案例PDF检查见[打印记录](handoff/runs/20261001-U2-PRINT-PDF.zh-CN.md)。本次发布没有重做PDF打印或其他系统安装；手机390px布局、语言切换和公网案例另做浏览器核对。展示页由GitHub Pages托管，没有付费云端后端。
