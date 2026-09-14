import unittest
from unittest.mock import Mock
from scripts.recover_solar_generation import OneGenerationRecovery
from tradeintel_ai.agent import ModelResponse


class GenerationRecoveryTests(unittest.TestCase):
    def test_reuses_plan_and_only_sends_identical_generation_once(self):
        provider = Mock(); provider.complete.return_value = ModelResponse(text='answer')
        request = {'messages':[{'role':'user','content':'frozen'}], 'tools':[]}
        record = Mock(); recovery = OneGenerationRecovery('plan',request,provider,record)
        self.assertEqual(recovery.complete(messages=[],tools=[]).text,'plan')
        provider.complete.assert_not_called()
        self.assertEqual(recovery.complete(**request).text,'answer')
        with self.assertRaises(ValueError): recovery.complete(**request)
        provider.complete.assert_called_once_with(**request)

    def test_changed_evidence_stops_without_network(self):
        provider = Mock(); request = {'messages':[], 'tools':[]}
        recovery = OneGenerationRecovery('plan',request,provider,Mock())
        recovery.complete(**request)
        with self.assertRaises(ValueError): recovery.complete(messages=[{'role':'user','content':'different'}],tools=[])
        provider.complete.assert_not_called()

    def test_failed_request_is_not_retried(self):
        provider = Mock(); provider.complete.side_effect = TimeoutError()
        request = {'messages':[], 'tools':[]}
        recovery = OneGenerationRecovery('plan',request,provider,Mock())
        recovery.complete(**request)
        with self.assertRaises(TimeoutError): recovery.complete(**request)
        with self.assertRaises(ValueError): recovery.complete(**request)
        self.assertEqual(provider.complete.call_count,1)
