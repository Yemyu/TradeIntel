# TradeIntel 本地运行

本说明随源码包提供。本地应用通过浏览器使用；贸易数据需从 [Release](https://github.com/Yemyu/TradeIntel/releases/tag/showcase-20261002)单独下载。完整安装指南：[中文](https://github.com/Yemyu/TradeIntel/blob/main/docs/LOCAL_RUN.zh-CN.md) · [English](https://github.com/Yemyu/TradeIntel/blob/main/docs/LOCAL_RUN.md)。

## 安装

建议使用Python3.13；完整安装记录使用macOS和Python3.13.3。会话与报告存储依赖POSIX的`fcntl`模块，原生Windows不能直接运行。

在源码目录执行：

```bash
python3.13 --version
python3.13 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
```

下载`trade-demo-data-20260927-isolated-v2.zip`，核对SHA-256：

```bash
shasum -a 256 "/path/to/trade-demo-data-20260927-isolated-v2.zip"
```

预期摘要：

```text
1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6
```

解压到新的数据目录，核验后启动：

```bash
mkdir -p .local
unzip "/path/to/trade-demo-data-20260927-isolated-v2.zip" -d ".local/trade-data-bundle-1"
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root ".local/trade-data-bundle-1"
.venv/bin/python scripts/run_web.py --trade-data-root ".local/trade-data-bundle-1"
```

核验应返回`"status": "verified"`。打开`http://127.0.0.1:8765/preview/`。终端保持运行；Ctrl-C停止服务。

## 提问与报告

在模型设置中选择智谱GLM、DeepSeek或千问，填写平台支持的模型ID和自己的API Key。保存不发送模型请求；测试连接和助手提问会请求所选服务商，可能收费。

可以先问“最近美国大豆进口有什么变化？”，再问“出口呢？”。回复中的报告卡片提供图表、逐月金额和出处，也可打印或保存PDF。不配置模型时，用数据查询模式手动确认商品和月份。

数据最新月为2026年7月；指定未收录月份时提示缺口。进口消费额与出口FAS分开展示，金额变化不能直接认定政策效果。已登记政策资料才能被检索，数据ZIP不包含完整政策库。

密钥、对话和报告保存在本地的`.local/`。共享项目源码时不包含该目录。

[模型测试](https://github.com/Yemyu/TradeIntel/blob/main/docs/MODEL_SELECTION.zh-CN.md) · [公开案例](https://yemyu.github.io/TradeIntel/?lang=zh#cases)
