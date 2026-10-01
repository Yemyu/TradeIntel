"""Single-owner, append-only send/accounting boundary for the finite retest.

No key loading and no CLI network entry. Production factories receive this
opener only after a separately reviewed freeze and finite user permit exist.
"""
import io
import json
import math
import time
import hashlib
import fcntl
from pathlib import Path
from decimal import Decimal
from contextlib import contextmanager
from urllib.request import build_opener, HTTPRedirectHandler

from scripts.run_us_agent_retest import GateError, write_new

ENDPOINT = "https://api.deepseek.com/chat/completions"
INPUT_BOUND = 1048576
OUTPUT_BOUNDS = {"confirmed_total_max_tokens": 8192, "capacity_fallback": 393216}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GateError("Redirect rejected before next HTTP request")


def official_transport(request, *, timeout):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


def create_accounted_model(config, params, ledger, turn, *, transport=official_transport):
    from tradeintel_ai.trade_agent_deepseek import create_trade_agent_model
    opener = AccountedOpener(ledger, turn, transport=transport)
    model = create_trade_agent_model(config, params, opener=opener)
    model.retest_accounting = opener
    model.retest_origin = "api" if transport is official_transport else "offline_fixture"
    return model


def validate_permit(permit, freeze_digest, now):
    continuation = permit.get("schema") == "us-retest-continuation-permit-v2"
    fixed = {"schema": "us-retest-continuation-permit-v2" if continuation else "us-retest-finite-permit-v1", "approved": True,
             "approver_role": "user", "freeze_sha256": freeze_digest,
             "endpoint": ENDPOINT, "model": "deepseek-flash", "reasoning_effort": "high",
             "max_requests": 48,
             "max_rounds": 6, "max_tools": 12, "max_tokens": 8192,
             "max_body_bytes": 65536, "timeout_seconds": 90, "wall_seconds": 7200,
             "user_turns": 11 if continuation else 12, "retry_allowed": False}
    if continuation:
        fixed.update(currency="CNY", new_time_window_authorized=True, consumed_requests=5)
        if (permit.get("currency") != "CNY" or permit.get("consumed_cost") != "0.036040"
                or permit.get("allowlist") != ["R02", "R03", "R04", "R05", "R06", "T01", "T02", "T03", "T04", "P01", "P02"]):
            raise GateError("Continuation finite scope/cumulative basis mismatch")
    prices = {"USD": ("2", "0.30", "1.20"), "CNY": ("10", "2", "8")}
    currency = permit.get("currency")
    if currency not in prices:
        raise GateError("Unsupported verified billing currency")
    budget, input_price, output_price = prices[currency]
    fixed.update(currency=currency, budget=budget, input_price_per_million=input_price,
                 output_price_per_million=output_price)
    for key, value in fixed.items():
        if type(permit.get(key)) is not type(value) or permit[key] != value:
            raise GateError("Finite permit mismatch: " + key)
    for key in ("authorization_message_sha256", "price_source_sha256", "freeze_sha256"):
        value = permit.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise GateError("Missing permit evidence digest: " + key)
    if continuation:
        for key in ("parent_freeze_sha256", "parent_files_sha256"):
            value = permit.get(key)
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise GateError("Missing continuation evidence digest")
    expiry = permit.get("expires_at")
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or now >= expiry:
        raise GateError("Permit expired or invalid")
    route = permit.get("output_bound_route")
    if route not in OUTPUT_BOUNDS:
        raise GateError("Unverified output reservation route")
    if route == "confirmed_total_max_tokens" and not permit.get("total_output_contract_sha256"):
        raise GateError("Total thinking-output contract not verified")
    return OUTPUT_BOUNDS[route]


