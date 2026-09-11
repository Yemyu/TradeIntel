"""Offline diagnosis of a recorded model response using frozen intent rules."""
import json
from dataclasses import asdict
from .agent import _normalise_response
from .intent_proposal import _pairs, _constant, validate_candidate


class DiagnosticModel:
    """Capture normalized provider text before the parser can discard it.

    append must durably write events. Never pass these audit events back to a model.
    This wrapper is not yet installed in the archived live runner.
    """
    def __init__(self, model, append, *, api_key):
        self.model, self.append, self.api_key = model, append, api_key
        self.attempts = 0

    def record(self, event):
        text = json.dumps(event, ensure_ascii=False, allow_nan=False)
        if self.api_key:
            text = text.replace(self.api_key, '[REDACTED]')
        self.append(json.loads(text))

    def complete(self, *, messages, tools):
        if self.attempts or tools:
            raise ValueError('diagnostic wrapper accepts one tool-free request')
        self.attempts += 1
        self.record({'event': 'request_started', 'attempt': self.attempts})
        try:
            response = _normalise_response(self.model.complete(messages=messages, tools=[]))
        except BaseException:
            self.record({'event': 'request_failed', 'attempt': self.attempts})
            raise
        self.record({'event': 'response_recorded', 'response': asdict(response)})
        return response


def diagnose_response(question, raw_response):
    result = {'executed': False, 'semantic_correctness': None}
    try:
        response = _normalise_response(raw_response)
    except (TypeError, ValueError):
        return {**result, 'stage': 'response_contract'}
    if response.tool_calls:
        return {**result, 'stage': 'unexpected_tool_call'}
    if response.metadata.get('finish_reason') != 'stop':
        return {**result, 'stage': 'incomplete_response'}
    if len(response.text) > 24000:
        return {**result, 'stage': 'response_too_long'}
    if not response.text.strip():
        return {**result, 'stage': 'empty_text'}
    try:
        candidate = json.loads(response.text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        return {**result, 'stage': 'json_decode'}
    try:
        proposal = validate_candidate(candidate, question)
    except (TypeError, ValueError, KeyError):
        return {**result, 'stage': 'candidate_validation'}
    return {**result, 'stage': 'valid_proposal' if proposal else 'valid_clarification'}
