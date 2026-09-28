import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.tradeintel_ai.agent import ModelResponse
from src.tradeintel_ai.natural_v2 import NaturalV2Session, propose, validate_candidate


QUESTION = "请分析2026年7月2025钨政策全部登记税号，中国原产金额和中国来源占比有什么区别？"
PROPOSAL = {
    "status": "proposal",
    "request": {
        "schema_version": "research-request-v2",
        "policy_id": "us_301_review2025_tungsten_solar",
        "month": "2026-07",
        "product": "all",
        "focus": "contrast",
        "policy_view": "archived_event",
    },
    "evidence": {
        "policy_id": "2025钨政策",
        "month": "2026年7月",
        "product": "全部登记税号",
        "focus": "中国原产金额和中国来源占比有什么区别",
    },
    "missing": [],
}


class FakeRepo:
    exposure_version = "v" * 64
    exposure_snapshot = {"start": "2025-01", "end": "2026-07"}


class FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return ModelResponse(text=self.payload, metadata={"finish_reason": "stop"})


class NaturalV2Tests(unittest.TestCase):
    def test_latest_is_host_resolved_and_preserves_raw_intent(self):
        question = QUESTION.replace('2026年7月', '最新可用数据')
        payload = json.loads(json.dumps(PROPOSAL))
        payload['request']['month'] = 'latest_available'
        payload['evidence']['month'] = '最新可用数据'
        session = NaturalV2Session()
        with tempfile.TemporaryDirectory() as folder, patch(
                'src.tradeintel_ai.natural_v2.pin_repository', return_value=FakeRepo()):
            directory = Path(folder) / 'preview-latest'
            preview = session.preview(question, FakeModel(json.dumps(payload)),
                repository=FakeRepo(), audit_directory=directory)
            self.assertEqual(preview['status'], 'needs_confirmation')
            self.assertEqual(preview['request']['month'], '2026-07')
            self.assertEqual(preview['month_resolution']['intent'], 'latest_available')
            confirmed = session.consume(preview['confirmation_token'], repository=FakeRepo())
            self.assertEqual(confirmed['original_question'], question)
            self.assertEqual(confirmed['month_resolution'], preview['month_resolution'])
            self.assertIn('latest_available', (directory / 'response.json').read_text())
        self.assertEqual(payload['request']['month'], 'latest_available')

    def test_latest_cannot_be_guessed_by_model(self):
        question = QUESTION.replace('2026年7月', '最新可用数据')
        payload = json.loads(json.dumps(PROPOSAL))
        payload['evidence']['month'] = '最新可用数据'
        with self.assertRaises(ValueError):
            validate_candidate(payload, question)

    def test_latest_missing_release_and_changed_version_never_execute(self):
        question = QUESTION.replace('2026年7月', '最新可用月份')
        payload = json.loads(json.dumps(PROPOSAL))
        payload['request']['month'] = 'latest_available'
        payload['evidence']['month'] = '最新可用月份'
        missing = FakeRepo()
        missing.exposure_snapshot = None
        with patch('src.tradeintel_ai.natural_v2.pin_repository', return_value=missing):
            result = NaturalV2Session().preview(question, FakeModel(json.dumps(payload)), repository=missing)
            self.assertEqual(result['status'], 'not_available')
            self.assertNotIn('confirmation_token', result)
        session = NaturalV2Session()
        changed = FakeRepo()
        changed.exposure_version = 'different-version'
        with patch('src.tradeintel_ai.natural_v2.pin_repository', side_effect=[FakeRepo(), changed]):
            preview = session.preview(question, FakeModel(json.dumps(payload)), repository=FakeRepo())
            result = session.consume(preview['confirmation_token'], repository=changed)
            self.assertEqual(result['status'], 'confirmation_stale')
            self.assertFalse(result['execution_attempted'])

    def test_bounded_negative_limits_are_allowed(self):
        with patch('src.tradeintel_ai.natural_v2.pin_repository', return_value=FakeRepo()):
            result = propose(QUESTION + '，不要预测，也不做因果分析。',
                FakeModel(json.dumps(PROPOSAL)), repository=FakeRepo())
        self.assertEqual(result['status'], 'needs_confirmation')

    def test_conflicting_latest_and_positive_unsupported_requests_do_not_call(self):
        for suffix in ['，最新可用数据', '，请预测', '，请做因果分析', '，计算现行总税率',
                       '，不要预测但要因果分析', '，不要预测，排除81019910']:
            model = FakeModel(json.dumps(PROPOSAL))
            result = propose(QUESTION + suffix, model, repository=FakeRepo())
            self.assertEqual(result['status'], 'needs_clarification', suffix)
            self.assertEqual(model.calls, 0)

    def test_unsupported_scope_never_calls_model_or_issues_token(self):
        for suffix in ['，还要2026年6月', '，对比6月和7月', '，看6、7月',
                       '，同比变化', '，排除81019910', '，不要金额只看份额',
                       '，用最新数据', '，current month', '，81019400和81019980']:
            with self.subTest(suffix=suffix):
                model = FakeModel(json.dumps(PROPOSAL))
                result = NaturalV2Session().preview(QUESTION + suffix, model, repository=FakeRepo())
                self.assertEqual(result['status'], 'needs_clarification')
                self.assertEqual(model.calls, 0)
                self.assertFalse(result['execution_attempted'])
                self.assertNotIn('confirmation_token', result)
                with self.assertRaises(ValueError):
                    validate_candidate(PROPOSAL, QUESTION + suffix)

    def test_scope_preflight_is_audited_as_zero_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'preview-scope'
            result = NaturalV2Session().preview(QUESTION + '，看最新月份', FakeModel('unused'),
                                               audit_directory=directory)
            self.assertEqual(result['model_calls'], 0)
            self.assertFalse((directory/'attempt.json').exists())
            self.assertEqual(json.loads((directory/'outcome.json').read_text())['status'],
                             'needs_clarification')

    def test_model_cannot_expand_explicit_product_to_all(self):
        with self.assertRaises(ValueError):
            validate_candidate(PROPOSAL, QUESTION + '，81019910')

    def test_audit_persists_raw_response_and_binds_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'preview-test'
            with patch('src.tradeintel_ai.natural_v2.pin_repository', return_value=FakeRepo()):
                session = NaturalV2Session()
                result = session.preview(QUESTION, FakeModel(json.dumps(PROPOSAL)),
                                         repository=FakeRepo(), audit_directory=directory)
                confirmed = session.consume(result['confirmation_token'], repository=FakeRepo())
            self.assertEqual(json.loads((directory/'request.json').read_text())['question'], QUESTION)
            response = json.loads((directory/'response.json').read_text())
            self.assertEqual(json.loads(response['response']['text']), PROPOSAL)
            self.assertIsNone(response['usage'])
            self.assertEqual(set(confirmed['planning_audit']['files']),
                             {'request.json', 'attempt.json', 'response.json', 'outcome.json'})
            self.assertNotIn('planning_audit', result)

    def test_failed_parse_is_recorded_without_token_or_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'preview-failed'
            result = NaturalV2Session().preview(QUESTION, FakeModel('fake-secret invalid JSON'),
                repository=FakeRepo(), audit_directory=directory, secret='fake-secret')
            self.assertEqual(result['status'], 'needs_review')
            self.assertNotIn('confirmation_token', result)
            raw = (directory/'response.json').read_text()
            self.assertNotIn('fake-secret', raw)
            self.assertIn('[REDACTED]', raw)

    def test_transport_failure_keeps_attempt_but_not_exception_secret(self):
        class BrokenModel:
            def complete(self, **kwargs):
                raise RuntimeError('sensitive transport details')
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder) / 'preview-transport'
            result = NaturalV2Session().preview(QUESTION, BrokenModel(),
                repository=FakeRepo(), audit_directory=directory)
            self.assertEqual(result['status'], 'needs_review')
            self.assertEqual(json.loads((directory/'response.json').read_text()),
                             {'error_type': 'RuntimeError', 'usage': None})
            self.assertTrue((directory/'attempt.json').exists())

    def test_candidate_requires_literal_quotes_and_fixed_view(self):
        self.assertIsNotNone(validate_candidate(PROPOSAL, QUESTION))
        invalid = json.loads(json.dumps(PROPOSAL, ensure_ascii=False))
        invalid["evidence"]["month"] = "七月"
        with self.assertRaises(ValueError):
            validate_candidate(invalid, QUESTION)
        invalid = json.loads(json.dumps(PROPOSAL, ensure_ascii=False))
        invalid["request"]["policy_view"] = "current"
        with self.assertRaises(ValueError):
            validate_candidate(invalid, QUESTION)

    def test_preview_is_bounded_and_confirmation_is_one_time(self):
        model = FakeModel("```json\n" + json.dumps(PROPOSAL, ensure_ascii=False) + "\n```")
        with patch("src.tradeintel_ai.natural_v2.pin_repository", return_value=FakeRepo()):
            session = NaturalV2Session()
            result = session.preview(QUESTION, model, repository=FakeRepo())
            self.assertEqual(result["status"], "needs_confirmation")
            self.assertEqual(result["model_calls"], 1)
            self.assertEqual(model.calls, 1)
            token = result["confirmation_token"]
            confirmed = session.consume(token, repository=FakeRepo())
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertFalse(confirmed["execution_attempted"])
            rejected = session.consume(token, repository=FakeRepo())
            self.assertEqual(rejected["status"], "confirmation_rejected")

    def test_stale_version_invalidates_preview_before_execution(self):
        model = FakeModel(json.dumps(PROPOSAL, ensure_ascii=False))
        repo = FakeRepo()
        with patch("src.tradeintel_ai.natural_v2.pin_repository", return_value=repo):
            session = NaturalV2Session()
            result = session.preview(QUESTION, model, repository=repo)
            repo.exposure_version = "w" * 64
            stale = session.consume(result["confirmation_token"], repository=repo)
        self.assertEqual(stale["status"], "confirmation_stale")
        self.assertFalse(stale["execution_attempted"])

    def test_model_clarification_never_creates_token(self):
        clarification = {"status": "clarify", "request": None,
                         "evidence": {}, "missing": ["month"]}
        model = FakeModel(json.dumps(clarification))
        result = propose(QUESTION, model, repository=FakeRepo())
        self.assertEqual(result["status"], "needs_clarification")
        self.assertNotIn("confirmation_token", result)


if __name__ == "__main__":
    unittest.main()
