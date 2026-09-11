import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/run_policy_retrieval.py'


class PolicyCliTests(unittest.TestCase):
    def test_conflicting_modes_rejected(self):
        r=subprocess.run([sys.executable,str(SCRIPT),'--generate','--replay-last'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)

    def test_cannot_replay_for_another_question(self):
        r=subprocess.run([sys.executable,str(SCRIPT),'--replay-last','--question','别的问题'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        self.assertIn('必须保持原问题',r.stderr)

    def test_no_evidence_needs_no_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            r=subprocess.run([sys.executable,str(SCRIPT),'--generate','--question','现在税率是多少？','--output-dir',temp],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            results=list(Path(temp).glob('run-*/result.json'))
            self.assertEqual(len(results),1)
            result=json.loads(results[0].read_text())
            self.assertEqual(result['audit']['new_api_calls'],0)
            self.assertEqual(result['generation']['status'],'no_evidence')
