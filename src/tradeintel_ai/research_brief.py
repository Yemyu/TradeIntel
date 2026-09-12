"""Confirmed, explicit research brief. Not an autonomous or causal analyst.

Calculations never come from generated text. Policy claims remain review drafts.
Existing frozen components are composed, not rewritten.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from .capability_contract import assess_trade_request
from .evidence_v21 import EvidenceRegistryV21
from .policy_evidence_access import expand_context, PolicyRetriever
from .policy_focus import FocusedPolicyModel, presentation_flags
from .policy_retrieval import validate_search_query
from .policy_workflow import load_frozen_corpus, run_generation, safe_diagnostic
from .execution_journal import ExecutionJournal
from .research_comparison import calculate, registered_windows, resolve, render_comparison
from .structured_workflow import execute_request

ROOT = Path(__file__).resolve().parents[2]


def trade_request(months, origin='China', hs6=None):
    return dict(policy_id='us_301_list1_2018', operation='read',
                metric='import_value_consumption_usd', origin=origin,
                granularity='hs6_2017' if hs6 else 'policy_aggregate',
                months=months, hs6=hs6, causal_effect=False)


def descriptive_summary(data):
    """Exact integer totals, endpoint change only; no implied causal estimator."""
    rows = sorted(data['series'], key=lambda row: row['month'])
    complete = all(row['value_usd'] is not None for row in rows)
    first, last = rows[0], rows[-1]
    delta = percent = None
    if len(rows) > 1 and complete:
        delta = last['value_usd'] - first['value_usd']
        if first['value_usd'] != 0:
            percent = str((Decimal(delta) * 100 / Decimal(first['value_usd'])).quantize(Decimal('0.01')))
    return {'series': rows, 'complete': complete,
            'total_usd': sum(row['value_usd'] for row in rows) if complete else None,
            'first_month': first['month'], 'last_month': last['month'],
            'endpoint_change_usd': delta, 'endpoint_change_percent': percent,
            'comparison_kind': 'last_requested_month_vs_first_requested_month',
            'causal_effect_estimated': False}


def summary_with_comparison(data, comparison, repository):
    """Apply an explicit descriptive comparison to an already verified series."""
    summary = descriptive_summary(data)
    trade_scope = {
        'months': list(data.get('requested_months') or [row['month'] for row in data['series']]),
        'granularity': 'hs6_2017' if data.get('hs6') is not None else 'policy_aggregate',
        'hs6': data.get('hs6'),
    }
    windows = (registered_windows(repository)
               if comparison.get('kind') == 'registered' else None)
    contract = resolve(comparison, trade_scope, registered_windows=windows)
    comparison_result = calculate(contract, data['series'])
    summary['comparison_contract'] = contract
    summary['comparison'] = comparison_result
    if contract['kind'] == 'sequence':
        summary.update(endpoint_change_usd=None, endpoint_change_percent=None,
                       comparison_kind='sequence')
    elif contract['kind'] == 'endpoint':
        summary.update(
            first_month=contract['reference_months'][0],
            last_month=contract['current_months'][0],
            endpoint_change_usd=comparison_result['change_usd'],
            endpoint_change_percent=comparison_result['change_percent'],
            comparison_kind='explicit_endpoint')
    else:
        summary.update(endpoint_change_usd=None, endpoint_change_percent=None,
                       comparison_kind='registered_window',
                       reference_months=contract['reference_months'],
                       current_months=contract['current_months'])
    return summary


class ResearchBrief:
    def __init__(self, registry=None, corpus=None):
        self.registry = registry or EvidenceRegistryV21()
        self.corpus = corpus if corpus is not None else load_frozen_corpus(ROOT)
        self._pending = None

    def prepare(self, request):
        self._pending = None
        required = {'policy_question', 'policy_as_of', 'trade'}
        allowed = (required, required | {'comparison'},
                   required | {'policy_search_query'},
                   required | {'comparison', 'policy_search_query'})
        if not isinstance(request, dict) or set(request) not in allowed:
            raise ValueError('必须明确提供政策问题、政策资料截止日和贸易请求')
        question = request['policy_question']
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise ValueError('政策问题不能为空或过长')
        cutoff = request['policy_as_of']
        if not isinstance(cutoff, str) or date.fromisoformat(cutoff).isoformat() != cutoff:
            raise ValueError('政策资料截止日须为YYYY-MM-DD')
        if 'policy_search_query' in request:
            validate_search_query(request['policy_search_query'])
        assessment = assess_trade_request(request['trade'], self.registry.repository)
        # Never silently execute an in-coverage subset.
        if assessment['status'] != 'within_declared_capability':
            return {'status': 'needs_clarification', 'assessment': assessment, 'model_calls': 0}
        if 'comparison' in request:
            try:
                windows = (registered_windows(self.registry.repository)
                           if request['comparison'].get('kind') == 'registered' else None)
                resolve(request['comparison'], request['trade'],
                        registered_windows=windows)
            except Exception as exc:
                return {'status': 'needs_clarification',
                        'reason': str(exc), 'model_calls': 0}
        snapshot = deepcopy(request)
        token = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self._pending = (token, snapshot)
        candidates = PolicyRetriever(self.corpus).search(
            question, top_k=3, as_of=cutoff,
            search_query=request.get('policy_search_query'))
        return {'status': 'needs_confirmation', 'confirmation_token': token,
                'request': deepcopy(snapshot), 'model_calls': 0,
                'policy_candidate_count': len(candidates['hits']),
                'scope_note': '美国进口；List 1暴露范围；金额使用项目历史数据。资料截止日仅限制政策文档，不表示贸易数据的历史实时版本。',
                'intent_verified': False}

    def confirm(self, token, output, *, model=None, source_kind='live', secret='', audit_context=None,
                entry_kind='explicit_options'):
        if entry_kind not in ('explicit_options', 'natural_language_plan'):
            raise ValueError('unknown research entry kind')
        if self._pending is None or token != self._pending[0]:
            return {'status': 'confirmation_rejected', 'model_calls': 0}
        _, request = self._pending
        self._pending = None  # consumed even on failure: never automatic retries
        if source_kind not in ('live', 'fixture'):
            raise ValueError('此入口不允许把归档回答用于新的问题或提示')
        output = Path(output)
        output.mkdir(parents=True, exist_ok=False)
        journal = ExecutionJournal(output / 'execution-audit.jsonl', secret=secret)
        journal.append('confirmed', status='accepted', detail=audit_context or {})
        def save(name, value):
            text = json.dumps(value, ensure_ascii=False, indent=2)
            if secret:
                text = text.replace(secret, '[REDACTED]')
            (output / name).write_text(text + '\n')
        save('request.json', request)
        journal.append('trade_started', detail={'tool': 'structured_workflow'})
        try:
            trade = execute_request({'task': 'trade', 'request': request['trade']}, self.registry)
        except Exception as exc:
            trade = {'status': 'execution_failed', 'response': '贸易工具异常，已停止发布金额。',
                     'tool_results': [], 'facts': [], 'sources': [],
                     'diagnostic': safe_diagnostic(exc)}
        journal.append('trade_finished', status=trade.get('status'),
                       detail={'diagnostic': trade.get('diagnostic')} if trade.get('diagnostic') else {})
        result = {'version': 'research-brief-1', 'request': request, 'trade': trade,
                  'entry_kind': entry_kind,
                  'intent_verified': False, 'semantic_verified': False,
                  'model_training': False, 'new_api_calls': 0,
                  'task_results': {'trade': trade.get('status')}}
        trade_ready = trade['status'] == 'evidence_ready'
        if trade_ready:
            data = next(r['data'] for r in trade['tool_results'] if r['tool_name'] == 'get_trade_series')
            readiness = next(r['data'] for r in trade['tool_results'] if r['tool_name'] == 'get_causal_readiness')
            result['summary'] = (summary_with_comparison(
                data, request['comparison'], self.registry.repository)
                if 'comparison' in request else descriptive_summary(data))
            result['causal_readiness'] = readiness
        # Policy retrieval is independent of the trade tool. A trade failure
        # must not erase a separately reviewable policy result.
        save('trade-result.json', result)
        result['policy_evidence'] = {'hits': []}
        journal.append('policy_started', detail={'model_requested': model is not None})
        try:
            retrieval = PolicyRetriever(self.corpus).search(
                request['policy_question'], top_k=3, as_of=request['policy_as_of'],
                search_query=request.get('policy_search_query'))
            evidence = expand_context(retrieval, self.corpus)
            result['policy_evidence'] = evidence
        except Exception as exc:
            result['policy'] = {'generation': {'status': 'retrieval_failed', 'claims': []},
                                'audit': {'source_kind': 'no_model', 'new_api_calls': 0,
                                          'diagnostic': safe_diagnostic(exc)}}
        else:
            if model is None:
                result['policy'] = {'generation': {'status': 'not_requested' if evidence['hits'] else 'no_evidence', 'claims': []},
                                    'audit': {'source_kind': 'no_model', 'new_api_calls': 0}}
            else:
                result['policy'] = run_generation(FocusedPolicyModel(model), evidence,
                    output / 'policy-attempt', source_kind=source_kind, secret=secret)
        result['new_api_calls'] = result['policy']['audit']['new_api_calls']
        journal.append('policy_finished', status=result['policy']['generation'].get('status'),
                       detail={'model_calls': result['policy']['audit'].get('model_calls', 0),
                               'new_api_calls': result['new_api_calls']})
        result['presentation_review'] = presentation_flags(
            request['policy_question'], result['policy']['generation'])
        result['task_results']['policy'] = result['policy']['generation'].get('status')
        if trade_ready:
            result['status'] = 'research_draft' if result['summary']['complete'] else 'incomplete_trade_data'
            if result['task_results']['policy'] not in {'not_requested', 'draft_requires_semantic_review'}:
                result['status'] = 'partial'
        else:
            result['status'] = 'partial'
        journal.append('execution_completed', status=result['status'], detail={
            'trade_status': result['task_results'].get('trade'),
            'policy_status': result['task_results'].get('policy'),
        })
        save('result.json', result)
        # Render exactly the redacted persisted artifact, not unredacted model text.
        result = json.loads((output / 'result.json').read_text())
        (output / 'report.zh-CN.md').write_text(render_brief(result))
        return result


def render_brief(result):
    def safe(text):
        # Treat user/model/source strings as text, never executable Markdown/HTML.
        return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('[', '\\[').replace(']', '\\]').replace('|', '\\|')
    def money(value):
        return '缺失，不能补零' if value is None else f'{value:,}'
    request = result['request']
    lines = ['# TradeShock：贸易与政策研究简报', '',
             '> 实验性研究草稿，不是因果结论，也不是自动审定的政策意见。', '',
             '## 1. 这份报告回答什么', '', safe(request['policy_question']), '',
             f"政策资料截止：{request['policy_as_of']}。该日期只筛选政策文件，不限制下面历史贸易观察期。",
             f"贸易范围：美国进口 / List 1暴露范围 / {safe({'China': '中国', 'other_origins': '其他原产地整体（不含中国）', 'all_origins': '全部原产地'}[request['trade']['origin']])} / "
             f"{safe(request['trade']['hs6'] or '政策整体')}；消费进口额，美元。", '',
             ('范围由模型根据自然语言提出，经确认后执行；确认不等于语义正确，仍需逐项核对原话与证据。'
              if result.get('entry_kind') == 'natural_language_plan' else
              '范围来自明确选项并经过确认；本入口没有让大模型自动理解整项研究意图。'
              if result.get('entry_kind') == 'explicit_options' else
              '这份记录未标记入口来源，请结合原始请求与运行记录核对；不能据此判断是否使用自然语言规划。'), '']
    if result['trade'].get('status') != 'evidence_ready':
        lines += ['## 2. 贸易任务', '', '贸易证据执行失败，没有发布金额。', safe(result['trade'].get('response', '')),'',
                  '## 3. 政策任务', '']
        policy = result.get('policy', {})
        lines += [f"生成状态：{policy.get('generation', {}).get('status', 'unknown')}；"
                  f"回答来源：{policy.get('audit', {}).get('source_kind', 'unknown')}。", '',
                  '政策任务独立保存；引用仍需人工审查。', '']
        for claim in policy.get('generation', {}).get('claims', []):
            lines += [safe(claim['text']), '', '引用：' + ', '.join(safe(c) for c in claim['citations']), '']
        return '\n'.join(lines)
    summary = result['summary']
    lines += ['## 2. 贸易数据告诉我们什么（程序计算）', '', '| 请求月份 | 进口额（美元） |', '|---|---:|']
    lines += [f"| {r['month']} | {money(r['value_usd'])} |" for r in summary['series']]
    lines += ['', f"所列月份合计：{money(summary['total_usd'])} 美元。"]
    comparison = summary.get('comparison')
    if comparison:
        lines += render_comparison(summary)
    elif summary['endpoint_change_usd'] is not None:
        rate = summary['endpoint_change_percent']
        lines += [f"{summary['last_month']} 相对 {summary['first_month']} 的金额变化："
                  f"{money(summary['endpoint_change_usd'])} 美元；变化率：{rate + '%' if rate is not None else '首月为零，不能计算'}。"]
    lines += [('这是明确登记或指定窗口的描述性比较，不是全年变化、政策前后平均效应或因果估计；'
               '登记窗口也不等于因果识别。' if comparison else
               '这是首末所选月份的描述性比较，不是全年变化、政策前后平均效应或因果估计；中间月份可不连续。'), '',
              '## 3. 政策文件怎样解释（AI 草稿与证据分开）', '']
    policy = result['policy']
    query_note = result['request'].get('policy_search_query')
    if query_note:
        lines += ['检索桥接表达（只用于寻找候选原文，不替代原问题）：'
                  + safe(query_note), '']
    lines += [f"生成状态：{policy['generation']['status']}；回答来源：{policy['audit']['source_kind']}；本次新 API 调用：{result['new_api_calls']}。",
              '引用编号有效只代表来源存在；文字是否被原文支持，仍需审查。', '']
    hits = {h['id']: h for h in result['policy_evidence']['hits']}
    for claim in policy['generation'].get('claims', []):
        lines += [safe(claim['text']), '', '引用：' + ', '.join(safe(c) for c in claim['citations']), '']
    if not policy['generation'].get('claims'):
        lines += ['本次没有可展示的 AI 政策主张。下面是检索到的候选原文，不把片段自动当成答案。', '']
    for flag in result['presentation_review']['flags']:
        lines += [f"审查提醒（第{flag['claim']}条）：{safe(flag['note'])}"]
    lines += ['', '## 4. 不能从这里得出的结论', '',
              f"当前研究设计状态：{safe(result['causal_readiness']['status'])}。",
              '本报告没有估计因果效应。政策文件说明规则，贸易表显示观察结果；把两者放在一起，不等于证明关税造成了这些变化。',
              '政策资料库仅含两份公告的已索引正文，不覆盖完整附件、后续全部修订或现行税率；政策整体暴露口径不等同于逐笔应税交易。', '',
              '## 5. 可核查来源', '', '贸易工具的来源及校验指纹（完整记录见同目录 result.json）：', '']
    seen = set()
    for tool in result['trade']['tool_results']:
        for source in tool.get('evidence', {}).get('sources', []):
            key = json.dumps(source, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                label = source.get('path') or source.get('file_name') or source.get('kind', '来源')
                lines += [f"- {safe(label)}；SHA256：{safe(source.get('sha256', '未提供'))}"]
                if source.get('url'):
                    lines += [f"  来源网址：{safe(source['url'])}"]
    lines += ['', '政策候选原文（窗口扩展未改变原检索排名）：', '']
    for hit in hits.values():
        lines += [f"### {safe(hit['id'])}", '',
                  f"出版日期：{hit['published']}；第{hit['page']}页；原文字符 {hit['start']}–{hit['end']}。",
                  f"来源：{hit['citation_url']}", f"SHA256：{hit['sha256']}", '',
                  *['> ' + safe(line) for line in hit['text'].splitlines()], '']
    lines += ['## 6. 这次 AI 做了什么', '',
              '采用 BM25 词法检索、同页上下文扩展、受证据约束的生成及引用结构检查。金额和变化率不交给模型编写；没有训练或微调模型，也不声称已经实现自主多智能体。',
              '报告及原始响应可供人工审查；没有自动改写模型主张或给出语义准确率。', '']
    return '\n'.join(lines)
