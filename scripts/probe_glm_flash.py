"""Bounded GLM-5.3-Flash tool probe; does not use business questions."""
import argparse
import json
from decimal import Decimal
from pathlib import Path
from urllib.request import Request

from scripts.glm_retest_transport import ENDPOINT, load_key
from scripts.run_glm_agent_retest import CREDENTIALS
from scripts.run_us_agent_retest import GateError, write_new
from scripts.us_retest_transport import canonical_hash, official_transport


def probe(root, *, transport=official_transport, key_path=CREDENTIALS):
    if root.exists():
        raise GateError("Probe exists; no retry")
    root.mkdir(parents=True)
    write_new(root / "started.json", {
        "model": "glm-5.3-flash", "reasoning_effort": "high", "max_requests": 2,
        "max_tokens": 1024, "timeout_seconds": 30, "retry": False,
        "purpose": "tool_roundtrip_not_accuracy", "budget_cny": "2",
        "input_price_per_million": "0.8", "output_price_per_million": "2.8",
        "price_source": "https://docs.bigmodel.cn/cn/guide/start/pricing",
        "hypothesis": "High profile can call a tool and consume its result",
        "data": "synthetic ping only; no evaluation answers"})
    key = load_key(key_path)
    messages = [{"role": "user", "content": "Call connection_check with value ping. After the tool responds, reply only OK."}]
    tools = [{"type": "function", "function": {"name": "connection_check",
              "description": "Synthetic connection check", "parameters": {"type": "object",
              "properties": {"value": {"type": "string"}}, "required": ["value"], "additionalProperties": False}}}]
    cost = Decimal(0)
    for number in (1, 2):
        body = {"model": "glm-5.3-flash", "messages": messages, "tools": tools,
                "thinking": {"type": "enabled"}, "reasoning_effort": "high",
                "max_tokens": 1024, "stream": False, "temperature": 0}
        if number == 1:
            body["tool_choice"] = {"type": "function", "function": {"name": "connection_check"}}
        encoded = json.dumps(body).encode()
        # Reserve full advertised 1M input capacity plus requested output.
        reservation = Decimal("0.8") + Decimal(1024) * Decimal("2.8") / 1000000
        if cost + reservation > Decimal("2") or len(encoded) > 65536:
            raise GateError("Probe budget/body limit")
        write_new(root / f"send-{number}.json", {"body_sha256": canonical_hash(body),
                  "body_bytes": len(encoded), "reserved_cny": str(reservation)})
        request = Request(ENDPOINT, data=encoded, method="POST",
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with transport(request, timeout=30) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024 or getattr(response, "status", 200) != 200:
                    raise GateError("Probe response limit/status")
            result = json.loads(raw)
            if result.get("model") != "glm-5.3-flash":
                raise GateError("Response model mismatch")
            usage = result["usage"]
            values = [usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")]
            if (any(type(v) is not int or v < 0 for v in values)
                    or values[0] > 1000000 or values[1] > 1024 or values[2] != values[0] + values[1]):
                raise GateError("Probe usage unaccounted")
            cost += (Decimal(values[0]) * Decimal("0.8") + Decimal(values[1]) * Decimal("2.8")) / 1000000
            message = result["choices"][0]["message"]
            write_new(root / f"response-{number}.json", {"model": result["model"],
                      "usage": {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
                      "message": {k: message[k] for k in ("role", "content", "tool_calls") if k in message},
                      "estimated_cumulative_cny": str(cost), "billing": "not_verified"})
            if number == 1:
                calls = message.get("tool_calls", [])
                if len(calls) != 1 or calls[0]["function"]["name"] != "connection_check" or json.loads(calls[0]["function"]["arguments"]) != {"value": "ping"}:
                    raise GateError("Synthetic tool call mismatch")
                messages.append(message)  # Transient reasoning never written to disk.
                messages.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": "OK"})
            elif message.get("tool_calls") or (message.get("content") or "").strip() != "OK":
                raise GateError("Synthetic final reply mismatch")
        except Exception as error:
            write_new(root / "STOP.json", {"attempt": number, "retry": False,
                      "error_type": type(error).__name__, "http_status": getattr(error, "code", None)})
            raise GateError("Probe failed; saved safe stop record") from None
    receipt = {"status": "tool_roundtrip_passed", "model": "glm-5.3-flash", "reasoning_effort": "high",
               "api_requests": 2, "formal_questions": 0, "estimated_cny": str(cost), "billing": "not_verified"}
    write_new(root / "result.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute required")
    print(json.dumps(probe(args.output.absolute()), ensure_ascii=False))
