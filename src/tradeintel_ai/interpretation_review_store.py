"""Content-bound local reviewer decisions; never changes case publication."""
import hashlib
import json
from datetime import datetime, timezone
from .host_review import _publish, _read

FILES=('status.json','trade-evidence.json','policy-facts.json','interpretation-response.json','source-packet.zh-CN.md')


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
    for name in FILES:
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
    notes=json.loads(json.loads(contents['interpretation-response.json'])['text'])['notes']
    # Identical answers from separate runs still need separate decisions.
    fingerprint=hashlib.sha256(json.dumps({'run':run.name,'files':hashes},sort_keys=True).encode()).hexdigest()
    result={'fingerprint':fingerprint,'data_version':status['data_version'],'hashes':hashes,
            'notes':notes,'decision':None,'status':'pending','case_publication_allowed':False}
    history=_review_history(run)
    result.update(history=history, revision=len(history), review_digest=None)
    if history:
        record=history[-1]
        result['decision']=record
        result['review_digest']=_review_digest(record)
        result['status']='recorded' if record['fingerprint']==fingerprint else 'stale'
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
              f"- 额外税率：适用子目税率之外加征{facts.get('additional_duty_percent','未知')}%；不代表综合税率。", '',
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
