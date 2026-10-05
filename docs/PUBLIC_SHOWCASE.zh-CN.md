# 案例展示页

[🌐 English](PUBLIC_SHOWCASE.md) · [项目介绍](../README.zh-CN.md) · [快速开始](LOCAL_RUN.zh-CN.md)

[公开网站](https://yemyu.github.io/TradeIntel/?lang=zh)提供项目介绍、已保存的问答、查询步骤和图表报告。语言切换会保留当前案例和报告。自己提问请运行本地应用；这里展示的内容不会发送新的模型请求。

## 案例内容

| 案例 | 展示内容 | 记录类型 |
|---|---|---|
| 大豆进口，接着问出口 | 连续追问并分别查看进口和出口报告 | 保存的模型参与查询 |
| 豆油进口查询 | 识别豆油1507，查看十二个月的进口数据 | 保存的模型参与查询 |
| 钨和光伏材料 | 五类商品的公告背景、进口金额和中国来源份额 | 资料整理报告 |
| 所问月份还没有数据 | 八月未收录，改查七月的请求被程序拦截 | 缺数据处理记录 |

英文对话对应保存的中文记录。报告保留商品、时间、金额和来源；政策报告另注明资料整理日期。不同模型的任务表现见[模型测试](MODEL_SELECTION.zh-CN.md)。

## 从源码预览

在项目根目录执行：

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web/design-preview
```

打开 `http://127.0.0.1:8000/`，可以阅读已导出的案例，无需贸易数据包。新的查询、对话保存和模型设置由本地 Python 服务提供，启动方法见快速开始。

## GitHub Pages 构建

Pages 从已提交的公开案例构建网站，使用 Python 标准库；CI 使用 Python 3.12。无需模型密钥、私人会话或贸易数据包。选择一个尚不存在的输出目录：

```bash
PYTHONPATH=src:.:tests python3 -S -m unittest test_github_pages_build
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --output tmp/pages-build/site
PYTHONPATH=src:. python3 -S scripts/build_github_pages.py --verify tmp/pages-build/site
```

`.github/workflows/pages.yml` 部署14份允许的静态资源。构建检查案例结构、报告范围和金额计算；这不替代对原始记录的核验。在线展示不包含提问表单、模型设置、密钥或本地会话。

## 原始记录导出

维护者使用 `scripts/build_public_showcase.py` 从本机保存的原始记录导出案例。该流程需要原始存档，普通访客无需执行：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --output tmp/showcase-check/site
PYTHONPATH=src:. .venv/bin/python scripts/build_public_showcase.py --verify tmp/showcase-check/site
PYTHONPATH=src:. .venv/bin/python scripts/serve_public_showcase_qa.py --site tmp/showcase-check/site
```

检查地址为 `http://127.0.0.1:8897/TradeIntel/preview/`，用于确认仓库子路径下的页面与资源链接。审计文件保存在输出目录旁，不发布到网站。输出目录已存在时，导出脚本拒绝覆盖。

报告的 PDF 使用浏览器打印生成。既有[打印检查记录](handoff/runs/20261001-U2-PRINT-PDF.zh-CN.md)和[测试说明](TESTING.zh-CN.md)列出已执行的检查。
