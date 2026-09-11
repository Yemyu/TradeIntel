from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from scripts.score_acceptance_v21 import aggregate, validate_review, score
from scripts.prepare_acceptance_review import prepare
from scripts import run_acceptance_v21 as evaluation
from src.tradeintel_ai.model_adapter import ModelAdapterError, OpenAICompatibleConfig


def fixture():
    categories=['continuous']*18+['causal']*3+['unsupported']*3
    rows=[]
    for repeat in (1,2):
        for i,category in enumerate(categories,1):
            rows.append({'id':f'A{i:02d}','repeat':repeat,'category':category,
                'recorded':True,'generation_complete':True,'visible_response':'verified example',
                'reviewer':'test fixture only','rationale':'synthetic test, not real evaluation',
                'automatic_checks':{'queried_trade_scope_matches':True},
                'required_fact_reviews':[{'numeric':True,'correct':True}],
                'claim_reviews':[{'supported':True,'fabricated_source':False}],
                'task_complete':True,'tool_selection_correct':True,'boundary_correct':True,
                'unsupported_causal_claim':False})
    return {'rows':rows,'run_sha256':'synthetic'}


class ScoreTests(unittest.TestCase):
    def test_end_to_end_failed_collection_and_journal_tamper(self):
        config=OpenAICompatibleConfig(evaluation.BASE,evaluation.MODEL,'fake-secret',60,0)
        with TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()), patch.object(
                evaluation.OpenAICompatibleModel,'complete',side_effect=ModelAdapterError('timeout')):
            run_path=Path(folder)/'run.json'
            evaluation.run(execute=True,output=run_path,config=config)
            review_path=Path(folder)/'review.json'
            review_path.write_text(json.dumps(prepare(run_path)))
            result=score(review_path)
            self.assertEqual(result['recorded_answers'],3)
            self.assertEqual(result['semantic_scores']['pooled']['task']['total'],48)
            self.assertFalse(result['internal_acceptance_passed'])
            journal=run_path.with_suffix('.jsonl')
            journal.write_text('{}\n')
            with self.assertRaises(ValueError):score(review_path)

    def test_all_pass_internal_only(self):
        score=aggregate(fixture(),collected=True)
        self.assertTrue(score['internal_acceptance_passed'])
        self.assertFalse(score['model_adopted'])
        self.assertFalse(score['independent_human_review_verified'])

    def test_pending_never_becomes_pass(self):
        review=fixture()
        review['rows'][0]['required_fact_reviews'][0]['correct']=None
        result=aggregate(review,collected=True)
        self.assertEqual(result['status'],'pending_semantic_review')
        self.assertIsNone(result['semantic_scores'])

    def test_missing_answer_keeps_numeric_and_task_denominators(self):
        review=fixture();r=review['rows'][0]
        r.update(recorded=False,generation_complete=False,visible_response='',reviewer=None,rationale=None)
        r['claim_reviews']=[]
        result=aggregate(review,collected=False)
        pooled=result['semantic_scores']['pooled']
        self.assertEqual(pooled['numeric']['total'],48)
        self.assertEqual(pooled['numeric']['correct'],47)
        self.assertEqual(pooled['task']['total'],48)
        self.assertFalse(result['internal_acceptance_passed'])

    def test_good_pooled_average_cannot_hide_bad_round(self):
        review=fixture()
        for row in review['rows'][:4]:row['task_complete']=False
        result=aggregate(review,collected=True)
        self.assertGreater(result['semantic_scores']['pooled']['task']['rate'],.85)
        self.assertFalse(result['internal_acceptance_passed'])

    def test_any_unsafe_or_fabricated_source_fails(self):
        for field in ('unsafe','fabricated'):
            review=fixture()
            if field=='unsafe':review['rows'][0]['unsupported_causal_claim']=True
            else:review['rows'][0]['claim_reviews'][0]['fabricated_source']=True
            self.assertFalse(aggregate(review,collected=True)['internal_acceptance_passed'])

    def test_claim_and_boundary_judgments_cannot_be_overridden_by_task_flag(self):
        review=fixture()
        review['rows'][0]['claim_reviews'][0]['supported']=False
        review['rows'][21]['boundary_correct']=False
        result=aggregate(review,collected=True)
        self.assertEqual(result['semantic_scores']['pooled']['task']['correct'],46)
        self.assertFalse(result['internal_acceptance_passed'])

    def test_no_claims_is_not_perfect_citation_score(self):
        review=fixture()
        for row in review['rows']:row['claim_reviews']=[]
        result=aggregate(review,collected=True)
        self.assertIsNone(result['semantic_scores']['pooled']['citations']['rate'])
        self.assertFalse(result['internal_acceptance_passed'])

    def test_immutable_evidence_and_strict_booleans(self):
        template=fixture()
        for row in template['rows']:
            for key in ('task_complete','tool_selection_correct','boundary_correct','unsupported_causal_claim','reviewer','rationale'):
                row[key]=None
            for f in row['required_fact_reviews']:f['correct']=None
            for f in row['claim_reviews']:f.update(supported=None,fabricated_source=None)
        validate_review(fixture(),template)
        for mutate in ('drop','duplicate','text','int_bool','numeric'):
            review=fixture()
            if mutate=='drop':review['rows'].pop()
            if mutate=='duplicate':review['rows'][1]=deepcopy(review['rows'][0])
            if mutate=='text':review['rows'][0]['visible_response']='edited answer'
            if mutate=='int_bool':review['rows'][0]['task_complete']=1
            if mutate=='numeric':review['rows'][0]['required_fact_reviews'][0]['numeric']=False
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                validate_review(review,template)
