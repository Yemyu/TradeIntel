# 本地候选新环境依赖安装尝试（2026-09-27）

## 目标与隔离

从本地 `codex/local-release-candidate` @ `d6dc061` 克隆到独立临时目录，在 macOS / Python 3.13.3 下新建 `.venv`，尝试按仓库 `requirements.txt` 安装四个固定版本，再做 `pip check` 与产品路径复验。只在临时虚拟环境安装；不改系统 Python、全局 pip 配置、原工作区或数据包。不调用模型/MySQL，不推送。

## 实际结果

1. 新克隆与新虚拟环境创建成功。
2. 使用本机默认包索引时，访问 `https://pypi.tuna.tsinghua.edu.cn/simple/pypdf/` 遇 TLS `UNEXPECTED_EOF_WHILE_READING`，`pip` 重试后停止。
3. 仅对本次命令指定官方 `https://pypi.org/simple` 再试，遇 `CERTIFICATE_VERIFY_FAILED` / TLS EOF；`curl` 请求官方 PyPI 与 Census 网站也因 SSL 连接错误结束。没有关闭证书验证或把索引写进全局配置。
4. 临时 `.venv` 的 `pip list --format=freeze` 仅有 `pip==25.0.1`，四个项目依赖**一个也没有安装成功**。因此没有运行 `pip check`、依赖后的测试或完整安装验收。

这是当前终端 HTTPS/证书通道的环境阻碍；`pip` 所说的 `No matching distribution found` 由无法读取索引引出，不能据此断言固定包版本不存在。[PyPI 上的 `pypdf 6.16.2`](https://pypi.org/project/pypdf/6.16.2/) 页面可由独立浏览渠道读取，故也不能写成依赖清单本身失败。

此前的**普通商品报告**仍有无额外 Python 包的新虚拟环境干净克隆验收，见[主路径验收](20260927-CLEAN-CLONE-QA.zh-CN.md)。这次尝试既不推翻该结果，也不把整个 `requirements.txt` 安装冒称通过。下次重试须先恢复终端可信 HTTPS 或提供经核验的离线 wheel，再在全新虚拟环境复验；不使用 `--trusted-host` 等跳过证书校验的办法。
