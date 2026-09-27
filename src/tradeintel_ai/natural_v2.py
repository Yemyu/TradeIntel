"""Natural-language preview/confirm boundary for the v2 monthly exposure task.

This module deliberately stops at a validated request preview.  It does not
read trade data or call the report generator until the caller presents the
single-use confirmation token.  The web layer can therefore show the user
exactly which registered case, month, product and focus will be used.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Mapping

from .agent import _normalise_response
from .policy_cases import resolve_case
from .response_contract import parse_json_response
from .structured_task import compile_task
from .exposure_version_store import pin_repository


SCHEMA_VERSION = "research-request-v2"
VALID_FOCUSES = {"china_amount", "china_share", "contrast"}
LATEST = 'latest_available'
LATEST_PHRASE = r'最新可用(?:的)?(?:贸易)?(?:数据|月份)|latest\s+available\s+(?:data|month)'
SAFE_LIMIT = r'(?:不要|不做|不进行|无需|不需要)\s*(?:预测|因果分析|因果推断)(?=$|[，。；、\s]|也|和)'
CASE_PRODUCTS = {
    "us_301_review2025_tungsten_solar": {
        "28046100", "38180000", "81019400", "81019910", "81019980"
    },
    "us_301_solar2024": {"85414200", "85414300"},
}

SYSTEM_PROMPT = """你是 TradeShock AI 的任务解析器，不是执行器。
只把用户问题解析为一个登记政策单月贸易结构解读任务，绝不查询数据、写报告或调用工具。
仅允许以下JSON对象，不能有额外字段：
{"status":"proposal","request":{"schema_version":"research-request-v2","policy_id":"...","month":"YYYY-MM","product":"八位HTS8或all","focus":"china_amount|china_share|contrast","policy_view":"archived_event"},"evidence":{"policy_id":"用户原话片段","month":"用户原话片段","product":"用户原话片段","focus":"用户原话片段"},"missing":[]}
如果政策、月份、商品范围或关注角度无法从用户问题确定，返回
{"status":"clarify","request":null,"evidence":{},"missing":["字段名"]}。
policy_id必须是已登记的精确ID；不要把未登记政策替换成默认案例。
month为明确的统计月份；用户明确说“最新可用数据/月份”时必须输出latest_available，由程序查发布快照决定实际月份，不得自行填日期。product为明确八位HTS8，或用户明确说全部/整体登记商品时为all。
china_amount表示比较中国原产金额，china_share表示比较中国占该商品美国全部来源进口的比例，contrast表示同时比较两者。
policy_view固定为archived_event，表示使用项目登记的历史政策事件，不代表现行税则。
evidence四个字段都必须逐字摘自用户问题；不要编造引文，不要把模型自己的字段名当作引文。
当前只支持一个月份、一个税号或全部登记税号。多月和商品排除要求必须澄清。“不要预测”“不做因果分析”是允许的限制，保留原问题并完成其余合法任务。
"""


def messages(question: str, capabilities: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    """Build the one planning request; no user-controlled instructions are mixed into the system rule."""

    context = {"schema_version": SCHEMA_VERSION, "registered_cases": sorted(CASE_PRODUCTS)}
    if capabilities:
        context["capabilities"] = dict(capabilities)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(
            {"question": question, "task_boundary": context},
            ensure_ascii=False,
        )},
    ]


def _month_in_question(month: str, question: str) -> bool:
    year, number = month.split("-", 1)
    return month in question or bool(re.search(
        rf"{year}\s*年\s*0?{int(number)}\s*月", question
    ))


def _contains_quote(quote: object, question: str) -> bool:
    return isinstance(quote, str) and bool(quote.strip()) and quote in question


def scope_clarification(question: str) -> str | None:
    """Conservative host guard, not a general natural-language understanding claim.

    Reject recognizable constraints the fixed single-month schema cannot
    represent. False positives request clarification, never execute a subset.
    """
    # Remove only explicit, bounded restrictions from this screening copy;
    # the complete original question still goes to the model and audit.
    screened = re.sub(SAFE_LIMIT, '', question)
    latest = bool(re.search(LATEST_PHRASE, screened, re.I))
    explicit_month = bool(re.search(r'\d{4}-(?:0[1-9]|1[0-2])|\d{1,2}\s*月', screened))
    if latest and explicit_month:
        return '同时出现明确月份和最新可用数据，请选择其中一种统计时间。'
    screened = re.sub(LATEST_PHRASE, '', screened, flags=re.I)
    if re.search(r'因果|预测|现行.*税率|现在.*税率|总税率|综合税率', screened):
        return '当前任务支持存档政策与单月贸易结构，不支持因果、预测或现行综合税率，请明确要分析的数据范围。'
    if re.search(r'最新|最近|当前|本月|上月|今年|去年|latest|current|last\s+month', screened, re.I):
        return '当前入口需要明确统计月份，尚不自动解释“最新/最近”。请指定YYYY-MM；不能把旧数据当成今天的数据。'
    if re.search(r'排除|不含|不包括|除外|除了|不要|不看|别看|仅限以外|而不是|不是|exclude|except|without|\bnot\b', screened, re.I):
        return '检测到排除或否定条件，当前任务格式无法可靠保留。请改写为明确要分析的一个税号和关注角度；不会忽略条件后执行。'
    months = set(re.findall(r'(?<!\d)(\d{4})-(0[1-9]|1[0-2])(?!\d)', question))
    months.update((year, f'{int(month):02d}') for year, month in
                  re.findall(r'(\d{4})\s*年\s*(0?[1-9]|1[0-2])\s*月', question))
    chinese_months = set(re.findall(r'(?<!\d)(0?[1-9]|1[0-2])\s*月', question))
    if (len(months) > 1 or len({int(m) for m in chinese_months}) > 1
            or re.search(r'同比|环比|逐月|每月|趋势|季度|全年|多月|个月|[至到~～—]\s*\d{1,2}\s*月|\d{1,2}\s*[、和及至到~-]\s*\d{1,2}\s*月', question)):
        return '当前入口只解读一个月的贸易结构，不能完成跨月或趋势比较。请指定一个月份，或保留原问题等待多月功能；不会只取其中一个月。'
    codes = set(re.findall(r'(?<!\d)\d{8}(?!\d)', question.replace('.', '')))
    if len(codes) > 1:
        return '当前入口支持一个税号或全部登记税号，暂不支持自选多个税号；不会把多个商品偷偷缩成一个。'
    return None


def validate_candidate(candidate: object, question: str) -> dict[str, Any] | None:
    """Validate a model proposal without deciding whether the repository can execute it.

    ``None`` means the model explicitly requested clarification; invalid
    shapes raise so callers can distinguish a bad model response from a user
    question that simply lacks a field.
    """

    if scope_clarification(question):
        raise ValueError('question contains unsupported scope constraints')
    if not isinstance(candidate, dict) or set(candidate) != {
        "status", "request", "evidence", "missing"
    }:
        raise ValueError("invalid research-request-v2 envelope")
    status = candidate["status"]
    if status == "clarify":
        if (candidate["request"] is not None or candidate["evidence"] != {}
                or not isinstance(candidate["missing"], list)
                or not candidate["missing"]
                or any(not isinstance(item, str) or not item.strip() or len(item) > 80
                       for item in candidate["missing"])):
            raise ValueError("invalid research-request-v2 clarification")
        return None
    if status != "proposal" or candidate["missing"] != []:
        raise ValueError("invalid research-request-v2 status")
    request = candidate["request"]
    if not isinstance(request, dict) or set(request) != {
        "schema_version", "policy_id", "month", "product", "focus", "policy_view"
    }:
        raise ValueError("invalid research-request-v2 request fields")
    if request["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported research-request-v2 schema")
    policy_id = request["policy_id"]
    if not isinstance(policy_id, str) or policy_id not in CASE_PRODUCTS:
        raise ValueError("unknown registered policy")
    month = request["month"]
    if not isinstance(month, str) or (month != LATEST and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month)):
        raise ValueError("invalid research month")
    product = request["product"]
    if not isinstance(product, str) or (product != "all" and product not in CASE_PRODUCTS[policy_id]):
        raise ValueError("unsupported registered product")
    focus = request["focus"]
    if not isinstance(focus, str) or focus not in VALID_FOCUSES:
        raise ValueError("unsupported research focus")
    if request["policy_view"] != "archived_event":
        raise ValueError("unsupported policy view")
    evidence = candidate["evidence"]
    fields = {"policy_id", "month", "product", "focus"}
    if not isinstance(evidence, dict) or set(evidence) != fields:
        raise ValueError("research-request-v2 evidence fields missing")
    if any(not _contains_quote(evidence[field], question) for field in fields):
        raise ValueError("research-request-v2 evidence is not a literal user quote")
    latest_requested = bool(re.search(LATEST_PHRASE, question, re.I))
    if (month == LATEST) != latest_requested:
        raise ValueError('latest month intent must be resolved by host')
    if month == LATEST and not re.search(LATEST_PHRASE, evidence['month'], re.I):
        raise ValueError('latest intent evidence missing')
    if month != LATEST and not _month_in_question(month, question):
        raise ValueError("research month is not explicit in the question")
    # The model must preserve a user-visible product scope.  A raw code is
    # checked literally; whole-scope language is checked by the quoted field.
    if product != "all" and product not in question.replace(".", ""):
        raise ValueError("research product is not explicit in the question")
    if product == 'all' and not re.search(r'全部|所有|整体|\ball\b', evidence['product'], re.I):
        raise ValueError('whole-product scope is not explicit in the quoted evidence')
    explicit_codes = set(re.findall(r'(?<!\d)\d{8}(?!\d)', question.replace('.', '')))
    if explicit_codes and product == 'all':
        raise ValueError('explicit product scope must not silently expand to all')
    return {"request": deepcopy(request), "evidence": deepcopy(evidence)}


def propose(question: str, model, *, repository=None) -> dict[str, Any]:
    """Make one bounded natural-language proposal; never execute the request."""

    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "needs_review",
        "model_calls": 0,
        "execution_attempted": False,
        "intent_verified": False,
    }
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        return {**base, "status": "needs_clarification",
                "response": "请用不超过2000字明确说明政策、月份、商品范围和关注金额/份额/对比。"}
    clarification = scope_clarification(question)
    if clarification:
        return {**base, 'status': 'needs_clarification',
                'missing': ['supported_scope'], 'response': clarification}
    base["model_calls"] = 1
    try:
        response = _normalise_response(model.complete(messages=messages(question), tools=[]))
        if response.tool_calls or response.metadata.get("finish_reason") != "stop":
            raise ValueError("planner response did not finish")
        candidate = parse_json_response(response.text)
        validated = validate_candidate(candidate, question)
    except Exception:
        return {**base, "status": "needs_review",
                "response": "任务解析未通过程序校验，尚未读取数据；请检查模型返回或改写问题。"}
    if validated is None:
        missing = candidate.get("missing", []) if isinstance(candidate, dict) else []
        return {**base, "status": "needs_clarification", "missing": missing,
                "response": "还不能确认本次单月研究的政策、月份、商品范围或关注角度；尚未执行。"}
    request, evidence = validated["request"], validated["evidence"]
    try:
        case = resolve_case(request["policy_id"], require_enabled=False)
        if case.status != "enabled":
            return {**base, "status": "not_available", "request": request,
                    "evidence": evidence,
                    "response": "该政策仍是候选案例，尚未开放在线研究；没有读取数据或调用解释模型。"}
        if repository is None:
            raise ValueError("repository required for a version-bound preview")
        repo = pin_repository(repository, policy_id=request["policy_id"])
        snapshot = getattr(repo, "exposure_snapshot", None)
        version = getattr(repo, "exposure_version", None)
        if not snapshot or not version:
            return {**base, "status": "not_available", "request": request,
                    "evidence": evidence,
                    "response": "当前政策没有可绑定的已发布数据版本，尚未执行。"}
        month_resolution = {'intent':request['month'], 'resolved_month':request['month'],
                            'data_version':version, 'source':'explicit_user_month'}
        if request['month'] == LATEST:
            request['month'] = snapshot['end']
            month_resolution.update(resolved_month=request['month'], source='published_snapshot.end')
        if not snapshot["start"] <= request["month"] <= snapshot["end"]:
            return {**base, "status": "outside_coverage", "request": request,
                    "evidence": evidence, "data_version": version,
                    "response": "所选月份不在当前已发布数据窗口内；没有自动改月份或执行。"}
        # Re-run the host-owned structured contract before handing out a token.
        compile_task({"policy_id": request["policy_id"], "month": request["month"],
                      "product": request["product"], "task": "monthly_exposure"})
    except Exception:
        return {**base, "status": "needs_review",
                "response": "登记政策或数据版本无法安全核对，尚未执行；没有回退到默认案例。"}
    preview = {
        **base,
        "status": "needs_confirmation",
        "request": request,
        "evidence": evidence,
        "data_version": version,
        "month_resolution": month_resolution,
        "confirmation_scope": "local_single_user_process",
        "response": (
            "以下是模型对问题的结构化理解，不是查询结果。请确认政策、月份、商品范围和关注角度；"
            "确认前不会读取贸易数据或调用解释模型。"
        ),
    }
    return preview


class NaturalV2Session:
    """Single-user in-process one-time confirmation storage."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] | None = None
        self._lock = threading.Lock()

    def preview(self, question: str, model, *, repository=None,
                audit_directory: Path | None = None, secret: str = "") -> dict[str, Any]:
        self._pending = None
        audit_reference = None
        if audit_directory is not None:
            from .host_review import _publish
            audit_directory.mkdir(parents=True, exist_ok=False)
            def save(name, value):
                # The provider configuration is never serialized; also redact
                # the configured credential if an upstream response echoes it.
                serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
                if secret:
                    serialized = serialized.replace(secret, '[REDACTED]')
                _publish(audit_directory / name, json.loads(serialized))
            save('request.json', {'question': question, 'messages': messages(question),
                                  'tools': [], 'max_calls': 1})
            class RecordedModel:
                def complete(self, **kwargs):
                    save('attempt.json', {'attempted_calls': 1})
                    try:
                        response = _normalise_response(model.complete(**kwargs))
                    except Exception as exc:
                        save('response.json', {'error_type': type(exc).__name__,
                                               'usage': None})
                        raise
                    save('response.json', {'response': asdict(response),
                                           'usage': response.metadata.get('usage')})
                    return response
            result = propose(question, RecordedModel(), repository=repository)
            save('outcome.json', result)
            audit_reference = {
                'directory': audit_directory.name,
                'files': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(audit_directory.glob('*.json'))},
            }
        else:
            result = propose(question, model, repository=repository)
        if result.get("status") != "needs_confirmation":
            return result
        token = secrets.token_urlsafe(24)
        request = deepcopy(result["request"])
        self._pending = {
            "token": token,
            "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            "question": question,
            "request": request,
            "data_version": result["data_version"],
            "policy_id": request["policy_id"],
            "planning_audit": audit_reference,
            "month_resolution": deepcopy(result['month_resolution']),
        }
        return {**result, "confirmation_token": token}

    def consume(self, token: object, *, repository=None) -> dict[str, Any]:
        with self._lock:
            pending = self._pending
            self._pending = None  # consume atomically before execution
        if pending is None or not isinstance(token, str) or token != pending["token"]:
            return {"status": "confirmation_rejected", "execution_attempted": False,
                    "response": "确认无效或已失效；请重新提交问题查看预览。"}
        try:
            if repository is None:
                raise ValueError("repository required")
            repo = pin_repository(repository, policy_id=pending["policy_id"])
            if getattr(repo, "exposure_version", None) != pending["data_version"]:
                return {"status": "confirmation_stale", "execution_attempted": False,
                        "response": "数据版本已变化；旧预览失效，请重新预览。"}
            snapshot = getattr(repo, "exposure_snapshot", None)
            request = pending["request"]
            if not snapshot or not snapshot["start"] <= request["month"] <= snapshot["end"]:
                return {"status": "confirmation_stale", "execution_attempted": False,
                        "response": "数据窗口已变化；旧预览失效，请重新预览。"}
            return {"status": "confirmed", "execution_attempted": False,
                    "request": deepcopy(request), "data_version": pending["data_version"],
                    "repository": repo, "original_question": pending['question'],
                    "month_resolution": deepcopy(pending['month_resolution']),
                    "planning_audit": deepcopy(pending['planning_audit'])}
        except Exception:
            return {"status": "confirmation_stale", "execution_attempted": False,
                    "response": "登记版本无法再次核对；旧预览失效，请重新预览。"}


__all__ = [
    "CASE_PRODUCTS", "SCHEMA_VERSION", "SYSTEM_PROMPT", "NaturalV2Session",
    "VALID_FOCUSES", "messages", "propose", "validate_candidate",
]
