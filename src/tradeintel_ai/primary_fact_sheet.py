"""Map the registered CBP clauses to product-specific source facts."""
import hashlib
import re
from .policy_facts_contract import SCHEMA, validate_policy_facts

POLICY='us_301_review2025_tungsten_solar'
TEXT_HASHES={'cbp63577329:p8':'ccd14691b208c1c85615674cf95b13b45395998e1ed1e7da736f41a58d40e20e',
             'cbp63577329:p9':'c2482138ad6c4202cf89c4f39fef6785d394e5beee8a0479dc2b1092848b740b',
             'cbp63577329:p12':'02beeb87a0dabb6104b23226637a9cc74e87edaa3fc42b5adb08ec05a1ab148f'}
GROUPS={'cbp63577329:p9':(50,('28046100','38180000')),
        'cbp63577329:p12':(25,('81019400','81019910','81019980'))}


def build_primary_fact_sheet(evidence, version, *, root=None):
    if evidence.get('policy_id')!=POLICY or not version:
        raise ValueError('primary version required')
    refs={h['id']:h for h in evidence['hits']}
    if len(refs)!=len(evidence['hits']):raise ValueError('duplicate source')
    for key,digest in TEXT_HASHES.items():
        if hashlib.sha256(refs[key]['text'].encode()).hexdigest()!=digest:
            raise ValueError('unreviewed primary clause text')
    timing=refs['cbp63577329:p8']
    text=timing['text']
    for required in ('January 1, 2025','12:01 a.m. eastern standard time',
                     'entered for consumption, or withdrawn from warehouse for consumption'):
        if required not in text:raise ValueError('effective clause changed')
    rates=[]
    for source,(rate,codes) in GROUPS.items():
        hit=refs[source]
        if 'products of China' not in hit['text'] or f'additional {rate} percent' not in hit['text']:
            raise ValueError('rate clause changed')
        found={m.replace('.','') for m in re.findall(r'\b\d{4}\.\d{2}\.\d{2}\b',hit['text'])}
        if not set(codes)<=found:raise ValueError('product clause missing')
        rates.extend({'hts8':code,'additional_duty_percent':rate,'source_id':source,
                      # The two clauses each say "products of China"; bind the
                      # origin evidence to the same product group instead of
                      # reusing the silicon paragraph for tungsten.
                      'origin_source_id':source} for code in codes)
    from .policy_product_details import enrich
    return validate_policy_facts(enrich({'schema_version':SCHEMA,'policy_view':'archived_event',
            'policy_id':POLICY,'data_version':version,'model_generated':False,'legal_approval':False,
            'effective_date':'2025-01-01','clock_24h':'00:01','timezone':'美国东部标准时间（EST）',
            'origin':'中国原产','entry_events':['消费入境','从仓库提取消费'],
            'product_rates':rates,'scope_source_id':timing['id'],
            'origin_source_id':'per_product',
            'sources':[{'id':h['id'],'url':h['citation_url'],'text':h['text'],
                        'document_sha256':h['sha256'],'text_sha256':hashlib.sha256(h['text'].encode()).hexdigest()}
                       for h in (timing,refs['cbp63577329:p9'],refs['cbp63577329:p12'])],
            'limitations':['仅存档CBP通知，不是现行综合税率。','税号贸易金额不等于逐笔适用税基；商品限定及其他税费须核对完整原文。']}, root))
