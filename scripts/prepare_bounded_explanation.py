"""Prepare minimal host-bound explanation offline; never calls a provider."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))
from tradeintel_ai.bounded_explanation import VERSION, messages, slots
from tradeintel_ai.brief_business_view import build_view
from tradeintel_ai.brief_fact_catalog import render_fact_catalog
from scripts.prepare_brief_v3_offline import estimate_input_tokens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--question', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    request = messages(args.question, catalog)
    view, sidecar = build_view(args.question, catalog, deduplicate=True)
    estimate = estimate_input_tokens(request)
    args.output.mkdir(parents=True, exist_ok=False)
    files = {'messages.json': request, 'host-bindings.json': slots(catalog),
             'catalog.json': catalog, 'business-view.json': view,
             'business-view-sidecar.json': sidecar}
    for name, value in files.items():
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    (args.output / 'program-report-A3.zh-CN.md').write_text(render_fact_catalog(catalog))
    manifest = {'schema_version': 'brief-view-offline-manifest-v1',
                'protocol': VERSION, 'mode': 'bounded_explanation_offline',
                'representation': 'exact_value_dedup_v1',
                'api_calls': 0, 'network_calls': 0, 'credential_used': False,
                'model_result': False, 'callable': False,
                'question': args.question,
                'status': 'prepared_view_no_model_result' if estimate['tokens'] <= 16000 else 'blocked_budget',
                'catalog_sha256': catalog['catalog_sha256'], 'input_estimate': estimate,
                'required_files': ['catalog.json', 'business-view.json',
                                  'business-view-sidecar.json', 'messages.json',
                                  'program-report-A3.zh-CN.md', 'host-bindings.json'],
                'boundary': 'E contract only; no semantic approval or authorization implied.'}
    manifest['artifact_files_sha256'] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in args.output.iterdir() if p.is_file()}
    manifest['binding'] = {'catalog_sha256': catalog['catalog_sha256'],
                           'view_catalog_sha256': view['policy']['catalog_sha256'],
                           'sidecar_view_schema': sidecar['view_schema'],
                           'id_map_size': len(sidecar.get('id_map', {})),
                           'view_question_matches': view.get('question') == args.question}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == '__main__': main()
