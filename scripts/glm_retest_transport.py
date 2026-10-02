"""GLM transport for a separate, finite model comparison.

The existing DeepSeek permit and adapter are left unchanged. Token reservations
are a planning limit, not proof of how a supplier applies a resource pack.
"""
import io
import hashlib
import json
import math
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
import fcntl

from scripts.run_us_agent_retest import GateError, write_new
from scripts.us_retest_transport import canonical_hash, official_transport
from tradeintel_ai.model_adapter import OpenAICompatibleConfig, OpenAICompatibleModel, ModelAdapterError
from tradeintel_ai.trade_agent_deepseek import ThinkingToolResponse

BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ENDPOINT = BASE_URL + "/chat/completions"
MODELS = ("glm-4.5-air", "glm-4.6v")
# Reserve model capacity rather than pretending bytes are tokenizer counts.
# Settlement uses supplier usage. Unknown outcomes keep their reservation.
CAPACITY_BOUND = 1048576


def profile(model):
    if model not in MODELS:
        raise GateError("Model is not one of the two selected resource-pack models")
    return {"base_url": BASE_URL, "model": model, "temperature": 0,
            "timeout_ceiling_seconds": 90,
            "request_params": {"thinking": {"type": "enabled"}, "max_tokens": 8192},
            "stream": False, "reasoning_label": "thinking_enabled",
            "reasoning_effort": "not_sent_not_verified_for_this_model"}


def load_key(path):
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise GateError("Private credentials must be an owner-only regular file")
    config = json.loads(path.read_text())["glm"]
    key = config.get("api_key")
    if (config.get("base_url") != BASE_URL or not isinstance(key, str)
            or not 12 <= len(key) <= 512 or not key.isascii() or any(c.isspace() for c in key)):
        raise GateError("Invalid GLM credential configuration")
    return key


class GLMToolModel(OpenAICompatibleModel):
    """Carry a returned reasoning field through tool turns in memory only.

    GLM 4.x is not given DeepSeek's required-field rule or a guessed effort
    parameter. If reasoning is absent it stays absent; nullable fields keep
    their original type. The original adapter still parses the public answer.
    """
    def __init__(self, config, *, opener=official_transport, request_params=None):
        if config.base_url.rstrip("/") != BASE_URL or config.model not in MODELS:
            raise GateError("GLM adapter endpoint/model mismatch")
        if not request_params or request_params.get("thinking") != {"type": "enabled"}:
            raise GateError("This comparison requires thinking enabled")
        if set(request_params) != {"thinking", "max_tokens"}:
            raise GateError("Unverified GLM request parameter")
        super().__init__(config, system_prompt="", opener=opener, request_params=request_params)
        self._lock = threading.Lock()

    def _payload(self, *, messages, tools):
        payload = super()._payload(messages=messages, tools=tools)
        payload["stream"] = False
        offset = len(payload["messages"]) - len(messages)
        for source, wire in zip(messages, payload["messages"][offset:]):
            if source.get("role") == "assistant" and "reasoning_content" in source:
                value = source["reasoning_content"]
                if value is not None and not isinstance(value, str):
                    raise ModelAdapterError("Invalid GLM reasoning field")
                wire["reasoning_content"] = value
        return payload

    def complete(self, *, messages, tools):
        with self._lock:
            original, bodies = self._opener, []
            def capture(request, *, timeout):
                with original(request, timeout=timeout) as response:
                    raw = response.read()
                bodies.append(raw)
                return io.BytesIO(raw)
            self._opener = capture
            try:
                result = super().complete(messages=messages, tools=tools)
            finally:
                self._opener = original
            message = json.loads(bodies[0])["choices"][0]["message"]
            reasoning = message.get("reasoning_content")
            content = message.get("content")
            if reasoning is not None and not isinstance(reasoning, str):
                raise ModelAdapterError("Invalid GLM reasoning field")
            if content is not None and not isinstance(content, str):
                raise ModelAdapterError("Invalid GLM content field")
            return ThinkingToolResponse(text=result.text, tool_calls=result.tool_calls,
                metadata=result.metadata, reasoning_content=reasoning,
                reasoning_present="reasoning_content" in message,
                wire_content=content, wire_content_present="content" in message)


