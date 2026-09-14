# 0133：真实入口统一为冻结、执行、审核、继续

## 本次交付

统一入口为 `scripts/run_live_development_0128.py`。默认只检查；`--freeze`保存批次旁边的完整预检JSON；`--execute`要求当前配置和依赖与预检完全一致，真实调用到待审即停；`--pending`读取完整待审材料；`--submit`记录宿主明确判断；`--resume`继续同一waiting_review批次。公共路径强制启用检查点与持久化宿主审核，不使用自动关键词裁判。

预算保持4次规划+2次带证据+2次无证据、累计20000已报告token阈值，无自动重试。实际请求捕获需要消息、模型、温度、生成上限、thinking、stream、端点、超时匹配，不允许额外参数。预检仅验证本地配置与依赖，不测试服务可达性、密钥是否有效或资源包余额。

审核命令无需密钥；用户不需要填写审核表。宿主助手读取完整材料后创建含slot、submission的JSON，再提交。缺失判断不会继续后续模型调用；审核失败仍保留且停止主流程。已有授权有效，不再要求用户重复确认。

## 操作顺序（助手执行）

后续配置改进：已新增 `--configure`，在交互式本地终端隐藏输入一次密钥，保存至项目 `.local/glm.json`（Git忽略，权限0600）。默认沿用最近开发路线的glm-4.7，也可配置时传`--model`。不会覆盖已有配置；不访问网络。后续运行自动读取本地文件，环境变量可显式覆盖。已用临时假密钥验证读取、权限和拒绝覆盖，并确认Git忽略规则。本次没有保存真实密钥。

用户仅需在项目终端执行 `.venv/bin/python scripts/run_live_development_0128.py --configure` 并隐藏输入；随后所有预检、审核、恢复由助手处理。不再要求每次export密钥。

先在项目配置中提供TRADEINTEL_MODEL_BASE_URL、TRADEINTEL_MODEL_NAME、TRADEINTEL_MODEL_API_KEY；本次只检查这些变量是否存在，没有输出密钥。项目当前未找到.env配置，当前进程也未配置这三项。历史0035记录显示密钥仅注入临时进程，没有持久化，这与终端关闭后缺失配置相符。

假设新批次目录为 `/tmp/tradeintel-live-0133`：

```bash
.venv/bin/python scripts/run_live_development_0128.py --output /tmp/tradeintel-live-0133 --freeze
.venv/bin/python scripts/run_live_development_0128.py --output /tmp/tradeintel-live-0133 --execute
.venv/bin/python scripts/run_live_development_0128.py --output /tmp/tradeintel-live-0133 --pending
```

助手读取pending中的完整计划、报告、主张和引文后，生成审核JSON，并执行：

```bash
.venv/bin/python scripts/run_live_development_0128.py --output /tmp/tradeintel-live-0133 --submit /tmp/tradeintel-host-submission.json
.venv/bin/python scripts/run_live_development_0128.py --output /tmp/tradeintel-live-0133 --resume
```

退出码4表示等待审核，0表示命令成功，2表示未就绪或输入无效，3表示运行停止。不得把4理解成完成，也不得对3自动重试。恢复使用同一目录；不能用新批次把失败悄悄抹掉。改动代码/题文/数据/模型配置会使预检失效，需要明确新批次。

## 验证与限制

完整回归686项通过（62.431秒），`git diff --check`通过；0次真实模型请求。

新增模拟HTTP入口测试：冻结不请求网络；更换模型被拒；启动产生1次规划请求并等待plan审查；提交测试专用判断后恢复到answer待审，仍只有1次请求。缺失密钥或URL带查询凭据不能冻结。测试中的审核判断不是实际语义评估。

没有使用聊天中的历史密钥发请求，没有真实GLM成绩。因果识别状态不变。本轮完成的是可运行的审核开发入口，尚不是无人审查产品，也未证明四场景真实模型全部通过。下一阶段Astra中：恢复本地GLM配置后，按冻结四场景开展一次有界批次，由助手逐项审核。
