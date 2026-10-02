# 本地运行

[项目介绍](../README.zh-CN.md) · [当前功能](CURRENT_PRODUCT.zh-CN.md) · [模型测试](MODEL_SELECTION.zh-CN.md)

看案例不需要安装。要自己提问，需要运行本地服务，并使用自己的模型 API Key；只查数据时不需要模型。使用当前仓库源码即可，不需要重复下载旧源码 ZIP。

## 准备源码和数据

需要Python和独立贸易数据包。普通Git克隆不含这个包：124个已处理文件，解压后约579 MB，ZIP约64 MiB。包内有 `BUNDLE_MANIFEST.json` 和 `data/`，没有API密钥、MySQL数据库或原始Census压缩包。**目前没有公开下载地址**，首次使用前需要另行取得。

数据包v2的SHA-256为 `1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`。安装已在macOS验证；当前报告存储使用POSIX文件接口，Windows尚未验证。

在项目根目录使用已有虚拟环境，或首次安装：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

不要装到系统Python，也不要覆盖自己已有的环境。将数据解到新的独立目录，不要解到源码根目录覆盖已有数据：

```bash
mkdir -p .local
unzip "/实际路径/trade-demo-data-20260927-isolated-v2.zip" -d .local/trade-data-bundle-1
```

如果拿到目录包，可以直接使用。传给程序的目录需同时包含清单和data，而不是ZIP或内层data。先核验：

```bash
PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1
```

返回 `"status": "verified"` 后继续。核验不下载数据，不调用模型或MySQL。

## 启动网页

```bash
.venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1
```

打开 `http://127.0.0.1:8765/preview/`。终端需要保持运行，Ctrl-C停止服务。端口被其他应用使用时，选择空闲端口：

```bash
.venv/bin/python scripts/run_web.py --port 8898 --trade-data-root .local/trade-data-bundle-1
```

对应地址为 `http://127.0.0.1:8898/preview/`。不要为了本项目关闭其他应用。服务默认只允许本机访问，不应直接改成公网监听。

## 配置模型

在聊天页面打开“模型设置”：

1. 选择取得密钥的平台。型号必须是这个平台实际支持的名称，不能将聊天界面的显示名随意填进API。
2. 选择预设型号，或输入自定义型号。推理选项以当前服务商支持的配置为准。
3. 填入自己的API Key并保存。密钥由本地服务保存，不发布到展示网站；同平台换型号可以保留密钥，换平台需新密钥。
4. 可选“测试连接”：它发送短请求，服务商可能收费。成功表示该请求得到响应，不等于所有问题都会答好。

保存设置、看案例和读已有报告不发模型请求。助手提交问题会调用所选平台，并向其发送问题和工具查询结果，按服务商规则计费。

## 提问与读报告

先问“最近美国大豆进口有什么变化？”，完成后接着问“出口呢？”。用底部“发送”或Enter提交；Shift+Enter换行。打开回复下方的报告卡片，查看图表和逐月金额，再返回聊天继续追问。

换商品时直接说“改看豆油进口”。含糊的商品或范围需要确认，明确商品不应每次都要求手动选码。选择“数据查询”则由你确认商品、方向和月份，不使用模型，也不要求连接MySQL。

对话和报告可在刷新后恢复。查看案例、打开报告和切换语言不会重新发送请求；页内往返保留未发送草稿，整页刷新不保存草稿。

## 数据与常见问题

- **“最近”到哪一天？** 目前末月是2026年7月，不是实时数据。进口有48个不连续月份，出口为2025年8月至2026年7月。
- **所问月份没有数据怎么办？** 页面提示缺口；需要改查其他月份时请明确提出，不会自动用最新可用月替代。
- **金额等于数量吗？** 不等于。金额可能受数量和价格共同影响；报告不直接推断政策效果。
- **启动失败？** 检查数据目录、清单核验和端口。不要删除原数据或重写清单跳过核验。
- **模型请求失败？** 检查服务地址、型号和密钥；未知结果不会自动重复请求，避免重复费用。
- **要更新数据包吗？** 新版解到新目录，先核验，再调整启动参数；旧版保留，不自动删除。

[macOS安装核验记录](handoff/runs/20260927-FULL-INSTALL-QA.zh-CN.md) · [展示页说明](PUBLIC_SHOWCASE.zh-CN.md)
