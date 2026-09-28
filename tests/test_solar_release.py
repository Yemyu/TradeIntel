"""Real local candidate integration; enables routing only inside a test patch."""
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.replay_exposure_update import snapshot
from tradeintel_ai.policy_cases import CASES
from tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
from tradeintel_ai.exposure_version_store import ExposureVersionStore, VersionStoreError
from tradeintel_ai.repository import DataPaths, EvidenceRepository
from tradeintel_ai.tools import ToolError
from tradeintel_ai.research_data_link import research_data_link
from tradeintel_ai.version_report import version_report
from tradeintel_ai.business_workflow import run_business_question
from tradeintel_ai.structured_task import compile_task
from tradeintel_ai.agent import ModelResponse
from tradeintel_ai.interpretation_review_store import packet, submit, reviewed_draft


class SolarReleaseTests(unittest.TestCase):
    def test_real_candidate_release_is_self_contained_and_case_bound(self):
        source = Path(__file__).resolve().parents[1]
        case = CASES['us_301_solar2024']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = Path(case.manifest).parent
            shutil.copytree(source / base, root / base,
                            ignore=shutil.ignore_patterns('versions'))
            repo = EvidenceRepository(DataPaths(root))
            # Production configuration remains candidate; no bypass in tool schema.
            with self.assertRaises(ToolError):
                get_policy_exposure_series(repository=repo, policy_id=case.policy_id)
            with patch.dict(CASES, {case.policy_id: replace(case, status='enabled')}):
                state = snapshot(root, case.end, policy_id=case.policy_id)
                self.assertIn(str(base / 'source.json'), state['policy_files'])
                store = ExposureVersionStore(root, root / case.versions)
                store.bootstrap(state)
                release = store.prepare_release(state['version'])
                receipt = json.loads((release / 'release.json').read_text())
                self.assertTrue(all(p.startswith(str(base) + '/') for p in receipt['files']))
                result = get_policy_exposure_series(repository=repo, policy_id=case.policy_id)
                self.assertEqual(result['data']['months'], 19)
                self.assertTrue(result['data']['coverage_complete'])
                self.assertEqual(result['data_version'], state['version'])
                self.assertEqual(result['policy_evidence']['policy_id'], case.policy_id)
                self.assertEqual(len(result['policy_evidence']['hits']), 4)
                self.assertEqual({p['hts8'] for p in result['data']['series'][0]['product_breakdown']},
                                 {'85414200', '85414300'})
                run = root / 'isolated-run'
                run.mkdir()
                (run/'status.json').write_text(json.dumps({'policy_id':case.policy_id,
                                                         'data_version':state['version']}))
                (run/'trade-evidence.json').write_text(json.dumps(result))
                link = research_data_link(root, run)
                self.assertEqual(link['status'], 'bound')
                self.assertIn('&policy_id=us_301_solar2024', link['url'])
                html = version_report(root, state['version'], policy_id=case.policy_id)
                self.assertIn('policy_id=us_301_solar2024', html)
                self.assertIn(state['version'], html)
                task = {'policy_id':case.policy_id, 'month':'2026-07',
                        'product':'85414200', 'task':'monthly_exposure', 'focus':'contrast'}
                question, _ = compile_task(task)
                class OfflineModel:
                    calls = 0
                    def complete(self, **kwargs):
                        self.calls += 1
                        return ModelResponse(text=json.dumps({'schema_version':'research-brief-v2',
                            'findings':[{'observation_id':'observation.single_product_profile',
                            'explanation':'金额与份额描述不同维度，不能据此认定政策效果。',
                            'limitation_ids':['limitation.1']}], 'followups':[]}),
                            metadata={'finish_reason':'stop'})
                model = OfflineModel()
                output = root / 'isolated-business'
                finished = run_business_question(model, question, output, repository=repo,
                    policy_id=case.policy_id, interpretation_mode=True, structured_task=task)
                self.assertEqual(finished['status'], 'interpretation_needs_review')
                self.assertEqual(model.calls, 1)
                p = packet(output)
                self.assertEqual(p['evidence_bundle']['policy_id'], case.policy_id)
                submit(output, {'fingerprint':p['fingerprint'], 'reviewer':'synthetic-test',
                    'facts_checked':True, 'decisions':[{'index':0,'verdict':'accept','reason':'test only'}]})
                draft = reviewed_draft(output)
                self.assertIn('85414200', draft)
                self.assertNotIn('81019910', draft)
                self.assertEqual(research_data_link(root, output)['status'], 'bound')
                # No primary store exists in this isolated workspace. A link
                # must not fall back to that store or the active primary case.
                with self.assertRaises(VersionStoreError):
                    version_report(root, state['version'])
                with self.assertRaises(ToolError):
                    get_policy_exposure_series(repository=repo, policy_id=case.policy_id, hts8='38180000')
                # Source damage outside the release must not change a pinned query.
                (root / base / 'source.json').write_text('{}')
                self.assertEqual(get_policy_exposure_series(repository=repo, policy_id=case.policy_id), result)
                # Damage inside the sealed release must stop query execution.
                (release / base / 'source.json').write_text('{}')
                with self.assertRaises(VersionStoreError):
                    get_policy_exposure_series(repository=repo, policy_id=case.policy_id)
            self.assertEqual(CASES[case.policy_id].status, 'candidate')
            with self.assertRaises(ValueError):
                version_report(root, state['version'], policy_id=case.policy_id)
