"""Prepare one reviewed E development candidate from pinned R2 data; no network."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_s3_experiment import build_r2_bundle
from src.tradeintel_ai.brief_fact_catalog import build_fact_catalog, render_fact_catalog
from src.tradeintel_ai.provider_executor import _load_view_package, _verify_named_freeze


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--experiment-id', required=True)
    args = p.parse_args()
    from src.tradeintel_ai.provider_executor import _safe_key
    _safe_key(args.experiment_id, 'experiment_id')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / 'bundle.json'
    build_r2_bundle(bundle)
    catalog = build_fact_catalog(json.loads(bundle.read_text()))
    old_dir = ROOT/'tmp/s3-20260920-freeze-candidate/packages/D1-r2-selected'
    old = json.loads((old_dir/'catalog.json').read_text())
    # Product data and computed observations must remain exactly the same.
    for key in ('facts', 'observations', 'data_version', 'request'):
        if catalog[key] != old[key]:
            raise ValueError('unexpected data change: ' + key)
    catalog_path = output/'catalog.json'
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2))
    question = json.loads((old_dir/'manifest.json').read_text())['question']
    subprocess.run([sys.executable, str(ROOT/'scripts/prepare_bounded_explanation.py'),
                    '--catalog', str(catalog_path), '--question', question,
                    '--output', str(output/'package')], check=True, capture_output=True)
    _load_view_package(output/'package', contract='E')
    reference = output/'reference.zh-CN.md'
    reference.write_text('# 独立审阅参考，不发送模型\n\n'+render_fact_catalog(catalog)+
        '\n验收：金额与份额含义；证据支持的研究重点；具体缺证，三项至少两项。'
        '零严重事实、分母、范围、政策或来源错误。引用仅表示输入关联，不证明推论。')
    runtime = ['src/tradeintel_ai/provider_executor.py', 'src/tradeintel_ai/brief_business_view.py',
               'src/tradeintel_ai/evidence_linked_brief.py', 'src/tradeintel_ai/model_adapter.py',
               'scripts/run_fake_experiment.py', 'scripts/prepare_brief_v3_offline.py',
               'src/tradeintel_ai/bounded_explanation.py', 'src/tradeintel_ai/response_contract.py',
               'src/tradeintel_ai/brief_fact_catalog.py', 'scripts/prepare_bounded_explanation.py']
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    frozen = {'schema_version': 'bounded-provider-freeze-v1', 'experiment_id': args.experiment_id,
              'model': 'glm-4.5-air', 'endpoint': 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
              'params': {'temperature': 0, 'max_tokens': 2000, 'thinking': {'type': 'disabled'}},
              'max_calls': 1, 'runtime_sha256': {n: sha(ROOT/n) for n in runtime},
              'allowed_runs': [{'package': str((output/'package').relative_to(ROOT)), 'contract': 'E',
                                'stage': 'development', 'manifest_sha256': sha(output/'package/manifest.json'),
                                'reference': str(reference.relative_to(ROOT)), 'reference_sha256': sha(reference)}],
              'stop_rule': 'One development call only; no retries or formal questions. Human review required.'}
    _verify_named_freeze(ROOT, frozen, args.experiment_id, output/'package', 'E', {'events': []})
    (output/'freeze-candidate.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2))
    print(json.dumps({'status': 'candidate_ready_not_activated', 'api_calls': 0,
                      'data_unchanged': True, 'output': str(output)}))


if __name__ == '__main__': main()
