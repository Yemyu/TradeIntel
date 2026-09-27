"""Content-bound local reviewer decisions; never changes case publication."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from .host_review import _publish, _read
from .response_contract import parse_json_response

FILES=('status.json','trade-evidence.json','policy-facts.json','interpretation-response.json','source-packet.zh-CN.md')
V2_FILES=FILES+('evidence-bundle.json', 'interpretation-canonical.json')
SESSION_REVIEW_PROTOCOL = 'session-explanation-review-v1'
PUBLIC_SESSION_REVIEW_PROTOCOL = 'public-brief-explanation-review-v1'
LEGACY_REVIEW_PROTOCOL = 'legacy-interpretation'
V2_REVIEW_PROTOCOL = 'research-brief-v2'


def validate_session_review(payload, expected_items, *, reviewer):
    """Validate the session explanation review contract.

    The session flow stores its content-bound history in ``session_store``;
    this shared validator keeps its field semantics alongside the legacy and
    v2 file-backed review protocols without pretending those old packets are
    the new session packet.
    """
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer.strip()) > 80:
        raise ValueError('reviewer is required')
    if not isinstance(payload, dict) or type(payload.get('facts_checked')) is not bool:
        raise ValueError('facts_checked must be boolean')
    decisions = payload.get('decisions')
    if not isinstance(decisions, list) or len(decisions) != len(expected_items):
        raise ValueError('必须逐项审阅每个解释和追问')
    clean = []
    for item, decision in zip(expected_items, decisions):
        if not isinstance(decision, dict) or set(decision) != {'index', 'kind', 'verdict', 'reason'}:
            raise ValueError('审阅项字段无效')
        if (decision['index'] != item['index'] or decision['kind'] != item['kind']
                or decision['verdict'] not in {'accept', 'reject', 'needs_revision'}
                or not isinstance(decision['reason'], str)
                or not 1 <= len(decision['reason'].strip()) <= 1000):
            raise ValueError('审阅项顺序、结论或理由无效')
        clean.append(deepcopy(decision))
    eligible = bool(payload['facts_checked'] and clean
                    and any(d['kind'] == 'finding' and d['verdict'] == 'accept' for d in clean)
                    and all(d['verdict'] != 'needs_revision' for d in clean))
    return {
        'protocol': SESSION_REVIEW_PROTOCOL,
        'schema_version': SESSION_REVIEW_PROTOCOL,
        'reviewer': reviewer.strip(),
        'facts_checked': payload['facts_checked'],
        'decisions': clean,
        'eligible_for_export': eligible,
        'created_at': payload.get('created_at'),
        'status': 'accepted' if eligible else 'rejected_or_incomplete',
    }


def validate_public_session_review(payload, expected_items, *, reviewer):
    """Validate item decisions for the multi-period public explanation.

    This is deliberately a separate protocol from the legacy A3 explanation
    review: the new contract reviews interpretation/watch entries keyed by
    observation IDs, not ``finding``/``followup`` slots.
    """
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer.strip()) > 80:
        raise ValueError('reviewer is required')
    if not isinstance(payload, dict) or type(payload.get('facts_checked')) is not bool:
        raise ValueError('facts_checked must be boolean')
    decisions = payload.get('decisions')
    if not isinstance(decisions, list) or len(decisions) != len(expected_items):
        raise ValueError('必须逐项审阅每个解释和观察事项')
    clean = []
    for item, decision in zip(expected_items, decisions):
        if not isinstance(decision, dict) or set(decision) != {'index', 'kind', 'verdict', 'reason'}:
            raise ValueError('审阅项字段无效')
        if (decision['index'] != item['index'] or decision['kind'] != item['kind']
                or decision['verdict'] not in {'accept', 'reject', 'needs_revision'}
                or not isinstance(decision['reason'], str)
                or not 1 <= len(decision['reason'].strip()) <= 1000):
            raise ValueError('审阅项顺序、结论或理由无效')
        clean.append(deepcopy(decision))
    has_policy = any(item.get('kind') == 'policy_explanation' for item in expected_items)
    eligible = bool(payload['facts_checked']
                    and any(d['kind'] == 'interpretation' and d['verdict'] == 'accept'
                            for d in clean)
                    and (not has_policy or all(
                        d['verdict'] == 'accept'
                        for d in clean if d['kind'] == 'policy_explanation'))
                    and all(d['verdict'] != 'needs_revision' for d in clean))
    return {
        'protocol': PUBLIC_SESSION_REVIEW_PROTOCOL,
        'schema_version': PUBLIC_SESSION_REVIEW_PROTOCOL,
        'reviewer': reviewer.strip(),
        'facts_checked': payload['facts_checked'],
        'decisions': clean,
        'eligible_for_export': eligible,
        'created_at': payload.get('created_at'),
        'status': 'accepted' if eligible else 'rejected_or_incomplete',
    }


def validate_review_payload(protocol, payload, expected_items=None, *, reviewer=None):
    """Dispatch validation by protocol without changing old packet semantics.

    The filesystem-backed legacy and v2 reviewers still require their bound
    ``packet`` and :func:`submit` flow.  The session explanation is the only
    protocol validated from an in-memory task payload; making that distinction
    explicit prevents callers from silently treating one schema as another.
    """
    if protocol == SESSION_REVIEW_PROTOCOL:
        if expected_items is None or reviewer is None:
            raise ValueError('session review requires expected items and reviewer')
        return validate_session_review(payload, expected_items, reviewer=reviewer)
    if protocol == PUBLIC_SESSION_REVIEW_PROTOCOL:
        if expected_items is None or reviewer is None:
            raise ValueError('public session review requires expected items and reviewer')
        return validate_public_session_review(payload, expected_items, reviewer=reviewer)
    if protocol in {LEGACY_REVIEW_PROTOCOL, V2_REVIEW_PROTOCOL}:
        raise ValueError('filesystem review packets must use packet()/submit()')
    raise ValueError('unsupported review protocol')


def _review_digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _review_history(run):
    first = run/'human-interpretation-review.json'
    revisions = sorted(run.glob('human-interpretation-review.*.json'))
    if not first.exists():
        if revisions:
            raise ValueError('review history missing original')
        return []
    history = [_read(first)]
    for number, path in enumerate(revisions, start=2):
        if path.name != f'human-interpretation-review.{number:06d}.json':
            raise ValueError('review history sequence invalid')
        record = _read(path)
        if (record.get('revision') != number
                or record.get('base_review_digest') != _review_digest(history[-1])
                or record.get('fingerprint') != history[-1].get('fingerprint')):
            raise ValueError('review history binding invalid')
        history.append(record)
    return history


def _packet_snapshot(run):
    hashes={}
    contents={}
    file_names = V2_FILES if (run/'evidence-bundle.json').is_file() else FILES
    if 'evidence-bundle.json' in file_names and (run/'input.json').exists():
        file_names = (*file_names, 'input.json')
    for name in file_names:
        path=run/name
        if path.is_symlink() or not path.is_file(): raise ValueError('review source missing or unsafe')
        contents[name]=path.read_bytes()
        hashes[name]=hashlib.sha256(contents[name]).hexdigest()
    status=json.loads(contents['status.json'])
    trade=json.loads(contents['trade-evidence.json'])
    facts=json.loads(contents['policy-facts.json'])
    if status.get('status')!='interpretation_needs_review' or not status.get('data_version'):
        raise ValueError('not a reviewable interpretation run')
    if any(obj.get('data_version')!=status['data_version'] for obj in (trade,facts)):
        raise ValueError('review version mismatch')
    response_payload=json.loads(contents['interpretation-response.json'])
    parsed=parse_json_response(response_payload['text'])
    if 'interpretation-canonical.json' in file_names:
        canonical=json.loads(contents['interpretation-canonical.json'])
        expected_hash=hashlib.sha256(response_payload['text'].encode('utf-8')).hexdigest()
        if canonical.get('raw_sha256') != expected_hash or canonical.get('parsed') != parsed:
            raise ValueError('canonical response does not match raw response')
    if 'evidence-bundle.json' in file_names:
        if parsed.get('schema_version') != 'research-brief-v2':
            raise ValueError('v2 response contract mismatch')
        from .evidence_bundle import build_evidence_bundle
        from .research_brief_v2 import review
        bundle = json.loads(contents['evidence-bundle.json'])
        expected = build_evidence_bundle(trade, facts, focus=bundle['request']['focus'])
        if bundle != expected:
            raise ValueError('evidence bundle does not match bound trade and policy facts')
        if status.get('policy_id', bundle['policy_id']) != bundle['policy_id']:
            raise ValueError('run policy does not match evidence bundle')
        if 'input.json' in contents:
            request = json.loads(contents['input.json']).get('structured_task')
            if not isinstance(request,dict) or any([
                request.get('policy_id') != bundle['policy_id'],
                request.get('month') != bundle['request']['month'],
                request.get('product') != bundle['request']['product'],
                request.get('focus','contrast') != bundle['request']['focus'],
            ]):
                raise ValueError('saved request does not match evidence bundle')
        model_review = review(parsed, bundle)
        notes=parsed.get('findings', [])
    else:
        notes=parsed['notes']
    # Identical answers from separate runs still need separate decisions.
    fingerprint=hashlib.sha256(json.dumps({'run':run.name,'files':hashes},sort_keys=True).encode()).hexdigest()
    result={'fingerprint':fingerprint,'data_version':status['data_version'],'hashes':hashes,
            'notes':notes,'decision':None,'status':'pending','case_publication_allowed':False,
            'contract':'research-brief-v2' if 'evidence-bundle.json' in file_names else 'legacy-interpretation'}
    if 'evidence-bundle.json' in file_names:
        result['evidence_bundle'] = bundle
        result['model_task_coverage'] = model_review['task_coverage']
    history=_review_history(run)
    result.update(history=history, revision=len(history), review_digest=None)
    if history:
        record=history[-1]
        result['decision']=record
        result['review_digest']=_review_digest(record)
        result['status']='recorded' if record['fingerprint']==fingerprint else 'stale'
    if 'evidence-bundle.json' in file_names:
        from .research_brief_v2 import task_coverage
        accepted_notes = []
        if result['status'] == 'recorded':
            accepted_notes = [notes[item['index']] for item in result['decision']['decisions']
                              if item['verdict'] == 'accept']
        result['accepted_task_coverage'] = task_coverage(accepted_notes, bundle)
    return result, trade, facts


def packet(run):
    return _packet_snapshot(run)[0]


def submit(run, payload):
    expected={'fingerprint','reviewer','facts_checked','decisions'}
    if not isinstance(payload,dict) or set(payload) not in (expected, expected|{'base_review_digest','change_reason'}):
        raise ValueError('invalid review fields')
    current=packet(run)
    if payload['fingerprint']!=current['fingerprint']: raise ValueError('review source changed; reload')
    revising='base_review_digest' in payload
    if revising:
        if current['status']!='recorded' or payload['base_review_digest']!=current['review_digest']:
            raise ValueError('审阅记录已变化或过期，请刷新后重试')
        if not isinstance(payload['change_reason'],str) or not 1<=len(payload['change_reason'].strip())<=1000:
            raise ValueError('请填写本次修订原因')
    elif current['decision'] is not None:
        raise ValueError('已有审阅记录，请使用修订入口')
    if not isinstance(payload['reviewer'],str) or not 1<=len(payload['reviewer'].strip())<=80:
        raise ValueError('reviewer label required')
    if type(payload['facts_checked']) is not bool: raise ValueError('facts confirmation must be boolean')
    decisions=payload['decisions']
    if not isinstance(decisions,list) or len(decisions)!=len(current['notes']): raise ValueError('review every note')
    for i,decision in enumerate(decisions):
        if not isinstance(decision,dict) or set(decision)!={'index','verdict','reason'}:
            raise ValueError('invalid note decision')
        if type(decision['index']) is not int or decision['index']!=i or decision['verdict'] not in ('accept','reject','needs_revision'):
            raise ValueError('invalid note verdict')
        if not isinstance(decision['reason'],str) or not 1<=len(decision['reason'].strip())<=1000:
            raise ValueError('reason required for every note')
    ready=payload['facts_checked'] and any(d['verdict']=='accept' for d in decisions) and all(d['verdict']!='needs_revision' for d in decisions)
    revision=current['revision']+1
    record={**payload,'revision':revision,'created_at':datetime.now(timezone.utc).isoformat(),
            'reviewer_identity':'self_declared_local_user_not_authenticated',
            'eligible_for_reviewed_draft':ready,'case_publication_allowed':False,
            'boundary':'仅记录此版回答的人工选择，不证明专业资质，不改变案例发布，不覆盖原模型答案。'}
    # Atomic no-overwrite publish: simultaneous edits of the same base compete
    # for one revision slot. No mutable "latest" pointer or overwritten history.
    filename='human-interpretation-review.json' if revision==1 else f'human-interpretation-review.{revision:06d}.json'
    _publish(run/filename,record)
    return packet(run)


def reviewed_draft(run):
    """Render only accepted notes after a complete, content-bound review.

    This is a local review draft, not a case publication or legal approval.
    It never changes the saved model response or the review decision.
    """
    current, trade, facts=_packet_snapshot(run)
    if (run/'evidence-bundle.json').is_file():
        return _reviewed_v2(run, current, trade, facts)
    decision=current.get('decision')
    if current.get('status')!='recorded' or not isinstance(decision,dict):
        raise ValueError('human review is still pending or stale')
    if decision.get('fingerprint')!=current['fingerprint']:
        raise ValueError('human review fingerprint mismatch')
    if decision.get('facts_checked') is not True or decision.get('eligible_for_reviewed_draft') is not True:
        raise ValueError('review is not eligible for draft export')
    decisions=decision.get('decisions')
    if not isinstance(decisions,list) or len(decisions)!=len(current['notes']):
        raise ValueError('review decision coverage incomplete')
    accepted=[]
    for index,item in enumerate(decisions):
        if not isinstance(item,dict) or item.get('index')!=index:
            raise ValueError('review decision index mismatch')
        if item.get('verdict')=='needs_revision':
            raise ValueError('review still has a revision item')
        if item.get('verdict')=='accept':
            accepted.append((index,current['notes'][index],item))
    if not accepted:
        raise ValueError('no accepted interpretation note')

    # Render exactly the bytes whose hashes were checked against the review.
    # Reopening these files here could mix new data with an older approval.
    data=trade.get('data',{})
    lines=['# 人工审阅稿（待进一步复核）','',
           '> 这不是案例发布批准、法律意见或自动批准的研究结论。仅纳入本次人工明确选择“采纳”的AI建议；原模型回答和未采纳内容保持不变。','',
           '## 运行范围与数据','',
           f"- 数据版本：`{current['data_version']}`",
           f"- 同版本数据页：`/api/version-report?version={current['data_version']}`（只读背景页，不扩大本次AI解释范围）",
           f"- 统计期：{data.get('start','未知')}至{data.get('end','未知')}",
           f"- 统计口径：{data.get('measure','未知')}；原产地筛选：{data.get('origin','未知')}",'',
           '| 月份 | 范围 | 美国全部来源消费进口额（美元） | 中国原产金额（美元） | 中国占该行进口额 |',
           '|---|---|---:|---:|---:|']
    for month in data.get('series',[]):
        # Keep month identity; a single-product response may have no breakdown.
        rows=month.get('product_breakdown') or [{**month,'hts8':data.get('hts8') or '查询范围合计'}]
        for row in rows:
            world=row.get('all_origins_value_usd');china=row.get('china_value_usd')
            if any(value is not None and (type(value) is not int or value<0) for value in (world,china)):
                raise ValueError('invalid reviewed monetary evidence')
            if world is not None and china is not None and china>world:
                raise ValueError('china exceeds total')
            money=lambda value: '未知' if value is None else f'{value:,}'
            share=f'{china/world*100:.2f}%' if world and china is not None else '未知'
            lines.append(f"| {month.get('month','未知')} | {row.get('hts8','未知')} | {money(world)} | {money(china)} | {share} |")
    lines += ['', '金额是美国消费进口统计，不是逐笔关税适用、实际税负、损失或政策因果效果。']
    lines += ['', '## 程序政策事实与来源', '',
              f"- 生效起点：{facts.get('effective_date','未知')} {facts.get('clock_24h','')} {facts.get('timezone','')}",
              f"- 原产范围：{facts.get('origin','未知')}",
              f"- 适用事件：{'或'.join(facts.get('entry_events',[]))}",
              *([f"- {r['hts8']}：额外加征{r['additional_duty_percent']}%，不代表综合税率。" for r in facts['product_rates']]
                if 'product_rates' in facts else [f"- 额外税率：适用子目税率之外加征{facts.get('additional_duty_percent','未知')}%；不代表综合税率。"]), '',
              '政策事实由程序依据已核查公告生成；章98例外、其他适用税费及逐笔适用条件仍需按完整原文核查。']
    source_ids=[]
    for source in facts.get('sources',[]):
        source_ids.append(source.get('id','未知'))
        lines += ['', f"- [{source.get('id','未知')}]({source.get('url','#')})（文档SHA-256：`{source.get('document_sha256','未知')}`）"]
    lines += ['', '## AI建议（仅纳入人工采纳项）', '']
    for index,note,item in accepted:
        lines += [f"### 建议 {index+1}", '', f"关联事实：{', '.join(note.get('fact_ids',[]))}", '', note.get('text',''), '', f"人工审阅理由：{item.get('reason','')}", '']
    rejected=sum(1 for item in decisions if item.get('verdict')=='reject')
    lines += ['## 审阅状态', '',
              f"审阅版本：{current['revision']}；决定指纹：`{current['review_digest']}`",
              f"本次共{len(decisions)}条AI建议，采纳{len(accepted)}条，排除{rejected}条；所有待修改项均已清除。",
              f"审阅者标签：{decision.get('reviewer','未记录')}（本地自报，不代表身份或专业资质认证）",
              f"审阅记录时间：{decision.get('created_at','未知')}",
              'case_publication_allowed=false；本稿只作为人工继续复核的材料。', '',
              '## 可追溯文件指纹', '',
              f"审阅包指纹：`{current['fingerprint']}`"]
    for name,digest in current['hashes'].items():
        lines.append(f"- `{name}`：`{digest}`")
    return '\n'.join(lines)+'\n'


def _reviewed_v2(run, current, trade, facts):
    """Render accepted v2 findings against the immutable evidence bundle."""
    decision=current.get('decision')
    if current.get('status')!='recorded' or not isinstance(decision,dict):
        raise ValueError('human review is still pending or stale')
    if decision.get('facts_checked') is not True or decision.get('eligible_for_reviewed_draft') is not True:
        raise ValueError('review is not eligible for draft export')
    bundle=current['evidence_bundle']
    decisions=decision.get('decisions')
    if not isinstance(decisions,list) or len(decisions)!=len(current['notes']):
        raise ValueError('review decision coverage incomplete')
    accepted=[]
    for index,item in enumerate(decisions):
        if item.get('index') != index or item.get('verdict') == 'needs_revision':
            raise ValueError('review still has a revision item')
        if item.get('verdict') == 'accept':
            accepted.append((index,current['notes'][index],item))
    if not accepted:
        raise ValueError('no accepted interpretation finding')
    lines=['# 人工审阅稿（v2，待进一步复核）','',
           '> 本稿只纳入本次人工选择的 AI 解释；不构成法律意见、税款/损失结论、因果结论或案例发布批准。','']
    from .research_brief_v2 import render_coverage
    lines[2:2] = [render_coverage(current['accepted_task_coverage']), '']
    from .evidence_bundle import render_observations
    lines += render_observations(bundle)
    lines += ['', '| 商品 | 美国全部来源金额（美元） | 中国原产金额（美元） | 中国占该商品进口 |',
              '|---|---:|---:|---:|']
    for p in bundle['profiles']:
        share = '未知（分母为零）' if p['china_share_of_product_percent'] is None else f"{p['china_share_of_product_percent']:.2f}%"
        lines.append(f"| {p['hts8']} | {p['world_import_usd']:,} | {p['china_import_usd']:,} | {share} |")
    lines += ['', '份额分母是美国该商品全部来源消费进口额。', '', '## 政策事实与限制', '']
    if facts.get('effective_date'):
        lines.append(f"生效时点：{facts['effective_date']} {facts.get('clock_24h','')} {facts.get('timezone','')}")
    if facts.get('origin'):
        lines.append('原产范围：' + facts['origin'])
    for rate in facts.get('product_rates', []):
        if rate['hts8'] in {p['hts8'] for p in bundle['profiles']}:
            lines.append(f"- {rate['hts8']}：存档额外税率 {rate.get('additional_duty_percent','未知')}%；依据 {rate.get('source_id','未知')}。")
            detail = rate.get('details')
            if detail:
                lines += ['  登记名称：' + (detail['registered_name_zh'] or detail['registered_name']),
                          '  适用条件未知：' + detail['conditions']['reason'],
                          '  例外未知：' + detail['exceptions']['reason']]
    lines += ['- '+item['text'] for item in bundle['limitations']]
    lines += ['', '## 来源', '']
    for source in bundle['sources']:
        url = source.get('url') or source.get('source_url')
        label = source.get('id') or source.get('path', '来源')
        lines.append(f"- [{label}]({url})" if url else f"- {label}")
        digest = source.get('sha256') or source.get('document_sha256')
        if digest:
            lines.append(f"  SHA-256：`{digest}`")
    lines += ['', '## AI 解释（人工采纳）', '']
    for index,note,item in accepted:
        lines += [f"### 解释 {index+1}", '', f"关联观察：{note.get('observation_id')}", '',
                  note.get('explanation',''), '', f"人工审阅理由：{item.get('reason','')}", '']
    lines += ['## 范围与版本', '', f"- 政策：`{bundle['policy_id']}`", f"- 数据版本：`{bundle['data_version']}`",
              f"- 统计期：{bundle['request']['month']}", '', '## 审阅状态', '',
              f"审阅版本：{current['revision']}；审阅包指纹：`{current['fingerprint']}`",
              'case_publication_allowed=false；本稿仍需继续复核。', '']
    return '\n'.join(lines)+'\n'
