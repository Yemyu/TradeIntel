"""Bounded, reviewer-gated development checks, never a blind benchmark."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .policy_workflow import safe_metadata, safe_diagnostic
from .research_models import ResearchPlannerModel, ResearchPolicyModel
from .unified_research import UnifiedResearchWorkflow, inspect_delivery, _atomic_text
from .answer_checklist import load_checklists, validate_review, file_hashes, unchanged


CASES = (
    {'id': 'D89-1', 'question': '第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06。',
     'tasks': ['policy'], 'policy': True,
     'reference': '两项政策需求：List1生效2018-07-06，额外25%；逐项核对冻结公告原文，不得写成现行税率。'},
    {'id': 'D89-2', 'question': '第一批关税何时生效，额外税率是多少？政策资料截止日是2018-07-06；请逐月列出其他原产地整体2018-09和2018-10的美元消费进口额；政策整体范围，不做因果分析。',
     'tasks': ['policy', 'trade'], 'policy': True,
     'reference': '两项政策+一项逐月序列。List1生效2018-07-06、额外25%。other_origins/policy_aggregate/消费进口额USD；9月36587820118、10月41012723839；sequence，不解释为政策效果。'},
    {'id': 'D89-3', 'question': '请比较其他原产地整体2018-10相对于2018-09的美元消费进口额；政策整体范围，不做因果分析。',
     'tasks': ['trade'], 'policy': False,
     'reference': '仅贸易比较；other_origins/policy_aggregate/消费进口额USD；9月36587820118为基准、10月41012723839为当前，差4424903721美元、12.09%。只描述，不归因。'},
    {'id': 'D89-4', 'question': '请逐月列出其他原产地整体2018-09和2018-10的美元消费进口额，并另列中国进口份额；政策整体范围，不做因果分析。',
     'tasks': [], 'policy': False,
     'reference': '必须保留金额和中国进口份额两项需求。份额unsupported，needs_scope_selection或保留全部要求的具体澄清；不查金额、不生成政策回答。'},
)
LIMITS = {'attempts': 6, 'reported_tokens_stop': 30000,
          'planning_per_case': 1, 'policy_per_case': 1, 'timeout_seconds': 60}


class SmokeStopped(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def workflow(model, source_kind, checklist_review=False):
    return UnifiedResearchWorkflow(model, require_comparison=True, require_search_query=True,
                                   require_request_units=True, derive_request_offsets=True,
                                   allow_grouped_policy_requests=checklist_review,
                                   planner_source_kind=source_kind)


def snapshot(config, source_kind, checklist_review=False):
    """No credentials; references stay in local review files, not model messages."""
    planner = ResearchPlannerModel(config)
    policy = ResearchPolicyModel(config)
    root = Path(__file__).resolve().parents[2]
    result = {'version': 'development-smoke-0090', 'source_kind': source_kind,
            'cases': deepcopy(CASES), 'limits': dict(LIMITS),
            'configuration': {'base_url': config.base_url,
                              'timeout_seconds': config.timeout_seconds,
                              'planning': planner.effective_request_settings(),
                              'policy_generation': policy.effective_request_settings()},
            'fingerprints': workflow(planner, source_kind)._fingerprints(),
            'entry_sha256': hashlib.sha256((root / 'scripts/run_development_smoke.py').read_bytes()).hexdigest(),
            'reference_source_sha256': hashlib.sha256(
                (root / 'docs/experiments/phase13k-results.zh-CN.md').read_bytes()).hexdigest(),
            'semantic_approval': 'explicit_external_reviewer_required',
            'claim': 'public_development_cases_not_accuracy_or_training'}
    if checklist_review:
        result.update(version='development-smoke-0093', checklists=load_checklists(CASES),
                      integrity_revision='0094',
                      fingerprints=workflow(planner, source_kind, True)._fingerprints(),
                      semantic_approval='independent_checklist_external_review')
    return result


def validate_config(config):
    # Exact endpoint allowlist also avoids logging credentials in URL parameters.
    if config.base_url.rstrip('/') != 'https://open.bigmodel.cn/api/paas/v4':
        raise ValueError('本批只允许智谱通用API端点，不使用默认或带参数的端点')
    if config.model != 'glm-4.7' or config.temperature != 0 or config.timeout_seconds != 60:
        raise ValueError('本批配置必须是glm-4.7、温度0、超时60秒')


def preflight(config, *, checklist_review=False):
    validate_config(config)
    manifest = snapshot(config, 'live', True) if checklist_review else snapshot(config, 'live')
    return {'status': 'offline_preflight_passed', 'new_api_calls': 0,
            'local_key_present': bool(config.api_key.strip()),
            'account_credit': 'not_checked', 'manifest': manifest,
            'manifest_sha256': digest(manifest), 'ready_for_unattended_execution': False}


class CallLedger:
    def __init__(self, output, manifest, fingerprint_check, secret=''):
        self.path = output / 'batch.json'
        self.manifest = manifest
        self.secret = secret
        self.fingerprint_check = fingerprint_check
        self.state = {'status': 'reserved', 'manifest_sha256': digest(manifest),
                      'source_kind': manifest['source_kind'], 'calls': [],
                      'cases': [{'id': c['id'], 'status': 'not_run'} for c in CASES],
                      'denominator': 4, 'new_api_calls': 0, 'reported_tokens': 0,
                      'unknown_usage_attempts': 0, 'semantic_coverage_verified': False}
        self.save()

    def save(self):
        calls = self.state['calls']
        self.state['new_api_calls'] = len(calls) if self.manifest['source_kind'] == 'live' else 0
        self.state['reported_tokens'] = sum(c.get('total_tokens') or 0 for c in calls)
        self.state['unknown_usage_attempts'] = sum(c.get('total_tokens') is None for c in calls)
        self.state['usage_complete'] = self.state['unknown_usage_attempts'] == 0
        write_json(self.path, self.state)

    def check(self):
        if self.state['status'] == 'stopped' or any(c['status'] != 'returned' for c in self.state['calls']):
            raise SmokeStopped('previous_call_not_successful')
        if not self.fingerprint_check():
            raise SmokeStopped('frozen_inputs_changed')

    def call(self, case_id, stage, complete, **kwargs):
        self.check()
        calls = self.state['calls']
        case = next(c for c in CASES if c['id'] == case_id)
        if stage not in ('planning', 'policy_generation') or (stage == 'policy_generation' and not case['policy']):
            raise SmokeStopped('stage_not_authorized')
        if len(calls) >= 6 or any(c['case'] == case_id and c['stage'] == stage for c in calls):
            raise SmokeStopped('attempt_limit')
        if self.state['reported_tokens'] >= 30000:
            raise SmokeStopped('reported_token_stop')
        record = {'case': case_id, 'stage': stage, 'status': 'attempt_reserved', 'total_tokens': None}
        calls.append(record)
        self.save()  # durable reservation BEFORE any provider code
        try:
            response = complete(**kwargs)
            metadata = safe_metadata(response.metadata)
            raw = json.dumps({'text': response.text, 'metadata': metadata,
                              'unexpected_tool_calls': bool(response.tool_calls)}, ensure_ascii=False)
            if self.secret:
                raw = raw.replace(self.secret, '[REDACTED]')
            _atomic_text(self.path.parent / f'{case_id}-{stage}-response.json', raw + '\n')
            record['metadata'] = metadata
            record['total_tokens'] = metadata.get('usage', {}).get('total_tokens')
            if metadata.get('finish_reason') != 'stop' or response.tool_calls:
                raise SmokeStopped('incomplete_or_unexpected_response')
            record['status'] = 'returned'
            self.save()
            return response
        except (Exception, KeyboardInterrupt) as exc:
            record.update(status='failed', diagnostic=safe_diagnostic(exc))
            self.state['status'] = 'stopped'
            self.save()
            raise

    def bind(self, model, case_id, stage):
        original = model.complete
        # Retain model class: workflow snapshots must see real generation settings.
        model.complete = lambda **kwargs: self.call(case_id, stage, original, **kwargs)
        return model


def run_batch(config, output, *, reviewer, reviewer_id, source_kind='live', model_factory=None,
              checklist_review=False):
    """New protocol requires structured reviewer decisions; legacy accepts True.

    No resume or automatic approval. Production CLI requires an interactive reviewer.
    model_factory is an offline test seam and is forbidden for live accounting.
    """
    validate_config(config)
    if source_kind not in ('live', 'fixture') or (source_kind == 'live' and model_factory is not None):
        raise ValueError('invalid model source')
    if not reviewer_id.strip() or not callable(reviewer):
        raise ValueError('explicit reviewer required')
    if source_kind == 'live' and not config.api_key.strip():
        raise ValueError('本地未设置API密钥；未调用')
    get_snapshot = lambda: (snapshot(config, source_kind, True) if checklist_review else snapshot(config, source_kind))
    manifest = get_snapshot()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'manifest.json', manifest)
    frozen = digest(manifest)
    manifest_path = output / 'manifest.json'
    reviewed_files = {str(manifest_path): hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    ledger = CallLedger(output, manifest, lambda: digest(get_snapshot()) == frozen and unchanged(reviewed_files),
                        secret=config.api_key)
    factory = model_factory or (lambda stage: (ResearchPlannerModel if stage == 'planning' else ResearchPolicyModel)(config))
    active_work = None
    active_row = None

    def review(case, row, stage, artifact):
        ledger.check()
        row['status'] = 'awaiting_' + stage + '_review'
        ledger.save()
        packet = {'case': case, 'stage': stage, 'artifact': artifact,
                  'output': str(output / case['id']),
                  'instruction': '逐项核对原问题、计划范围和比较方向；回答须核对数值、原文引用、遗漏及因果边界。不能仅凭文件齐全或引用ID有效通过。'}
        # Record reviewer reasons only after redacting the process credential.
        identity = reviewer_id.replace(config.api_key, '[REDACTED]') if config.api_key else reviewer_id
        if checklist_review:
            packet.update(checklist=deepcopy(manifest['checklists']['cases'][case['id']]),
                          files=file_hashes(output / case['id']))
            review_path = output / f"{case['id']}-{stage}-review.json"
            packet_path = output / f"{case['id']}-{stage}-review-packet.json"
            write_json(packet_path, packet)
            reviewed_files[str(packet_path)] = hashlib.sha256(packet_path.read_bytes()).hexdigest()
            submission = reviewer(deepcopy(packet))
            # Save submitted decisions even when malformed; never leak the local key.
            raw = json.dumps(submission, ensure_ascii=False)
            if config.api_key:
                raw = raw.replace(config.api_key, '[REDACTED]')
            submission = json.loads(raw)
            submission_path = output / f"{case['id']}-{stage}-review-submission.json"
            write_json(submission_path, submission)
            reviewed_files[str(submission_path)] = hashlib.sha256(submission_path.read_bytes()).hexdigest()
            ledger.check()
            record = validate_review(packet, submission, identity)
            if not unchanged(packet['files']):
                raise SmokeStopped('reviewed_artifacts_changed')
            write_json(review_path, record)
            reviewed_files.update(packet['files'])
            reviewed_files.update(file_hashes(output / case['id']))
            # Include the decision itself in all subsequent before-call checks.
            reviewed_files[str(review_path)] = hashlib.sha256(review_path.read_bytes()).hexdigest()
            approved = record['approved']
            row.setdefault('reviews', []).append(record)
        else:
            approved = reviewer(deepcopy(packet)) is True
            row.setdefault('reviews', []).append({'stage': stage, 'reviewer': identity,
                                                 'approved': approved, 'packet_sha256': digest(packet)})
        ledger.save()
        if not approved:
            raise SmokeStopped('review_not_approved')
        ledger.check()

    try:
        for case, row in zip(CASES, ledger.state['cases']):
            active_row = row
            ledger.check()
            row['status'] = 'planning'
            ledger.save()
            model = ledger.bind(factory('planning'), case['id'], 'planning')
            active_work = workflow(model, source_kind, True) if checklist_review else workflow(model, source_kind)
            run_dir = output / case['id']
            preview = active_work.prepare(case['question'], audit_output=run_dir / 'planning', secret=config.api_key)
            write_json(run_dir / 'preview.json', preview)
            ledger.check()
            if case['id'] == 'D89-4':
                if preview['status'] not in ('needs_scope_selection', 'needs_clarification'):
                    raise SmokeStopped('unsupported_scope_not_preserved')
                review(case, row, 'plan', preview)
                active_work.cancel()
            else:
                if preview['status'] != 'needs_confirmation' or sorted(preview['tasks']) != sorted(case['tasks']):
                    raise SmokeStopped('unexpected_plan_status_or_tasks')
                review(case, row, 'plan', preview)
                policy = ledger.bind(factory('policy_generation'), case['id'], 'policy_generation') if case['policy'] else None
                row.update(status='executing', confirmation_basis='explicit_development_reviewer_approval')
                ledger.save()
                result = active_work.confirm(preview['confirmation_token'], run_dir / 'delivery',
                                             model=policy, source_kind=source_kind, secret=config.api_key)
                ledger.check()
                if not inspect_delivery(run_dir / 'delivery').get('verified'):
                    raise SmokeStopped('delivery_not_verified')
                if result['status'] not in ('research_draft', 'trade_draft', 'policy_draft'):
                    raise SmokeStopped('unexpected_execution_status')
                if case['policy'] and result['policy']['generation']['status'] != 'draft_requires_semantic_review':
                    raise SmokeStopped('policy_generation_not_completed')
                review(case, row, 'answer', result)
            row['status'] = 'reviewer_accepted_development_case'
            ledger.save()
        ledger.state['status'] = 'development_review_complete'
    except (Exception, KeyboardInterrupt) as exc:
        ledger.state.update(status='stopped', diagnostic=safe_diagnostic(exc))
        if isinstance(exc, SmokeStopped):
            ledger.state['stop_reason'] = str(exc)
        if active_row is not None:
            active_row['status'] = 'stopped'
    finally:
        if active_work is not None:
            active_work.cancel()
        ledger.save()
    return deepcopy(ledger.state)
