import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
import hashlib
from pathlib import Path

from src.tradeintel_ai.provider_executor import run_experiment, _load_view_package
from src.tradeintel_ai.bounded_explanation import slots


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tmp/host-bound-20260920/D1d'


@unittest.skipUnless((SOURCE / 'catalog.json').is_file(), 'bounded package not prepared')
class BoundedExecutorTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='bounded-exec-'))
        self.addCleanup(shutil.rmtree, self.root)
        self.package = self.root / 'package'
        shutil.copytree(SOURCE, self.package)

    def test_bindings_tamper_even_with_updated_hash_is_rejected(self):
        path = self.package / 'host-bindings.json'
        path.write_text('{}')
        manifest = json.loads((self.package / 'manifest.json').read_text())
        manifest['artifact_files_sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.package / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'host bindings'):
            _load_view_package(self.package, contract='E')

    def test_wrong_contract_cannot_load_e_package(self):
        with self.assertRaisesRegex(ValueError, 'protocol'):
            _load_view_package(self.package, contract='C')

    def test_e_without_named_experiment_never_builds_client(self):
        with patch('src.tradeintel_ai.provider_executor._build_real_provider') as client:
            result = run_experiment(self.root, package=self.package, contract='E',
                                   output=self.root/'never', authorize_real_call=True)
        self.assertEqual(result['status'], 'real_call_not_authorized')
        client.assert_not_called()

    def test_semantic_flag_survives_in_manifest(self):
        catalog = json.loads((self.package / 'catalog.json').read_text())
        answer = {'interpretations': {k: '需要结合统计口径理解观察。' for k in slots(catalog)},
                  'missing_evidence': '缺少其他商品的政策原文。', 'question': '覆盖是否完整？'}
        result = run_experiment(self.root, package=self.package, contract='E',
                               output=self.root/'flag', provider=lambda **kw: (json.dumps(answer), {}))
        self.assertEqual(result['manifest']['validation_status'], 'needs_revision')
        self.assertFalse(result['manifest']['approved'])

    def test_e_contract_uses_existing_ledger_and_writes_pending_attachment(self):
        catalog = json.loads((self.package / 'catalog.json').read_text())
        answer = {'interpretations': {k: '金额与份额衡量不同侧面，不能单独推出替代能力。'
                                     for k in slots(catalog)},
                  'missing_evidence': '供应商产能与规格可比性需要核实。',
                  'question': '是否存在可行的替代供应来源？'}
        calls = []
        def provider(messages, timeout):
            calls.append(messages)
            return json.dumps(answer, ensure_ascii=False), {'completion_tokens': 50, 'stub': True}
        provider.model_name = 'bounded-stub'
        result = run_experiment(self.root, package=self.package, contract='E',
                                output=self.root / 'run', provider=provider)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['manifest']['validation_status'], 'manual_review_required')
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.root / 'run/pending-explanation.zh-CN.md').is_file())

    def test_e_contract_rejects_numeric_restatement(self):
        catalog = json.loads((self.package / 'catalog.json').read_text())
        answer = {'interpretations': {k: '两项合计占96.5%。' for k in slots(catalog)},
                  'missing_evidence': '供应商产能需要核实。', 'question': '能否替代？'}
        result = run_experiment(self.root, package=self.package, contract='E',
                                output=self.root / 'run',
                                provider=lambda **kw: (json.dumps(answer, ensure_ascii=False), {'completion_tokens': 20}))
        self.assertEqual(result['status'], 'invalid_response')
