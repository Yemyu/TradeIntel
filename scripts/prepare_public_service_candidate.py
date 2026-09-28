"""Build four offline candidates through the production session handlers.

Creates local QA sessions. Does not call a provider or certify browser QA.
Only requests/*/messages.json belongs in a model's context.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from scripts.prepare_public_brief_candidate import (
    ROOT, POLICY, VERSION, _snapshot, _independent_reference, _write_json,
)
from scripts.prepare_public_eval_diagnostic import estimate_input_tokens
from tradeintel_ai.session_store import load_session
from tradeintel_ai.session_explanation import load_public_snapshot
from tradeintel_ai.web_app import _handle_session_post
from tradeintel_ai.public_eval_protocols import (  # noqa: E402
    QUESTION_PROTOCOLS, UNIFIED_CANDIDATE_SCHEMA, UNIFIED_EXPERIMENT_ID,
)


def build_candidate(output: Path) -> dict:
    store, _, version = _snapshot(ROOT)
    out = Path(output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    for folder in ('requests', 'references', 'host_artifacts'):
        (out / folder).mkdir()
    scenarios_path = ROOT / 'evals/public_brief_v1/scenarios.json'
    scenarios = json.loads(scenarios_path.read_text())['scenarios']
    manifest = {'schema_version': UNIFIED_CANDIDATE_SCHEMA,
                'experiment_id': UNIFIED_EXPERIMENT_ID,
                'question_protocols': QUESTION_PROTOCOLS,
                'status': 'candidate_only_not_frozen', 'api_calls': 0,
                'data_version': version, 'scenarios': {}, 'files_sha256': {}}
    q1_session = None
    q1_request = None
    for item in scenarios:
        sid = item['id']
        trace = []

        def post(path, **body):
            result = _handle_session_post(ROOT, path, body, repository=None)
            trace.append({'route': path, 'status': result.get('status'),
                          'task_id': result.get('task_id')})
            return result

        if sid == 'q2':
            session_id = q1_session
            result = post('/api/session/followup', session_id=session_id,
                          text=item['question'], selected_products=item['selection'])
            if result.get('needs_clarification') or not result.get('proposal'):
                raise ValueError('Q2生产追问没有返回可确认范围')
            proposal = result['proposal']
        else:
            session_id = post('/api/session/create')['session']['session_id']
            proposal = post('/api/session/proposal', session_id=session_id,
                            original_question=item['question'], policy_id=POLICY,
                            selected_products=item['selection'])
        request = proposal['request']
        if request['data_version'] != VERSION:
            raise ValueError('生产提案改变了固定数据版本')
        if sid == 'q2' and request['window'] != q1_request['window']:
            raise ValueError('Q2必须继承Q1窗口')
        post('/api/session/confirm-proposal', session_id=session_id,
             proposal_id=proposal['proposal_id'])
        started = post('/api/session/task/start', session_id=session_id,
                       prompt_digest='public-eval-service-v1', request=request)
        task_id = started['task_id']
        post('/api/session/task/evidence', session_id=session_id, task_id=task_id)
        post('/api/session/task/generate', session_id=session_id, task_id=task_id)
        prepared = post('/api/session/task/explanation/prepare',
                        session_id=session_id, task_id=task_id,
                        mode=QUESTION_PROTOCOLS[sid]['mode'])
        if prepared['status'] != 'ready_for_provider':
            raise ValueError('解释材料未就绪')
        if (prepared.get('mode') != QUESTION_PROTOCOLS[sid]['mode']
                or prepared.get('protocol') != QUESTION_PROTOCOLS[sid]['protocol']):
            raise ValueError(f'生产解释模式或协议与锁定映射不一致：{sid}')
        session = load_session(ROOT, session_id)
        task = next(t for t in session['tasks'].values() if t['task_id'] == task_id)
        response = task['response']
        packet = load_public_snapshot(ROOT, session_id, task_id, task['explanation'])
        if prepared['messages'] != packet['messages']:
            raise ValueError('接口消息与保存快照不一致')
        if sid == 'q1':
            q1_session, q1_request = session_id, request
        reference = _independent_reference(store.release_root(version), request, scenario=sid)
        reference['required_points'] = item['required_points']
        metrics = {m['id']: m for m in response['report']['evidence']['metrics']}
        for code, row in reference['latest_rows'].items():
            for suffix, field in [('world', 'all_origins_value_usd'), ('china', 'china_value_usd')]:
                if Decimal(str(metrics[f"metric:{code}:{reference['latest_month']}:{suffix}"]['value'])) != Decimal(row[field]):
                    raise ValueError(f'独立参考与生产证据不一致：{sid}/{code}/{field}')
        reference['production_amount_comparison'] = 'passed'
        estimate = estimate_input_tokens(prepared['messages'])
        if estimate['tokens'] > estimate['hard']:
            raise ValueError(f'{sid}超输入硬门：{estimate["tokens"]}')
        qdir, hdir = out / 'requests' / sid, out / 'host_artifacts' / sid
        qdir.mkdir(); hdir.mkdir()
        artifacts = {qdir / 'messages.json': prepared['messages'],
                     hdir / 'request.json': request, hdir / 'proposal.json': proposal,
                     hdir / 'response.json': response, hdir / 'snapshot.json': packet,
                     hdir / 'service_trace.json': trace,
                     out / 'references' / f'{sid}.json': reference}
        if task.get('request_context'):
            artifacts[hdir / 'request_context.json'] = task['request_context']
        for path, value in artifacts.items():
            manifest['files_sha256'][str(path.relative_to(out))] = _write_json(path, value)
        manifest['scenarios'][sid] = {'question': item['question'],
            **QUESTION_PROTOCOLS[sid],
            'input_estimate': estimate, 'session_id': session_id, 'task_id': task_id,
            'service_status': prepared['status'], 'window': request['window']}
    code_paths = list((ROOT / 'src/tradeintel_ai').glob('*.py')) + [Path(__file__),
        ROOT / 'scripts/prepare_public_brief_candidate.py',
        ROOT / 'scripts/prepare_public_eval_diagnostic.py', scenarios_path]
    manifest['code_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(code_paths)}
    manifest['remaining_checks'] = ['browser_followup_and_announcement_recheck',
                                    'provider_configuration_and_scoring_review']
    _write_json(out / 'MANIFEST.json', manifest)
    return {'output': str(out), 'status': manifest['status'],
            'input_estimates': {k: v['input_estimate']['tokens'] for k, v in manifest['scenarios'].items()},
            'question_protocols': manifest['question_protocols'], 'api_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_candidate(args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
