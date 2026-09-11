import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_policy_acceptance import execute,preflight
from tradeintel_ai.agent import ModelResponse


class RunnerTests(unittest.TestCase):
    def test_frozen_preflight(self):
        # The historical batch must refuse the evolved application code.
        # Updating its hashes would falsely rebind old results to new code.
        with self.assertRaisesRegex(ValueError, 'Frozen file changed:'):
            preflight()
    def test_infrastructure_stops_remaining(self):
        evidence={'question':'fixture','as_of':'2018-07-06','hits':[{'id':'a','title':'x','page':1,'published':'2018-06-20','text':'x'}]}
        model=Mock()
        model.complete.side_effect=TimeoutError()
        with tempfile.TemporaryDirectory() as t:
            rows=execute([('A',evidence),('B',evidence)],model,Path(t)/'run',source_kind='fixture')
            self.assertEqual(rows[1]['status'],'not_executed_after_infrastructure_stop')
            self.assertEqual(model.complete.call_count,1)