def validate_permit(permit, effective, digest, now):
    fixed = {"schema": "glm-resource-pack-retest-permit-v1", "approved": True,
             "approver_role": "user", "freeze_sha256": digest,
             "profile_sha256": canonical_hash(effective), "model": effective["model"],
             "endpoint": ENDPOINT, "max_requests": 48, "max_rounds": 6,
             "max_tools": 12, "max_tokens": 8192, "max_body_bytes": 65536,
             "timeout_seconds": 90, "wall_seconds": 7200, "user_turns": 12,
             "retry_allowed": False, "billing": "resource_pack_expected_not_verified"}
    if effective != profile(effective.get("model")):
        raise GateError("Unknown GLM comparison profile")
    for key, value in fixed.items():
        if type(permit.get(key)) is not type(value) or permit[key] != value:
            raise GateError("GLM permit mismatch: " + key)
    evidence = permit.get("authorization_message_sha256")
    if not isinstance(evidence, str) or len(evidence) != 64 or any(c not in "0123456789abcdef" for c in evidence):
        raise GateError("User authorization evidence missing")
    ceiling, expiry = permit.get("max_total_tokens"), permit.get("expires_at")
    if type(ceiling) is not int or not 2 * CAPACITY_BOUND <= ceiling <= 5000000:
        raise GateError("Token reservation ceiling missing/out of range")
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or now >= expiry:
        raise GateError("GLM permit expired or invalid")


