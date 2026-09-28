"""Regression checks for actual G1 counterexamples, with no provider traffic."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.evidence_bundle import build_evidence_bundle, render_observations
from src.tradeintel_ai.interpretation_review_store import packet, submit, reviewed_draft
from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig
from src.tradeintel_ai.repository import EvidenceRepository
from src.tradeintel_ai.research_brief_v2 import review, messages
from src.tradeintel_ai.response_contract import canonical_response
from src.tradeintel_ai.web_app import DemoCoordinator
from tests.test_natural_v2 import PROPOSAL, QUESTION
from tests.test_research_brief_v2 import synthetic_trade, synthetic_sheet


def answer(observation='observation.rank_contrast'):
    return {'schema_version':'research-brief-v2', 'findings':[
        {'observation_id':observation, 'explanation':'金额与来源占比分别衡量贸易规模和进口来源结构。',
         'limitation_ids':['limitation.1']}], 'followups':[]}


class CredentialFreeClarificationTests(unittest.TestCase):
    def test_web_preflight_does_not_load_credentials(self):
        with tempfile.TemporaryDirectory() as folder, patch(
                'src.tradeintel_ai.web_app.load_config', side_effect=AssertionError('must not read credentials')):
            coordinator = DemoCoordinator()
            result = coordinator.natural_preview('请比较2026年6月和7月的进口金额',
                repository=None, output_root=Path(folder))
            self.assertEqual(result['status'], 'needs_clarification')
            self.assertEqual(result['model_calls'], 0)
            self.assertNotIn('confirmation_token', result)
            records = list(Path(folder).glob('preview-*/outcome.json'))
            self.assertEqual(len(records), 1)
            self.assertEqual(json.loads(records[0].read_text())['status'], 'needs_clarification')
            self.assertFalse(list(Path(folder).glob('preview-*/attempt.json')))


def make_review_run(root):
    bundle=build_evidence_bundle(synthetic_trade(), synthetic_sheet())
    raw=json.dumps(answer(),ensure_ascii=False)
    files={'status.json':{'status':'interpretation_needs_review','data_version':'v1'},
           'trade-evidence.json':synthetic_trade(),'policy-facts.json':synthetic_sheet(),
           'interpretation-response.json':{'text':raw},
           'interpretation-canonical.json':canonical_response(raw,stage='interpretation'),
           'evidence-bundle.json':bundle}
    for name,value in files.items():
        (root/name).write_text(json.dumps(value,ensure_ascii=False))
    (root/'source-packet.zh-CN.md').write_text('Synthetic only')
    return bundle


class G1RepairTests(unittest.TestCase):
    def test_single_product_real_pipeline_preserves_full_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response = ModelResponse(text=json.dumps(answer('observation.single_product_profile')),
                                     metadata={'finish_reason':'stop'})
            task = {'policy_id':PROPOSAL['request']['policy_id'], 'month':'2026-07',
                    'product':'81019910', 'task':'monthly_exposure', 'focus':'contrast',
                    'schema_version':'research-request-v2', 'policy_view':'archived_event'}
            with patch('src.tradeintel_ai.web_app.load_config', return_value=OpenAICompatibleConfig(
                    'https://fixture.invalid','fixture','fixture')), patch(
                    'src.tradeintel_ai.model_adapter.OpenAICompatibleModel.complete', return_value=response):
                result = DemoCoordinator().structured(task, repository=EvidenceRepository(), output_root=root)
            self.assertEqual(result['status'], 'interpretation_needs_review', result)
            run = root / result['run_id']
            full = json.loads((run / 'policy-facts.json').read_text())
            self.assertEqual(len(full['product_rates']), 5)
            p = packet(run)
            self.assertEqual([r['hts8'] for r in p['evidence_bundle']['policy_facts']['product_rates']], ['81019910'])
            request = json.loads((run / 'interpretation-request.json').read_text())
            sent = json.loads(request['messages'][1]['content'])
            self.assertEqual([r['hts8'] for r in sent['policy_facts']['product_rates']], ['81019910'])
            submit(run, {'fingerprint':p['fingerprint'], 'reviewer':'fixture', 'facts_checked':True,
                         'decisions':[{'index':0,'verdict':'accept','reason':'synthetic only'}]})
            draft = reviewed_draft(run)
            self.assertIn('钨棒', draft)
            self.assertIn('例外未知', draft)
            self.assertNotIn('28046100：存档额外税率', draft)

    def test_bad_cached_share_is_recomputed(self):
        trade=synthetic_trade()
        trade['data']['series'][0]['product_breakdown'][0]['china_share_percent']=1
        bundle=build_evidence_bundle(trade,synthetic_sheet())
        self.assertEqual(bundle['profiles'][0]['china_share_of_product_percent'],70)

    def test_single_zero_product_is_renderable_without_rank(self):
        trade=synthetic_trade()
        trade['data']['hts8']='11111111'
        trade['data']['series'][0]['product_breakdown']=[
            {'hts8':'11111111','china_value_usd':0,'all_origins_value_usd':0}]
        bundle=build_evidence_bundle(trade,synthetic_sheet())
        self.assertEqual([o['type'] for o in bundle['observations']],['single_product_profile'])
        self.assertIn('未知','\n'.join(render_observations(bundle)))

    def test_missing_product_rejected_and_ties_preserved(self):
        trade=synthetic_trade()
        trade['data']['series'][0]['product_breakdown'].pop()
        with self.assertRaises(ValueError): build_evidence_bundle(trade,synthetic_sheet())
        trade=synthetic_trade()
        trade['data']['series'][0]['product_breakdown'][1]['china_value_usd']=700
        bundle=build_evidence_bundle(trade,synthetic_sheet())
        self.assertEqual(bundle['observations'][0]['value'],['11111111','22222222'])

    def test_duplicate_finding_rejected(self):
        response=answer(); response['findings']*=2
        with self.assertRaises(ValueError):
            review(response,build_evidence_bundle(synthetic_trade(),synthetic_sheet()))

    def test_policy_reaches_model_and_trade_refs_exclude_policy(self):
        bundle=build_evidence_bundle(synthetic_trade(),synthetic_sheet())
        payload=json.loads(messages('fixture',bundle)[1]['content'])
        self.assertEqual(payload['policy_facts'],synthetic_sheet())
        self.assertTrue(all(m['source_refs']==['trade:t1'] for m in bundle['metrics']))

    def test_export_contains_numbers_sources_and_uses_checked_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); make_review_run(root)
            p=packet(root)
            submit(root,{'fingerprint':p['fingerprint'],'reviewer':'fixture','facts_checked':True,
                         'decisions':[{'index':0,'verdict':'accept','reason':'synthetic only'}]})
            # _read still reads review history, but must not reopen the bundle.
            from src.tradeintel_ai.interpretation_review_store import _read
            def guarded(path):
                self.assertNotEqual(path.name,'evidence-bundle.json')
                return _read(path)
            with patch('src.tradeintel_ai.interpretation_review_store._read',side_effect=guarded):
                text=reviewed_draft(root)
            self.assertIn('700',text); self.assertIn('70.00%',text)
            self.assertIn('https://example.test/data',text)

    def test_incoherent_bundle_rejected_before_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); bundle=make_review_run(root)
            bundle['policy_id']='wrong-case'
            (root/'evidence-bundle.json').write_text(json.dumps(bundle))
            with self.assertRaises(ValueError): packet(root)

    def test_real_coordinator_preview_confirm_generate_review_export(self):
        # Uses registered local release resources (not private tmp runs).
        # Only the provider boundary/config is replaced; both coordinator
        # methods, the execution engine and export are real.
        for focus,observation in [('contrast','observation.rank_contrast'),
                                  ('china_amount','observation.amount_leader'),
                                  ('china_share','observation.share_leader')]:
            with self.subTest(focus=focus), tempfile.TemporaryDirectory() as directory:
                proposal=deepcopy(PROPOSAL); proposal['request']['focus']=focus
                responses=[ModelResponse(text=json.dumps(proposal),metadata={'finish_reason':'stop'}),
                           ModelResponse(text=json.dumps(answer(observation)),metadata={'finish_reason':'stop'})]
                coordinator=DemoCoordinator(); repo=EvidenceRepository(); root=Path(directory)
                with patch('src.tradeintel_ai.web_app.load_config',return_value=OpenAICompatibleConfig('https://fixture.invalid','fixture','fixture')), \
                     patch('src.tradeintel_ai.model_adapter.OpenAICompatibleModel.complete',side_effect=responses) as provider:
                    question = QUESTION
                    if focus == 'contrast':
                        question = QUESTION.replace('2026年7月', '最新可用数据') + '，不要预测，也不做因果分析。'
                        proposal['request']['month'] = 'latest_available'
                        proposal['evidence']['month'] = '最新可用数据'
                        responses[0] = ModelResponse(text=json.dumps(proposal), metadata={'finish_reason':'stop'})
                    preview=coordinator.natural_preview(question,repository=repo,output_root=root)
                    self.assertEqual(preview['status'],'needs_confirmation')
                    self.assertEqual(provider.call_count,1)
                    result=coordinator.natural_confirm(preview['confirmation_token'],repository=repo,output_root=root)
                    self.assertEqual(result['status'],'interpretation_needs_review',result)
                    self.assertEqual(provider.call_count,2)
                    rejected=coordinator.natural_confirm(preview['confirmation_token'],repository=repo,output_root=root)
                    self.assertEqual(rejected['status'],'confirmation_rejected')
                    self.assertEqual(provider.call_count,2)
                run=root/result['run_id']; p=packet(run)
                self.assertEqual(p['evidence_bundle']['request']['focus'],focus)
                self.assertEqual(p['data_version'],preview['data_version'])
                saved_input = json.loads((run/'input.json').read_text())
                self.assertEqual(saved_input['original_question'],question)
                self.assertEqual(saved_input['month_resolution'],preview['month_resolution'])
                self.assertEqual(saved_input['month_resolution']['resolved_month'],'2026-07')
                submit(run,{'fingerprint':p['fingerprint'],'reviewer':'fixture','facts_checked':True,
                            'decisions':[{'index':0,'verdict':'accept','reason':'synthetic only'}]})
                self.assertIn('8,385,427',reviewed_draft(run))
