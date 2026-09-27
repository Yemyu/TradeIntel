"""Version-specific source facts, separate from unapproved model prose."""
import hashlib
import re
from .policy_time_hints import annotate_clock_times
from .policy_facts_contract import SCHEMA, validate_policy_facts

SOURCE_HASH = '578aa44e3c369edf56617a67ff339db1b45e0890f46f088176c085a66355d654'
TEXT_HASHES = {'fr202421217:rate':'15280e869aa0b1d4e7cb7275e32f46abfbe6b95edb108b9649d51439c6fc5c90',
               'fr202421217:scope_and_effective':'fec6713a47f54298a02bac719bc2386c61080ff0f7b3326fa807032ba2432bf6'}


def build_fact_sheet(evidence, version, *, root=None):
    if evidence.get('policy_id') != 'us_301_solar2024' or not version:
        raise ValueError('fact sheet requires solar release')
    refs = {h['id']:h for h in evidence['hits']}
    if len(refs) != len(evidence['hits']): raise ValueError('duplicate fact source')
    scope = refs['fr202421217:scope_and_effective']
    rate = refs['fr202421217:rate']
    for hit in (scope,rate):
        if hit.get('sha256') != SOURCE_HASH: raise ValueError('unreviewed source version')
        if hashlib.sha256(hit['text'].encode()).hexdigest() != TEXT_HASHES[hit['id']]:
            raise ValueError('unreviewed source text')
    # This is a reviewed, single-announcement extractor, not open-world law parsing.
    scope_text = ' '.join(scope['text'].split())
    rate_text = ' '.join(rate['text'].split())
    required = ('products of China', 'entered for consumption, or withdrawn from warehouse for consumption',
                '12:01 a.m. eastern daylight time on September 27, 2024',
                '(1) 8541.42.00', '(2) 8541.43.00')
    if any(s not in scope_text for s in required): raise ValueError('unreviewed effective clause')
    if 'The duty provided' not in rate_text or 'subheading + 50%.' not in rate_text:
        raise ValueError('unreviewed duty clause')
    hints = annotate_clock_times([scope])[0].get('derived_clock_hints',[])
    if len(hints)!=1 or hints[0]['clock_24h']!='00:01': raise ValueError('ambiguous source clock')
    from .policy_product_details import enrich
    return validate_policy_facts(enrich({'schema_version':SCHEMA, 'policy_view':'archived_event',
            'policy_id':evidence['policy_id'], 'data_version':version,
            'producer':'host_reviewed_announcement_mapping_v1', 'model_generated':False,
            'legal_approval':False, 'effective_date':'2024-09-27','clock_24h':hints[0]['clock_24h'],
            'timezone':'美国东部夏令时间（EDT）', 'origin':'中国原产',
            'entry_events':['消费入境','从仓库提取消费'], 'additional_duty_percent':50,
            'scope_source_id':scope['id'], 'origin_source_id':scope['id'],
            'product_rates':[{'hts8':code, 'additional_duty_percent':50,
                              'source_id':rate['id'], 'origin_source_id':scope['id']}
                             for code in ('85414200','85414300')],
            'sources':[{'id':h['id'],'url':h['citation_url'],'text':h['text'],
                        'document_sha256':h['sha256'],
                        'text_sha256':hashlib.sha256(h['text'].encode()).hexdigest()} for h in (scope,rate)],
            'limitations':['仅此存档公告，不是现行综合税率。','章98例外、其他适用税费及逐笔适用条件须查完整原文。']}, root))


def render_fact_sheet(sheet):
    rate_lines=([f"- {r['hts8']}：额外加征{r['additional_duty_percent']}%，不代表综合税率。" for r in sheet['product_rates']]
                if 'product_rates' in sheet else [f"- 额外税率：在适用子目税率之外加征{sheet['additional_duty_percent']}%；不代表综合税率。"])
    lines=['## 政策事实卡（程序据已核查原文生成，不是AI回答）','',
           '数据版本：'+sheet['data_version'], '',
           '- 存档生效起点：'+sheet['effective_date']+' '+sheet['clock_24h']+' '+sheet['timezone'],
           '- 原产范围：'+sheet['origin'],
           '- 适用事件：'+'或'.join(sheet['entry_events']),
           *rate_lines, '',
           *('- '+s for s in sheet['limitations']), '',
           '这张事实卡不代表AI解释通过；AI失败时仍只是一份来源资料，不是完整简报。','']
    for row in sheet.get('product_rates', []):
        detail = row.get('details')
        if detail:
            lines += [f"### {row['hts8']} 登记资料", '',
                      '- 登记名称：' + (detail['registered_name_zh'] or detail['registered_name']),
                      '- 名称为登记资料，不是法律适用结论。',
                      '- 适用条件：未知。' + detail['conditions']['reason'],
                      '- 例外：未知。' + detail['exceptions']['reason'], '']
    if sheet.get('requested_products'):
        lines += ['本次分析商品：' + '、'.join(sheet['requested_products']),
                  '以下引用保留共享原文上下文；其中其他税号不属于本次分析商品。', '']
    for source in sheet['sources']:
        lines += [f"[{source['id']}]({source['url']})",'',
                  *('> '+line for line in source['text'].splitlines()),'']
    return lines


def inspect_clock_conflicts(claims, sheet):
    conflicts=[]
    for index,claim in enumerate(claims):
        text=claim['text']
        ambiguous=bool(re.search(r'上午\s*(?:12|十二)\s*(?:[:：点时])',text))
        clocks=re.findall(r'(?<!\d)(\d{1,2}:[0-5]\d)(?!\d)',text)
        if ambiguous or any(c.zfill(5)!=sheet['clock_24h'] for c in clocks):
            conflicts.append({'claim_index':index,'original_text':text,
                              'reason':'ambiguous_or_conflicting_clock','expected_clock':sheet['clock_24h']})
    return {'status':'blocked' if conflicts else 'manual_review_required',
            'semantic_approval':False,'conflicts':conflicts,
            'limitation':'只检查显式数字时刻及已知歧义；不证明其他日期、税率或中文解释正确。'}
