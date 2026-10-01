# TradeShock 本地试用说明

这是一份尚未公开发布的本机试用候选。请将**源码包**和**贸易数据 ZIP**放在同一台 macOS 电脑上；两者是分开的文件。当前验证环境为 macOS、Python 3.13；Windows 和公网部署未验收。普通数据报告不需要 MySQL 或模型 API 密钥。**现有 `tradeintel-local-reviewer-source-20260929-v1.zip` 是后来新增贸易 Agent 之前封装的数据报告版，不含 `trade_agent.py` 等新模块，不能用它验收当前研究助手。**

1. 解压源码包，进入解压后的项目目录。创建项目虚拟环境：

   ```bash
   python3 -m venv .venv
   ```

2. 在源码目录内新建 `.local`，把另外提供的贸易数据 ZIP 解到一个**尚不存在**的子目录。不要覆盖已有数据目录：

   ```bash
   mkdir -p .local
   unzip "/绝对路径/trade-demo-data-20260927-isolated-v2.zip" -d .local/trade-data-1
   ```

3. 核验数据文件，必须看到 `"status": "verified"` 才继续：

   ```bash
   PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-1
   ```

4. 启动只监听本机的页面：

   ```bash
   .venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-1
   ```

   浏览器打开 `http://127.0.0.1:8765/preview/`。若使用当前仓库代码而非旧源码 ZIP，先在“查询方式”选择“仅查询数据（不使用模型）”；未配置模型的首次访问会自动选择它。试问“最近美国大豆进口有什么变化？”，确认商品候选后再生成报告；也可试玉米出口或大豆进口与出口。看完按终端 `Ctrl-C` 停止服务。页面会保留本机报告记录，重启服务后可读回。

数据截至本项目已发布的 2026 年 7 月，不是实时新闻或自动更新的政策库；金额变化不等于政策因果。模型解释是另行点击的试用入口，可能收费且仍需人工核查，本次普通数据报告无需配置它。商品找不到时系统应要求重新明确范围，而不是替换成不相关商品。

此候选只供约定的本地复验；源码及数据的公开发布范围尚未定，不要把 `.local/`、报告记录或个人密钥一起发给他人。数据包 SHA-256：`1ec80a664972fe8e1d3da212d975aa760bd62319b87ff00caaa0cb8ed90433e6`。
