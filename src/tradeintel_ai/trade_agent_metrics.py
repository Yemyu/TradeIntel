"""Allowlisted provider usage; unknown values are never replaced with zero."""
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")


def request_configuration(model):
    """Read only explicitly configured allowlisted fields, never credentials."""
    result = {}
    name = getattr(getattr(model, "config", None), "model", None)
    if isinstance(name, str) and 0 < len(name) <= 120:
        result["requested_model"] = name
    params = getattr(model, "request_params", None)
    if isinstance(params, dict):
        if isinstance(params.get("reasoning_effort"), str) and params["reasoning_effort"] in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            result["reasoning_effort"] = params["reasoning_effort"]
        thinking = params.get("thinking")
        if isinstance(thinking, dict) and isinstance(thinking.get("type"), str) and thinking["type"] in {"enabled", "disabled"}:
            result["thinking"] = {"type": thinking["type"]}
    return result


def response_metrics(metadata, elapsed_ms):
    metadata = metadata if isinstance(metadata, dict) else {}
    result = {"elapsed_ms": elapsed_ms, "usage": {}, "usage_status": "unknown"}
    for key in ("model", "requested_model", "finish_reason"):
        value = metadata.get(key)
        if isinstance(value, str) and len(value) <= 120:
            result[key] = value
    usage = metadata.get("usage")
    if isinstance(usage, dict):
        for key in TOKEN_FIELDS:
            value = usage.get(key)
            if type(value) is int and 0 <= value <= 1_000_000_000:
                result["usage"][key] = value
        if result["usage"]:
            result["usage_status"] = "reported" if all(key in result["usage"] for key in
                ("prompt_tokens", "completion_tokens", "total_tokens")) else "partial"
    return result


def summarize_metrics(metrics):
    events = metrics.get("attempts", [])
    responses = [event for event in events if event["status"] == "response_received"]
    totals = {key: {"reported_sum": sum(event.get("usage", {}).get(key, 0) for event in responses),
                    "reporting_responses": sum(key in event.get("usage", {}) for event in responses)}
              for key in TOKEN_FIELDS}
    for value in totals.values():
        if not value["reporting_responses"]:
            value["reported_sum"] = None
    return {**metrics, "complete_attempts": len(events), "responses_received": len(responses),
            "token_totals": totals, "cost_status": "unknown",
            "boundary": "应用调用尝试数，不代表已核验的收费次数；仅汇总供应商返回用量。"}
