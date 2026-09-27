"""Synthetic legacy review artifacts; no private run, credentials or data files."""
import json


def write_review_fixture(root):
    root.mkdir(parents=True, exist_ok=True)
    version = 'a' * 64
    source = 'synthetic:scope_and_effective'
    files = {
        'status.json': {'status':'interpretation_needs_review', 'data_version':version},
        'trade-evidence.json': {'data_version':version, 'data':{
            'start':'2026-07','end':'2026-07','measure':'import_value_consumption_usd',
            'origin':'China','series':[{'month':'2026-07','product_breakdown':[
                {'hts8':'85414200','all_origins_value_usd':1200,'china_value_usd':300}]}]}},
        'policy-facts.json': {'data_version':version, 'effective_date':'2025-01-01',
            'origin':'合成原产地','entry_events':['合成适用事件'],'additional_duty_percent':25,
            'sources':[{'id':source,'url':'https://example.test/synthetic-policy','document_sha256':'b'*64}]},
        'interpretation-response.json': {'text':json.dumps({'notes':[
            {'kind':'investigation','text':'第三国转运或轻微加工（合成待拒绝建议）','fact_ids':['trade.available']},
            {'kind':'limitation','text':'现有数据为海关统计金额，不能直接作为企业实际税款。（合成测试）','fact_ids':['trade.available']}
        ]}, ensure_ascii=False)},
    }
    for name, value in files.items():
        (root/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    (root/'source-packet.zh-CN.md').write_text('合成测试资料，不是实际政策或模型结果。',encoding='utf-8')