class SendLedger:
    """One durable reservation contains both wire and money, never two ledgers."""
    def __init__(self, root, permit, verify_inputs, *, turns, clock=time.time, monotonic=time.monotonic, continuation=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.permit = json.loads(json.dumps(permit, allow_nan=False))
        self.verify_inputs = verify_inputs
        self.clock, self.monotonic = clock, monotonic
        self.output_bound = validate_permit(self.permit, verify_inputs(), clock())
        self.permit_digest = canonical_hash(self.permit)
        self.turns = json.loads(json.dumps(turns, allow_nan=False))
        self.turns_digest = canonical_hash(self.turns)
        self.continuation = continuation
        self.consumed_requests, self.consumed_cost = 0, Decimal(0)
        if self.permit["schema"] == "us-retest-continuation-permit-v2":
            if (not continuation or continuation.get("parent_freeze_sha256") != self.permit["parent_freeze_sha256"]
                    or canonical_hash(continuation["parent_files"]) != self.permit["parent_files_sha256"]
                    or continuation.get("consumed_requests") != self.permit["consumed_requests"]
                    or continuation.get("consumed_cost") != self.permit["consumed_cost"]
                    or continuation.get("allowlist") != self.permit["allowlist"]
                    or [t["case_id"] for t in self.turns] != self.permit["allowlist"]):
                raise GateError("Continuation permit differs from frozen ancestor")
            self.consumed_requests = continuation["consumed_requests"]
            self.consumed_cost = Decimal(continuation["consumed_cost"])
        elif continuation is not None:
            raise GateError("Continuation requires its own finite permission")
        self.active = False
        self.last_wall = None

    @contextmanager
    def lock(self):
        with (self.root / "ledger.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    @contextmanager
    def batch(self):
        with (self.root / "owner.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise GateError("Batch already owned") from exc
            try:
                if self.continuation is not None:
                    parent = Path(self.continuation["parent"])
                    with (parent / "ledgers/live/owner.lock").open("a") as parent_owner:
                        try:
                            fcntl.flock(parent_owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError as exc:
                            raise GateError("Ancestor batch has an active owner") from exc
                        self.verify_inputs()
                        target = parent / "results/CONTINUATION_CLAIM.json"
                        claim = {"schema": "us-retest-one-child-v1", "parent_freeze_sha256": self.permit["parent_freeze_sha256"],
                            "child_freeze_sha256": self.permit["freeze_sha256"], "child": str(self.root.parent.parent.resolve()),
                            "allowlist": self.permit["allowlist"]}
                        if target.exists():
                            if json.loads(target.read_text()) != claim:
                                raise GateError("Ancestor already assigned to another continuation")
                        else:
                            write_new(target, claim)
                with self.lock():
                    if (self.root / "batch.json").exists():
                        raise GateError("Started batch cannot be resumed or retried")
                    start = self.clock()
                    if not math.isfinite(start):
                        raise GateError("Invalid clock")
                    validate_permit(self.permit, self.verify_inputs(), start)
                    write_new(self.root / "batch.json", {"started_at": start,
                        "deadline": min(start + 7200, self.permit["expires_at"]),
                        "permit_sha256": self.permit_digest, "permit": self.permit})
                self.started_mono = self.monotonic()
                self.last_wall = start
                self.active = True
                yield self
            finally:
                self.active = False
                fcntl.flock(stream, fcntl.LOCK_UN)

    def check_time(self):
        if not self.active or (self.root / "STOP.json").exists():
            raise GateError("Batch not active or terminal stop")
        now, elapsed = self.clock(), self.monotonic() - self.started_mono
        batch = json.loads((self.root / "batch.json").read_text())
        if not math.isfinite(now) or not math.isfinite(elapsed) or now < self.last_wall or elapsed < 0 or elapsed >= 7200 or now >= batch["deadline"]:
            self.stop("clock_or_deadline")
            raise GateError("Clock/deadline invalid")
        self.last_wall = now
        if canonical_hash(self.permit) != self.permit_digest:
            raise GateError("Permit changed")
        if canonical_hash(self.turns) != self.turns_digest:
            raise GateError("Frozen turn identities changed")
        validate_permit(self.permit, self.verify_inputs(), now)

    def stop(self, reason):
        try:
            write_new(self.root / "STOP.json", {"reason": reason, "retry": False})
        except FileExistsError:
            pass

    def records(self):
        return [json.loads(path.read_text()) for path in sorted(self.root.glob("send-[0-9][0-9][0-9].json"))]

    def reserve(self, request, turn):
        self.check_time()
        body = request.data
        if request.full_url != ENDPOINT or request.get_method() != "POST" or not isinstance(body, bytes) or len(body) > 65536:
            raise GateError("Endpoint/body mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise GateError("Invalid request JSON") from exc
        expected = {"model": "deepseek-flash", "thinking": {"type": "enabled"},
                    "reasoning_effort": "high", "max_tokens": 8192}
        if any(type(payload.get(key)) is not type(value) or payload[key] != value for key, value in expected.items()):
            raise GateError("Frozen model configuration changed")
        if set(payload) - {"model", "messages", "tools", "tool_choice", "temperature", "max_tokens", "thinking", "reasoning_effort"}:
            raise GateError("Unfrozen model request field")
        if payload.get("temperature") != self.permit.get("temperature", 0):
            raise GateError("Frozen temperature changed")
        if any(not isinstance(turn.get(key), str) or not turn[key].isalnum()
               for key in ("case_id", "request_id", "session_id")):
            raise GateError("Missing frozen turn identity")
        frozen = next((item for item in self.turns if item.get("case_id") == turn["case_id"]), None)
        if frozen is None or any(frozen.get(key) != turn[key] for key in ("request_id", "session_id")):
            raise GateError("Turn not in frozen batch")
        with self.lock():
            self.check_time()
            records = self.records()
            if self.consumed_requests + len(records) >= 48:
                raise GateError("Request limit exhausted")
            if sum(record["case_id"] == turn["case_id"] for record in records) >= 6:
                raise GateError("Per-turn request limit exhausted")
            if any(not (self.root / (record["id"] + "-settled.json")).exists() for record in records):
                raise GateError("Outstanding reservation; no further send")
            amount = (Decimal(INPUT_BOUND) * Decimal(self.permit["input_price_per_million"]) + Decimal(self.output_bound) * Decimal(self.permit["output_price_per_million"])) / Decimal(1000000)
            total = self.consumed_cost + sum((Decimal(json.loads((self.root / (record["id"] + "-settled.json")).read_text())["estimated_cost"]) for record in records), Decimal(0))
            if total + amount > Decimal(self.permit["budget"]):
                raise GateError("Insufficient remaining planning budget")
            number = len(records) + 1
            record_id = f"send-{number:03d}"
            # Only one reservation namespace; settled/received names do not
            # match send-[0-9][0-9][0-9].json when rereading.
            write_new(self.root / (record_id + ".json"), {"id": record_id, "number": number,
                "cumulative_number": self.consumed_requests + number,
                "case_id": turn["case_id"], "request_id": turn["request_id"], "session_id": turn["session_id"],
                "attempt": sum(record["case_id"] == turn["case_id"] for record in records) + 1,
                "reserved_cost": str(amount), "currency": self.permit["currency"], "output_bound": self.output_bound,
                "body_bytes": len(body), "body_sha256": hashlib.sha256(body).hexdigest(),
                "permit_sha256": self.permit_digest, "billing": "not_verified"})
            return record_id


class AccountedOpener:
    def __init__(self, ledger, turn, *, transport=official_transport):
        self.ledger, self.turn, self.transport = ledger, dict(turn), transport
        self.pending = None
        self.received = None
        self.count = 0

    def __call__(self, request, *, timeout):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 90:
            raise GateError("Invalid timeout")
        if self.pending is not None:
            raise GateError("Unsettled request")
        self.pending = self.ledger.reserve(request, self.turn)
        root = self.ledger.root
        write_new(root / (self.pending + "-dispatched.json"), {"status": "outcome_unknown"})
        self.count += 1
        try:
            with self.transport(request, timeout=timeout) as response:
                if hasattr(response, "geturl") and response.geturl() != ENDPOINT:
                    raise GateError("Unexpected response URL")
                if getattr(response, "status", 200) != 200:
                    raise GateError("Non-success HTTP response")
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise GateError("Response exceeds evidence limit")
            try:
                body = json.loads(raw)
                message = body["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise ValueError("Invalid model message")
                public = {key: message[key] for key in ("role", "content", "tool_calls") if key in message}
                usage = body.get("usage")
                if isinstance(usage, dict):
                    usage = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                             "prompt_cache_hit_tokens", "prompt_cache_miss_tokens") if key in usage}
                evidence = {"model_response": True, "model": body.get("model"),
                            "message": public, "usage": usage}
            except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
                evidence = {"model_response": False, "protocol": "unknown", "bytes": len(raw),
                            "body_sha256": hashlib.sha256(raw).hexdigest()}
            write_new(root / (self.pending + "-received.json"), evidence)
            self.received = evidence
            return io.BytesIO(raw)
        except Exception:
            self.fail("http_or_transport_failure")
            raise

    def settle(self):
        evidence = self.received or {}
        usage = evidence.get("usage")
        if not self.pending or not evidence.get("model_response") or not isinstance(usage, dict):
            self.fail("usage_unknown")
            raise GateError("Model response/usage unknown")
        inputs, outputs = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if any(type(value) is not int or value < 0 for value in (inputs, outputs)) or inputs > INPUT_BOUND or outputs > self.ledger.output_bound or (
                "total_tokens" in usage and (type(usage["total_tokens"]) is not int or usage["total_tokens"] != inputs + outputs)):
            self.fail("usage_inconsistent_or_out_of_bound")
            raise GateError("Usage inconsistent/out of bound")
        cost = (Decimal(inputs) * Decimal(self.ledger.permit["input_price_per_million"]) + Decimal(outputs) * Decimal(self.ledger.permit["output_price_per_million"])) / Decimal(1000000)
        with self.ledger.lock():
            write_new(self.ledger.root / (self.pending + "-settled.json"), {
                "id": self.pending, "estimated_cost": str(cost), "currency": self.ledger.permit["currency"],
                "prompt_tokens": inputs, "completion_tokens": outputs,
                "billing": "not_verified", "basis": "reported_usage_peak_uncached_price"})
        self.pending, self.received = None, None

    def fail(self, reason):
        if self.pending is not None:
            self.ledger.stop(reason)

    def accounting_complete(self):
        return self.pending is None and not (self.ledger.root / "STOP.json").exists()
