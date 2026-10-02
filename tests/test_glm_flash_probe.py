import io
import json
import tempfile
import unittest
from pathlib import Path
from scripts.probe_glm_flash import probe
from scripts.run_us_agent_retest import GateError


class FlashProbeTests(unittest.TestCase):
    def exercise(self, *, fail=False):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            key = base / "credentials.json"
            key.write_text(json.dumps({"glm": {"base_url": "https://open.bigmodel.cn/api/paas/v4",
                                              "api_key": "test-only-not-a-real-key"}}))
            key.chmod(0o600)
            sent = []
            def transport(request, *, timeout):
                body = json.loads(request.data)
                sent.append(body)
                self.assertEqual(body["reasoning_effort"], "high")
                self.assertEqual(timeout, 30)
                if fail:
                    raise TimeoutError("fixture")
                msg = ({"role": "assistant", "content": None, "reasoning_content": "PRIVATE",
                        "tool_calls": [{"id": "call", "type": "function", "function": {
                            "name": "connection_check", "arguments": '{"value":"ping"}'}}]}
                       if len(sent) == 1 else {"role": "assistant", "content": "OK"})
                return io.BytesIO(json.dumps({"model": "glm-5.3-flash", "choices": [{"message": msg}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}).encode())
            output = base / "probe"
            if fail:
                with self.assertRaises(GateError):
                    probe(output, transport=transport, key_path=key)
                self.assertEqual(len(sent), 1)
                self.assertTrue((output / "STOP.json").exists())
            else:
                result = probe(output, transport=transport, key_path=key)
                self.assertEqual(result["estimated_cny"], "0.000272")
                self.assertEqual(sent[1]["messages"][1]["reasoning_content"], "PRIVATE")
                self.assertNotIn("PRIVATE", "".join(p.read_text() for p in output.glob("*.json")))
            with self.assertRaises(GateError):
                probe(output, transport=transport, key_path=key)

    def test_high_tool_roundtrip_private_reasoning_and_price(self):
        self.exercise()

    def test_timeout_is_not_retried(self):
        self.exercise(fail=True)
