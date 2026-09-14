"""Host-owned case routing. Candidate resources are never live fallbacks."""
from dataclasses import dataclass

@dataclass(frozen=True)
class PolicyCase:
    policy_id: str
    status: str
    event: str
    products: str
    manifest: str
    monthly: str
    corpus: str
    versions: str
    start: str
    end: str


CASES = {
    'us_301_review2025_tungsten_solar': PolicyCase(
        'us_301_review2025_tungsten_solar', 'enabled',
        'data/processed/policy/section301_review2025_event.csv',
        'data/processed/policy/section301_review2025_products.csv',
        'data/processed/policy_exposure/manifest.json',
        'data/processed/policy_exposure/monthly',
        'data/processed/policy_exposure/policy_corpus.json',
        'data/processed/policy_exposure/versions', '2025-01', '2026-07'),
    'us_301_solar2024': PolicyCase(
        'us_301_solar2024', 'candidate',
        'data/candidates/solar2024/event.csv',
        'data/candidates/solar2024/products.csv',
        'data/candidates/solar2024/manifest.json',
        'data/candidates/solar2024/monthly',
        'data/candidates/solar2024/policy_corpus.json',
        'data/candidates/solar2024/versions', '2025-01', '2026-07'),
}


def resolve_case(policy_id, *, require_enabled=True):
    if not isinstance(policy_id, str) or policy_id not in CASES:
        raise ValueError('未知政策案例，不回退至默认案例')
    case = CASES[policy_id]
    if require_enabled and case.status != 'enabled':
        raise ValueError('政策案例仍在候选验收阶段，尚未开放查询')
    return case


def public_case_catalog():
    """Expose routing availability, never filesystem or credential settings."""
    labels = {'us_301_review2025_tungsten_solar':'2025 钨／硅片／多晶硅',
              'us_301_solar2024':'2024 光伏电池／组件'}
    return {'cases': [
        {'policy_id':case.policy_id, 'label':labels[case.policy_id],
         'status':case.status, 'query_enabled':case.status == 'enabled',
         'status_label':'已登记开放（初稿仍需审阅）' if case.status == 'enabled' else '候选，尚未开放',
         'registered_window':{'start':case.start,'end':case.end}}
        for case in CASES.values()],
        'boundary':'登记开放状态不证明模型质量、API健康或数据版本完整性；执行时仍逐项检查。'}
