import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tradeintel_ai.session_store import create_session, set_request
from src.tradeintel_ai.web_app import _handle_session_post
from tests.test_public_explanation_flow import VERSION, _request


class FollowupCardMergeTests(unittest.TestCase):
    def run_followup(self, text, products=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = create_session(root)
            request = _request()
            request['products'] = ['38180000', '28046100']
            set_request(root, session, request, data_version=VERSION)
            with patch('src.tradeintel_ai.scope_proposal.propose_scope',
                       side_effect=lambda *a, **kw: kw) as propose, \
                 patch('src.tradeintel_ai.web_app._prior_program_context', return_value={}), \
                 patch('src.tradeintel_ai.session_store.save_scope_proposal',
                       side_effect=lambda root, session, proposal: proposal):
                result = _handle_session_post(root, '/api/session/followup', {
                    'session_id': session['session_id'], 'text': text,
                    'selected_products': products or ['38180000'],
                }, repository=None)
                return result, propose.call_count

    def test_card_keeps_shifted_window_and_question(self):
        result, calls = self.run_followup('上月这类商品呢？')
        self.assertEqual(calls, 1)
        request = result['proposal']['request_override']
        self.assertEqual(request['window']['anchor_month'], '2026-06')
        self.assertEqual(request['products'], ['38180000'])
        self.assertIn('上月这类商品呢？', request['original_question'])

    def test_card_does_not_clear_ambiguous_months(self):
        result, calls = self.run_followup('看看2026-05和2026-06')
        self.assertEqual(calls, 0)
        self.assertTrue(result['needs_clarification'])

    def test_conflicting_code_requires_clarification(self):
        result, calls = self.run_followup('28046100怎么样？')
        self.assertEqual(calls, 0)
        self.assertTrue(result['needs_clarification'])

    def test_same_selection_still_retains_new_question(self):
        result, calls = self.run_followup('比去年怎么样？', ['38180000', '28046100'])
        self.assertEqual(calls, 1)
        self.assertIn('比去年怎么样？', result['proposal']['original_question'])

    def test_matching_explicit_code_is_allowed(self):
        result, calls = self.run_followup('38180000在2026-06怎么样？')
        self.assertEqual(calls, 1)
        self.assertFalse(result['needs_clarification'])
        self.assertEqual(result['proposal']['request_override']['window']['anchor_month'], '2026-06')
