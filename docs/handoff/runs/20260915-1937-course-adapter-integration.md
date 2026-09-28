# 2026-09-15 课程适配层接入结构化入口

- 实际执行模型：Luna 最高
- 目标：将已验证的固定工具契约接入现有结构化研究入口；原始课程目录不动。
- API/模型调用：0；Docker：0；MySQL连接/写入：0

## 变更

- `src/tradeintel_ai/course_adapters.py`：作为TradeIntel自己的边界模块。
- `src/tradeintel_ai/web_app.py`：结构化任务在加载模型前校验政策案例自己的产品表、数据版本、月份和HTS8；响应附带`course_adapter.status=validated`。实际数据读取仍走原TradeIntel工作流。
- `docs/handoff/COURSE_ADOPTION_MATRIX.zh-CN.md`：记录重复项和替换规则。

曾出现一次兼容失败：误用了旧的`EvidenceRepository.policy_products`固定表，真实版本根目录的2025政策表路径不同；已改为按当前case的登记产品文件读取。原有问题已由受影响测试覆盖。

## 验收

```text
.venv/bin/python scripts/check_course_adapter_offline.py
course adapter offline checks: 7 passed

.venv/bin/python -m unittest tests/test_g1_repairs.py tests/test_primary_interpretation_flow.py tests/test_research_brief_v2.py
Ran 20 tests — OK

.venv/bin/python -m unittest tests/test_web_app.py tests/test_solar_release.py tests/test_structured_task.py
Ran 14 tests — OK
```

曾运行全量`unittest discover`作为诊断，911项中有历史冻结哈希、未设置PYTHONPATH的导入错误和既有环境失败；其中新增接入导致的版本产品表错误已单独修复并通过上述受影响测试。全量结果不能宣称为全绿，也没有改冻结实验摘要。

## 下一步

用一个固定聊天/报告fixture验证适配结果在页面响应和运行记录中可见，再决定是否借用课程前端交互；不直接覆盖现有web页面。
