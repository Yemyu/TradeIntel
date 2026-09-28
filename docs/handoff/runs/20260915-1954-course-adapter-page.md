# 2026-09-15 课程适配状态页面验证

- 实际执行模型：Luna 最高
- 目标：让结构化研究结果中的适配状态可在现有本地页面看到。
- API/模型调用：0；Docker：0；MySQL连接/写入：0

## 变更

- `web/index.html`：增加安全的`appendCourseAdapter`显示函数，在结构化任务和自然语言确认结果中显示“固定贸易指标查询已通过”、登记HTS8数量和短数据版本。仅显示后端已验证字段，不让浏览器决定政策或SQL。
- `tests/test_course_adapter_offline.py`：增加页面静态存在性检查。

## 验收

```text
.venv/bin/python -m unittest tests/test_course_adapter_offline.py tests/test_g1_repairs.py tests/test_primary_interpretation_flow.py
Ran 18 tests — OK

.venv/bin/python -m unittest tests/test_web_app.py tests/test_solar_release.py tests/test_structured_task.py
Ran 14 tests — OK
```

本阶段没有启动浏览器或真实模型；页面检查是fixture/静态检查，不能替代一次人工浏览器点击验收。

## 下一步

如果继续使用课程页面设计，下一阶段可在本地启动TradeIntel自己的页面做一次浏览器点击验收；不启动课程Docker服务。出现政策版本、证据卡片或页面状态不一致时回Astra审查。
