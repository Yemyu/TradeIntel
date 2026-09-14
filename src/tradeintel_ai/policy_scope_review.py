"""Conservative omission flags; source visibility is not semantic approval."""
import re


def review_policy_scope(claims, evidence):
    hits = evidence['hits']
    refs = {h['id']: h for h in hits}
    if len(refs) != len(hits):
        raise ValueError('duplicate policy source')
    cited = {ref for claim in claims for ref in claim['citations']}
    origin_sources = [h['id'] for h in hits
                      if re.search(r'products?\s+of\s+China|articles\s+the\s+product\s+of\s+China', h['text'], re.I)]
    text = '\n'.join(c['text'] for c in claims)
    # A mention is only a lexical signal: even a negation may match. Never
    # interpret this as proof the model stated the condition correctly.
    origin_mention = bool(re.search(r'中国原产|原产(?:于|自)中国|中国生产|中国产品|中国产商品', text))
    warnings = []
    if origin_sources and not origin_mention:
        warnings.append('原文含中国原产适用范围，但AI解释未检测到明确原产范围表述，必须补核。')
    general = 'fr202421217:general_conditions'
    required = evidence.get('policy_id') == 'us_301_solar2024'
    if required and general not in refs:
        warnings.append('第二案例缺少一般适用限定原文，本报告证据不完整。')
    elif required and general not in cited:
        warnings.append('AI解释未引用一般适用限定；下方完整展示该段，未引用不代表不适用。')
    return {'status': 'needs_scope_review' if warnings else 'manual_review_required',
            'semantic_approval': False, 'origin_source_ids': origin_sources,
            'origin_mention_detected': origin_mention, 'warnings': warnings,
            'required_general_source': general if required else None,
            'general_source_present': general in refs if required else None,
            'general_source_cited': general in cited if required else None}


def render_scope_review(review, evidence):
    refs = {h['id']:h for h in evidence['hits']}
    lines = ['## 适用范围与遗漏提示（程序检查）', '',
             '以下只是遗漏提示与原文展示，不是AI解释正确或法律适用已获批准。', '']
    lines += ['- ' + message for message in review['warnings']]
    if review['origin_source_ids']:
        lines += ['', '原文中的原产范围不能被贸易表的“中国金额”列代替；请对照以下来源核查：', '']
        for ref in review['origin_source_ids']:
            lines.append(f"- [{ref}]({refs[ref]['citation_url']})")
    general = review['required_general_source']
    if general and review['general_source_present']:
        hit = refs[general]
        lines += ['', '### 一般适用限定原文（无论AI是否引用均展示）', '',
                  f"[{general}]({hit['citation_url']})", '',
                  *('> '+line for line in hit['text'].splitlines()), '']
    return lines
