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

仓库已有页面源码，公网展示尚未部署。本地地址不等于公开网址。

## 发布者构建和核验

以下命令依赖发布者本机的原始存档，访客无需执行。选择不存在的新输出目录：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --output tmp/handoff-runs/showcase-new/site
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --verify tmp/handoff-runs/showcase-new/site
PYTHONPATH=src:. .venv/bin/python scripts/serve_public_showcase_qa.py --site tmp/handoff-runs/showcase-new/site
```

打开 `http://127.0.0.1:8897/TradeIntel/preview/` 检查仓库子路径。构建只包含14份允许的静态资源，不带live.js、提问表单、密钥、私有路径、原始模型响应或待审阅草稿。审计保存在同级audit目录，不上传到网站。源文件变化、字段越界或输出目录已存在时，构建会拒绝，不覆盖旧文件。

## 交付状态

目前可提供源码和案例。完整本地查询还需要独立的124文件数据包，尚无公开下载地址；不放空的下载按钮，不将普通克隆说成可直接查询。

已有案例PDF检查见[打印记录](handoff/runs/20261001-U2-PRINT-PDF.zh-CN.md)。实际输入法、原生200%缩放和其他系统安装应分别记录，不用自动测试代替。页面或数据正式发布另行确认，不需要购买云服务器才能展示案例。
