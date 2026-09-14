import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.tradeintel_ai.business_case_selection import select_business_case, FIRST, SECOND
from src.tradeintel_ai.business_workflow import run_business_question
from src.tradeintel_ai.policy_cases import CASES
from src.tradeintel_ai.repository import EvidenceRepository, DataPaths
from src.tradeintel_ai.agent import ModelResponse
from tests.test_policy_exposure_workflow import Model


class BusinessCaseSelectionTests(unittest.TestCase):
    def test_explicit_conflicting_and_ambiguous_selection(self):
        self.assertEqual(select_business_case('3818.00.00政策')[0], FIRST)
        self.assertEqual(select_business_case('光伏政策是什么')[1], 'clarify')
        self.assertEqual(select_business_case('solar policy')[1], 'clarify')
        self.assertEqual(select_business_case('85414300和38180000')[1], 'clarify')
        self.assertEqual(select_business_case('85414300', FIRST)[1], 'clarify')
        self.assertEqual(select_business_case('政策', [SECOND])[1], 'unsupported')
        self.assertEqual(select_business_case('2024-21217')[0], SECOND)

    def test_boundaries_stop_before_model_and_version_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i, question in enumerate(['光伏政策是什么', '85414300在2025-01的金额', '硅片和光伏组件政策']):
                model = MagicMock()
                with patch('src.tradeintel_ai.business_workflow.pin_repository') as pin:
                    state = run_business_question(model, question, root / str(i),
                        repository=EvidenceRepository(DataPaths(root)))
                pin.assert_not_called()
                model.complete.assert_not_called()
                self.assertEqual(state['model_calls'], 0)
                self.assertIn(state['status'], ('clarify', 'unsupported'))
                self.assertTrue((root / str(i) / 'case-selection.json').exists())

    def test_second_case_policy_uses_own_real_evidence_and_prompt(self):
        source = Path(__file__).resolve().parents[1]
        case = CASES[SECOND]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = Path(case.manifest).parent
            shutil.copytree(source / base, root / base, ignore=shutil.ignore_patterns('versions'))
            model = Model([ModelResponse(text=json.dumps({'kind': 'policy'})),
                           ModelResponse(text=json.dumps({'claims': [{
                               'text': '存档公告列有8541.43.00，仍需核查适用条件。',
                               'citations': ['fr202421217:products']}]}))])
            with patch.dict(CASES, {SECOND: replace(case, status='enabled')}):
                state = run_business_question(model, '解释85414300的存档政策', root / 'run',
                                               repository=EvidenceRepository(DataPaths(root)))
            self.assertEqual(state['status'], 'draft_needs_review')
            self.assertEqual(state['policy_id'], SECOND)
            evidence = json.loads((root / 'run/evidence.json').read_text())
            self.assertEqual(evidence['policy_id'], SECOND)
            self.assertEqual(len(evidence['hits']), 4)
            request = (root / 'run/plan-request.json').read_text()
            self.assertIn('2024-21217', request)
            self.assertNotIn('CBP2024-12-31', request)
            self.assertIn('fr202421217:products', (root / 'run/report.zh-CN.md').read_text())
            self.assertEqual(CASES[SECOND].status, 'candidate')