class GLMSendLedger:
    def __init__(self, root, permit, effective, verify_inputs, *, turns,
                 clock=time.time, monotonic=time.monotonic):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.permit = json.loads(json.dumps(permit, allow_nan=False))
        self.effective = json.loads(json.dumps(effective, allow_nan=False))
        self.turns = json.loads(json.dumps(turns, allow_nan=False))
        self.verify_inputs, self.clock, self.monotonic = verify_inputs, clock, monotonic
        self.binding = canonical_hash([self.permit, self.effective, self.turns])
        validate_permit(self.permit, self.effective, verify_inputs(), clock())
        self.active = False

    @contextmanager
    def lock(self):
        with (self.root / "ledger.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    @contextmanager
    def batch(self):
        with (self.root / "owner.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise GateError("GLM batch already has an owner") from error
            try:
                with self.lock():
                    if (self.root / "batch.json").exists() or self.records():
                        raise GateError("Existing GLM batch cannot be resumed or retried")
                    self.started_mono, self.last_wall = self.monotonic(), self.clock()
                    validate_permit(self.permit, self.effective, self.verify_inputs(), self.last_wall)
                    self.deadline = min(self.last_wall + 7200, self.permit["expires_at"])
                    write_new(self.root / "batch.json", {"started_at": self.last_wall,
                        "deadline": self.deadline, "permit": self.permit,
                        "binding_sha256": self.binding})
                self.active = True
                yield self
            finally:
                self.active = False
                fcntl.flock(stream, fcntl.LOCK_UN)

    def records(self):
        return [json.loads(p.read_text()) for p in sorted(self.root.glob("send-[0-9][0-9][0-9].json"))]

    def stop(self, reason):
        try:
            write_new(self.root / "STOP.json", {"reason": reason, "retry": False})
        except FileExistsError:
            pass

    def check_time(self):
        if not self.active or (self.root / "STOP.json").exists():
            raise GateError("GLM batch inactive or stopped")
        now, elapsed = self.clock(), self.monotonic() - self.started_mono
        if not math.isfinite(now) or not math.isfinite(elapsed) or now < self.last_wall or elapsed < 0 or now >= self.deadline or elapsed >= 7200:
            self.stop("clock_or_deadline")
            raise GateError("GLM time budget exhausted or invalid")
        if canonical_hash([self.permit, self.effective, self.turns]) != self.binding:
            raise GateError("Frozen GLM settings/identities changed")
        validate_permit(self.permit, self.effective, self.verify_inputs(), now)
        self.last_wall = now

    def reserve(self, request, turn):
        self.check_time()
        body = request.data
        if request.full_url != ENDPOINT or request.get_method() != "POST" or not isinstance(body, bytes) or len(body) > 65536:
            raise GateError("GLM endpoint/body mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError) as error:
            raise GateError("Invalid GLM request JSON") from error
        expected = {"model": self.effective["model"], "temperature": 0,
                    "thinking": {"type": "enabled"}, "max_tokens": 8192, "stream": False}
        if (any(type(payload.get(k)) is not type(v) or payload[k] != v for k, v in expected.items())
                or set(payload) - {*expected, "messages", "tools", "tool_choice"}):
            raise GateError("GLM wire configuration changed")
        if not any(item == turn for item in self.turns):
            raise GateError("Turn not in frozen GLM batch")
        with self.lock():
            self.check_time()
            records = self.records()
            if len(records) >= 48 or sum(r["case_id"] == turn["case_id"] for r in records) >= 6:
                raise GateError("GLM request budget exhausted")
            settled = [self.root / (r["id"] + "-settled.json") for r in records]
            if any(not p.exists() for p in settled):
                raise GateError("Unsettled GLM request; no additional send")
            used = sum(json.loads(p.read_text())["total_tokens"] for p in settled)
            reserve = 2 * CAPACITY_BOUND
            if used + reserve > self.permit["max_total_tokens"]:
                raise GateError("GLM token reservation ceiling reached")
            ident = f"send-{len(records) + 1:03d}"
            write_new(self.root / (ident + ".json"), {"id": ident, "number": len(records) + 1,
                "case_id": turn["case_id"], "request_id": turn["request_id"], "session_id": turn["session_id"],
                "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                "reserved_tokens": reserve, "billing": "not_verified"})
            return ident


class GLMAccountedOpener:
    def __init__(self, ledger, turn, *, transport=official_transport):
        self.ledger, self.turn, self.transport = ledger, dict(turn), transport
        self.pending = self.received = None

    def __call__(self, request, *, timeout):
        if type(timeout) not in (float, int) or not math.isfinite(timeout) or not 0 < timeout <= 90:
            raise GateError("Invalid GLM timeout")
        if self.pending:
            raise GateError("Unsettled GLM request")
        self.pending = self.ledger.reserve(request, self.turn)
        write_new(self.ledger.root / (self.pending + "-dispatched.json"), {"status": "outcome_unknown"})
        try:
            with self.transport(request, timeout=timeout) as response:
                if getattr(response, "status", 200) != 200 or hasattr(response, "geturl") and response.geturl() != ENDPOINT:
                    raise GateError("GLM unexpected status or response URL")
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise GateError("GLM response exceeds limit")
            body = json.loads(raw)
            message = body["choices"][0]["message"]
            if not isinstance(message, dict) or body.get("model") != self.ledger.effective["model"]:
                raise GateError("GLM response model or message mismatch")
            usage = body.get("usage")
            if isinstance(usage, dict):
                usage = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if k in usage}
            self.received = {"model_response": True, "model": body["model"],
                "message": {k: message[k] for k in ("role", "content", "tool_calls") if k in message},
                "usage": usage}
            write_new(self.ledger.root / (self.pending + "-received.json"), self.received)
            return io.BytesIO(raw)
        except Exception:
            self.fail("http_or_protocol_failure")
            raise

    def settle(self):
        usage = (self.received or {}).get("usage")
        values = [usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")] if isinstance(usage, dict) else []
        if (not self.pending or len(values) != 3 or any(type(v) is not int or v < 0 for v in values)
                or values[0] > CAPACITY_BOUND or values[1] > CAPACITY_BOUND or values[2] != values[0] + values[1]):
            self.fail("usage_unknown_or_inconsistent")
            raise GateError("GLM usage is missing or inconsistent")
        with self.ledger.lock():
            write_new(self.ledger.root / (self.pending + "-settled.json"), {
                "id": self.pending, "prompt_tokens": values[0], "completion_tokens": values[1],
                "total_tokens": values[2], "billing": "not_verified"})
        self.pending = self.received = None

    def fail(self, reason):
        if self.pending:
            self.ledger.stop(reason)

    def accounting_complete(self):
        return self.pending is None and not (self.ledger.root / "STOP.json").exists()


def create_model(effective, key, ledger, turn, *, transport=official_transport):
    opener = GLMAccountedOpener(ledger, turn, transport=transport)
    model = GLMToolModel(OpenAICompatibleConfig(BASE_URL, effective["model"], key, 90, 0),
                         opener=opener, request_params=effective["request_params"])
    model.retest_accounting = opener
    model.retest_origin = "api" if transport is official_transport else "offline_fixture"
    return model
