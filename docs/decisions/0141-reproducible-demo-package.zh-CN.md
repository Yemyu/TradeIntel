# 0141：0140真实结果的可复现展示包

本阶段不再调用模型、不修改0138/0139/0140运行结果。新增一个只读打包脚本，从已完成且两题均accepted的0140账本中选择报告、事实审核摘要、组合贸易基准、范围比较、配对契约和控制摘要，生成`docs/experiments/phase-0140-live/reproducible-package/`。

脚本会先检查账本确实是`completed`且所有问题是`accepted`，输出已存在则拒绝覆盖。包内不放API密钥、provider配置、完整冻结快照、原始HTTP捕获或宿主审核包；这些材料仍留在本地`tmp/live-development-0140-policy`供完整审计。包里的`MANIFEST.json`保存每个文件的SHA-256和排除项，`run-summary.json`明确这不是盲测准确率、因果估计或训练结果。

验收：脚本拒绝未完成/已有输出的反例；使用0140完整运行生成包，核对清单、摘要和文档链接。此包适合GitHub展示和用户阅读，不替代完整运行目录，不上传密钥或大数据。

完成结果：包已生成，共14个文件；`MANIFEST.json` SHA-256为`4ada811f30ecd24924544c5f7517dd080442c1ab5e9cdff78b5de2c889244786`。2项反例测试通过。包摘要仍明确`semantic_accuracy_measured=false`、`causal_effect_estimated=false`和`training_or_fine_tuning=false`；这三个边界不能为了展示而省略。
