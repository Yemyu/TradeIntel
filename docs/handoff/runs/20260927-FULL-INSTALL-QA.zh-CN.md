# 本地候选完整依赖安装及主路径复验（2026-09-27）

## 环境与安装

在 macOS 上从本地分支 `codex/local-release-candidate` @ `95ef22d` 新克隆，使用 Python 3.13.3 新建项目 `.venv`。`requirements.txt` 四个固定版本均从官方 PyPI 安装成功：`pypdf==6.16.2`、`xlrd==2.0.2`、`numpy==2.2.6`、`scipy==1.15.3`；`.venv/bin/python -m pip check` 返回 `No broken requirements found`。

首次安装时，终端直连 PyPI 和默认镜像曾有 TLS/证书错误。此次 `pip` 使用测试环境已有代理与系统证书，未关闭证书校验，也未更改系统或全局 pip 配置。以下命令记录该测试环境的设置，不是通用安装步骤：

```bash
.venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir \
  --index-url https://pypi.org/simple \
  --proxy http://127.0.0.1:7897 --cert /etc/ssl/cert.pem \
  -r requirements.txt
```

这条命令的代理地址**只适用于本机当前配置**，不是给所有用户照抄的安装要求。没有用 `--trusted-host` 或其他跳过校验的选项。

## 实测结果

将独立数据包补入克隆后，清单核验为 124 文件、578,630,811 字节、三个版本摘要一致。Python 产品定向测试 28/28、Node 页面测试 18/18 全过。真实数据三条路径再次生成：2026-07 大豆进口 46,041,287 美元、玉米出口 1,637,235,741 美元、大豆双向进口 46,041,287 / 出口 889,379,312 美元。`/preview/` 返回 HTTP 200，大豆进口报告生成后重启本地服务，按报告 ID 读回 HTTP 200，报告摘要与 SHA256 不变。

此轮 0 次模型 API、0 次 MySQL；模型状态为 `not_run` / `not_requested`。因此可说**当前 macOS 上该本地 Git 候选加独立数据包可完成依赖安装和普通商品报告**，不能外推至 Windows、新电脑、公网部署、自动新政策、人工公告全链或模型内容质量。普通 Git 克隆仍不附带数据包；包的外部分发方式尚未决定。本轮仅本地提交记录，不推送。
