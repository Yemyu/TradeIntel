"""Small local web application for the bounded TradeShock AI demonstration.

The page deliberately exposes a narrow, registered case rather than pretending
to be a general trade-policy portal.  Deterministic exposure queries are
available with GET requests.  The model-backed demo is a separate POST route
and is only executed after an explicit button click in the browser.

This module uses the standard library only.  API credentials stay in the
project-local configuration and are never included in HTTP responses or
request logs.
"""

from __future__ import annotations

import csv
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse

from .local_provider_config import load_config
from .model_adapter import ModelAdapterError
from .policy_exposure_tools import (
    EXPOSURE_END,
    EXPOSURE_START,
    HTS8_PATTERN,
    POLICY_EXPOSURE_ID,
    get_policy_exposure_series,
)
from .policy_exposure_workflow import run_exposure_demo
from .repository import EvidenceRepository, RepositoryError, default_paths
from .research_models import ResearchPlannerModel
from .tools import ToolError
from .exposure_version_store import ExposureVersionStore, VersionStoreError, pin_repository


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8765
DEFAULT_OUTPUT_ROOT_NAME = "tmp/unified-research"
RUN_ID_PATTERN = re.compile(r"^exposure-[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")
CASES = {
    "may-tungsten": {
        "label": "2026 年 5 月 · 单税号",
        "description": "查询 81019910 的当月金额、中国份额和后续调查方向。",
    },
    "june-tungsten": {
        "label": "2026 年 6 月 · 单税号",
        "description": "保留的格式失败案例；可用来观察失败如何被保留。",
    },
    "july-scope": {
        "label": "2026 年 7 月 · 五税号整体",
        "description": "查询登记政策五个 HTS8 的整体金额、中国金额和份额。",
    },
}

POLICY_SOURCE_CARDS = (
    {
        "label": "USTR 公告（2024-12-11）",
        "kind": "政策公告",
        "url": "https://ustr.gov/about-us/policy-offices/press-office/press-releases/2024/december/ustr-increases-tariffs-under-section-301-tungsten-products-wafers-and-polysilicon-concluding",
        "description": "说明四年审查后的关税调整背景。",
    },
    {
        "label": "Federal Register（2024-12-16）",
        "kind": "法律出版",
        "url": "https://www.federalregister.gov/documents/2024/12/16/2024-29462/notice-of-modification-chinas-acts-policies-and-practices-related-to-technology-transfer",
        "description": "登记政策范围、税率与正式出版日期。",
    },
    {
        "label": "CBP 执行指引（2024-12-31）",
        "kind": "执行指引",
        "url": "https://content.govdelivery.com/accounts/USDHSCBP/bulletins/3ca1cf1",
        "description": "确认五个税号及 2025-01-01 生效安排。",
    },
    {
        "label": "USITC 2026-07 编码变更表",
        "kind": "编码连续性",
        "url": "https://www.usitc.gov/tariff_affairs/documents/list_of_committee_changes_for_july_1_2026-final.pdf",
        "description": "说明 3818000095 拆分为后续统计编码，避免把拆码误当增长。",
    },
)


class WebRequestError(ValueError):
    """A safe validation error returned as HTTP 400."""


class DemoBusyError(RuntimeError):
    """The same model-backed demo is already running."""


def _month_label(key: tuple[int, int]) -> str:
    return f"{key[0]:04d}-{key[1]:02d}"


def _configured_root(root: Path | None = None) -> Path:
    return (root or default_paths().root).resolve()


def _query_one(query: Mapping[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name, [])
    if len(values) > 1:
        raise WebRequestError(f"参数 {name} 只能出现一次")
    return values[0].strip() if values else default


def validate_exposure_params(
    query: Mapping[str, list[str]], *, root: Path | None = None
) -> dict[str, str | None]:
    """Validate browser query parameters without broadening the registered scope."""

    origin = _query_one(query, "origin", "China")
    if origin not in {"China", "other_origins", "all_origins"}:
        raise WebRequestError("origin 只能是 China、other_origins 或 all_origins")
    start = _query_one(query, "start", _month_label(EXPOSURE_START))
    end = _query_one(query, "end", _month_label(EXPOSURE_END))
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", start) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", end):
        raise WebRequestError("start 和 end 必须使用 YYYY-MM 格式")
    start_key = (int(start[:4]), int(start[5:]))
    end_key = (int(end[:4]), int(end[5:]))
    if not 1 <= start_key[1] <= 12 or not 1 <= end_key[1] <= 12:
        raise WebRequestError("月份必须位于 01 至 12")
    if start_key < EXPOSURE_START or end_key > EXPOSURE_END:
        raise WebRequestError(
            f"当前页面只支持已验证窗口 {_month_label(EXPOSURE_START)} 至 {_month_label(EXPOSURE_END)}"
        )
    if start_key > end_key:
        raise WebRequestError("start 不能晚于 end")
    hts8 = _query_one(query, "hts8", "") or None
    if hts8 is not None:
        hts8 = hts8.replace(".", "")
        if not HTS8_PATTERN.fullmatch(hts8):
            raise WebRequestError("hts8 必须是八位数字税号")
        # The function below is the source of truth for membership.  This
        # local check gives the page a clear error before reading monthly data.
        products_path = _configured_root(root) / "data/processed/policy/section301_review2025_products.csv"
        if products_path.exists():
            with products_path.open(newline="", encoding="utf-8") as handle:
                registered = {
                    row.get("canonical_hts8", "").replace(".", "").strip()
                    for row in csv.DictReader(handle)
                    if row.get("policy_id", "").strip() == POLICY_EXPOSURE_ID
                }
            if hts8 not in registered:
                raise WebRequestError("hts8 不在当前登记政策的五个税号中")
    return {"origin": origin, "start": start, "end": end, "hts8": hts8}


def _safe_error(exc: Exception) -> str:
    """Return a useful but non-sensitive message for an HTTP response."""

    if isinstance(exc, (WebRequestError, ToolError, RepositoryError, ModelAdapterError, ValueError)):
        message = str(exc).strip()
        # Paths and provider response bodies are not helpful in a browser and
        # can reveal local layout, so keep only the first safe sentence.
        if "api_key" in message.lower() or "secret" in message.lower():
            return "本地模型配置不完整；密钥只应保存在项目 .local 配置中。"
        return message[:300] or "请求无法完成"
    return "服务执行失败；本次运行记录已保留在本地，未生成成功报告。"


def _decode_json_object(raw: bytes) -> dict[str, Any]:
    """Decode the tiny POST contract and reject duplicate top-level keys."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise WebRequestError("请求对象不能包含重复字段")
            result[key] = value
        return result

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebRequestError("请求体必须是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise WebRequestError("请求必须是 JSON 对象")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryError("登记政策元数据无法读取") from exc
    if not isinstance(value, dict):
        raise RepositoryError("登记政策元数据必须是对象")
    return value


def policy_payload(repository: EvidenceRepository | None = None) -> dict[str, Any]:
    """Build a small public-safe description of the registered policy."""

    repository = repository or EvidenceRepository()
    repository = pin_repository(repository)
    root = repository.paths.root
    event_path = root / "data/processed/policy/section301_review2025_event.csv"
    products_path = root / "data/processed/policy/section301_review2025_products.csv"
    manifest_path = root / "data/processed/policy_exposure/manifest.json"
    correction_path = manifest_path.parent / "policy_metadata_corrections.json"
    if not event_path.exists() or not products_path.exists() or not manifest_path.exists():
        raise RepositoryError("登记政策资源不完整")
    with event_path.open(newline="", encoding="utf-8") as handle:
        events = list(csv.DictReader(handle))
    event = next((row for row in events if row.get("policy_id") == POLICY_EXPOSURE_ID), None)
    if event is None:
        raise RepositoryError("登记政策事件不存在")
    with products_path.open(newline="", encoding="utf-8") as handle:
        products = [
            row for row in csv.DictReader(handle)
            if row.get("policy_id", "").strip() == POLICY_EXPOSURE_ID
        ]
    correction = _read_json(correction_path) if correction_path.exists() else {}
    dates = correction.get("dates") if isinstance(correction.get("dates"), dict) else {
        "announcement_date": event.get("announcement_date", ""),
        "federal_register_publication_date": event.get("announcement_date", ""),
        "cbp_guidance_publication_date": "",
        "effective_date": event.get("effective_date", ""),
    }
    correction_products = correction.get("products", {})
    public_products: list[dict[str, Any]] = []
    for row in sorted(products, key=lambda item: item.get("canonical_hts8", "")):
        code = row.get("canonical_hts8", "").replace(".", "").strip()
        revised = correction_products.get(code, {}) if isinstance(correction_products, dict) else {}
        public_products.append({
            "hts8": code,
            "description_zh": revised.get("product_description_zh", row.get("product_description_zh", "")),
            "description": revised.get("product_description", row.get("product_description", "")),
            "additional_rate_percent": row.get("additional_rate_percent", ""),
            "effective_date": row.get("effective_date", ""),
        })
    manifest = _read_json(manifest_path)
    months = manifest.get("months", [])
    snapshot = getattr(repository, 'exposure_snapshot', None)
    if snapshot:
        months = [m for m in months if f"{int(m['year']):04d}-{int(m['month']):02d}" in snapshot['months']]
    manifest_labels = sorted(
        f"{int(item['year']):04d}-{int(item['month']):02d}"
        for item in months
        if isinstance(item, dict) and "year" in item and "month" in item
    )
    window_start = manifest_labels[0] if manifest_labels else _month_label(EXPOSURE_START)
    window_end = manifest_labels[-1] if manifest_labels else _month_label(EXPOSURE_END)
    return {
        "policy_id": POLICY_EXPOSURE_ID,
        "data_version": getattr(repository, 'exposure_version', None),
        "policy_name": event.get("policy_name", ""),
        "target_origin": event.get("target_origin", ""),
        "dates": dates,
        "scope_note": event.get("scope_note", ""),
        "products": public_products,
        "data_window": {
            "start": window_start,
            "end": window_end,
            "months": len(months),
            "raw_archives_retained": bool(manifest.get("raw_archive_retention")),
        },
        "sources": list(POLICY_SOURCE_CARDS),
        "limitations": [
            "页面只覆盖登记政策的五个精确 HTS8，不是完整现行税则。",
            "金额是美国消费进口的描述性暴露，不是损失、出口依赖或政策因果效果。",
            "统计窗口截至 2026-07；页面不会把尚未发布月份补成零。",
        ],
    }


def health_payload() -> dict[str, Any]:
    """Expose model readiness without exposing endpoint details or keys."""

    try:
        config = load_config()
    except Exception as exc:  # configuration errors are user-facing status, not crashes
        return {
            "status": "not_configured",
            "model": None,
            "api_key_configured": False,
            "message": _safe_error(exc),
        }
    return {
        "status": "ready" if bool(config.api_key) else "missing_api_key",
        "model": config.model,
        "api_key_configured": bool(config.api_key),
        "message": "真实模型演示可在点击后运行。" if config.api_key else "未配置本地模型密钥；确定性查询仍可使用。",
    }


def update_payload(root: Path | None = None) -> dict[str, Any]:
    """Return the local version pointer and latest accepted difference."""

    project_root = _configured_root(root)
    try:
        store = ExposureVersionStore(project_root)
        payload = store.status()
        if payload['active_version']:
            store.release_root(payload['active_version'])
        payload['release_verified'] = bool(payload['active_version'])
        public_fields = (
            "version",
            "status",
            "before_version",
            "requires_review",
            "ready_for_activation",
            "created_at_utc",
            "activated_at_utc",
            "difference",
        )

        def public_record(record: Any) -> dict[str, Any] | None:
            if not isinstance(record, Mapping):
                return None
            return {key: record[key] for key in public_fields if key in record}

        payload["active"] = public_record(payload.get("active"))
        public_candidates: list[dict[str, Any]] = []
        for record in payload.get("candidates", []):
            safe_record = public_record(record)
            if safe_record is not None:
                public_candidates.append(safe_record)
        payload["candidates"] = public_candidates
        return payload
    except VersionStoreError as exc:
        return {"status": "error", "message": str(exc)}


def version_bound_exposure(repository: EvidenceRepository, **params: Any) -> dict[str, Any]:
    """Read a single verified release, even if the active pointer changes."""
    repository = pin_repository(repository)
    result = get_policy_exposure_series(repository=repository, **params)
    pin_repository(repository)
    result['data_version'] = getattr(repository, 'exposure_version', None)
    result['version_binding'] = 'release_copy' if result['data_version'] else 'unregistered'
    return result


def safe_report_path(output_root: Path, run_id: str) -> Path:
    """Resolve only a generated report, never an arbitrary browser path."""

    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise WebRequestError("运行编号格式无效")
    root = output_root.resolve()
    report = (root / run_id / "report.zh-CN.md").resolve()
    try:
        report.relative_to(root)
    except ValueError as exc:
        raise WebRequestError("报告路径不在本地运行目录内") from exc
    if not report.is_file():
        raise FileNotFoundError("报告尚未生成或运行失败")
    return report


class DemoCoordinator:
    """Prevent duplicate same-case model calls while allowing other requests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set[str] = set()

    def structured(self, task, *, repository, output_root):
        from .structured_task import compile_task
        from .policy_cases import resolve_case
        from .business_workflow import run_business_question
        from .research_models import JsonResearchModel
        from dataclasses import replace
        try:
            question, _ = compile_task(task)
        except (ValueError, TypeError) as exc:
            raise WebRequestError('结构化任务参数无效') from exc
        case = resolve_case(task['policy_id'], require_enabled=False)
        if case.status != 'enabled':
            return {'status':'not_available','model_calls':0,'policy_id':case.policy_id,
                    'message':'此案例尚未开放在线研究。可先查看固定真实结果；没有调用模型。'}
        if not case.start <= task['month'] <= case.end:
            raise WebRequestError('月份超出登记数据窗口')
        # Validate the published copy before loading credentials or requesting AI.
        repo = pin_repository(repository, policy_id=case.policy_id)
        snapshot = getattr(repo,'exposure_snapshot',None)
        if not snapshot or not snapshot['start'] <= task['month'] <= snapshot['end']:
            raise WebRequestError('月份不在已发布数据窗口内')
        with self._lock:
            if 'business-question' in self._running:
                raise DemoBusyError('研究任务正在处理，请等待完成')
            self._running.add('business-question')
        try:
            config = replace(load_config(),timeout_seconds=180.0,temperature=0.0)
            if not config.api_key: raise ModelAdapterError('未配置本地模型密钥')
            class Once(JsonResearchModel):
                max_output_tokens=3072
                calls=0
                def complete(self, **kwargs):
                    if self.calls: raise ModelAdapterError('单次解释预算已用尽')
                    self.calls+=1
                    return super().complete(**kwargs)
            run_id='exposure-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
            result=run_business_question(Once(config),question,output_root/run_id,
                repository=repo,secret=config.api_key,policy_id=case.policy_id,
                interpretation_mode=True,structured_task=task)
            from .interpretation_review_store import FILES
            from .research_data_link import research_data_link
            review_available = result.get('status') == 'interpretation_needs_review' and all(
                (output_root/run_id/name).is_file() for name in FILES)
            return {**result,'run_id':run_id,
                'data_report':research_data_link(repository.paths.root,output_root/run_id),
                'review_url':f'/review/interpretation?run_id={run_id}' if review_available else None,
                'artifacts':[
                {'label':label,'url':f'/api/research-artifact/{run_id}/{name}'}
                for name,label in [('source-packet.zh-CN.md','程序来源资料'),
                                   ('interpretation-pending.zh-CN.md','AI待审阅附件')]
                if (output_root/run_id/name).is_file()]}
        finally:
            with self._lock: self._running.discard('business-question')

    def ask(self, question, *, repository, output_root, policy_id=None):
        from .business_workflow import run_business_question
        from .business_case_selection import select_business_case
        from dataclasses import replace
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise WebRequestError('问题需为1至2000字')
        with self._lock:
            if 'business-question' in self._running:
                raise DemoBusyError('研究问题正在处理，请等待完成')
            self._running.add('business-question')
        try:
            _, selection_status, _ = select_business_case(question, policy_id)
            config = None
            model = None
            class QuestionModel(ResearchPlannerModel):
                max_output_tokens = 2048
            if not selection_status:
                config = load_config()
                if not config.api_key:
                    raise ModelAdapterError('未配置本地模型密钥')
                config = replace(config, timeout_seconds=180.0)
                model = QuestionModel(config)
            run_id = 'exposure-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
            result = run_business_question(model, question, output_root / run_id,
                                          repository=repository, secret=config.api_key if config else '',
                                          policy_id=policy_id)
            available = result['status'] == 'draft_needs_review'
            from .research_data_link import research_data_link
            return {**result, 'run_id': run_id, 'report_available': available,
                    'data_report':research_data_link(repository.paths.root,output_root/run_id),
                    'report_url': f'/api/report/{run_id}' if available else None}
        finally:
            with self._lock:
                self._running.discard('business-question')

    def run(
        self,
        case: str,
        *,
        repository: EvidenceRepository,
        output_root: Path,
    ) -> dict[str, Any]:
        if case not in CASES:
            raise WebRequestError("未知的 AI 演示案例")
        with self._lock:
            if case in self._running:
                raise DemoBusyError("这个案例已经在运行；请等待当前运行结束。")
            self._running.add(case)
        run: Path | None = None
        try:
            config = load_config()
            if not config.api_key:
                raise ModelAdapterError("未配置本地模型密钥；没有调用模型")
            # Match the CLI's bounded timeout and generation class.  No retry
            # is added here: run_exposure_demo records the first failure.
            from dataclasses import replace

            config = replace(config, timeout_seconds=max(float(config.timeout_seconds), 180.0))

            class ExposureModel(ResearchPlannerModel):
                max_output_tokens = 4096

            output_root.mkdir(parents=True, exist_ok=True)
            run_id = "exposure-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
            run = output_root / run_id
            result = run_exposure_demo(
                ExposureModel(config),
                run,
                repository=repository,
                secret=config.api_key,
                case=case,
            )
            report = run / "report.zh-CN.md"
            delivered = result.get("status") == "draft_needs_review" and report.is_file()
            return {
                "status": "draft_needs_review" if delivered else "failed",
                "case": case,
                "run_id": run_id,
                "report_available": delivered,
                "report_url": f"/api/report/{run_id}" if delivered else None,
                "model": config.model,
                "model_calls": result.get("model_calls", 0),
                "message": (
                    "已生成受约束初稿；下载前仍需人工审阅。"
                    if delivered
                    else "模型演示未生成可交付报告；原始失败记录已保留。"
                ),
            }
        finally:
            with self._lock:
                self._running.discard(case)


class TradeIntelHandler(BaseHTTPRequestHandler):
    """HTTP adapter kept intentionally thin so business logic stays testable."""

    repository: EvidenceRepository
    output_root: Path
    coordinator: DemoCoordinator
    static_root: Path
    version_store: ExposureVersionStore

    server_version = "TradeIntelLocal/1.0"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Do not print query contents or model payloads into the terminal.
        return

    def _send_json(self, status: int | HTTPStatus, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int | HTTPStatus, body: str, content_type: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: int | HTTPStatus, exc: Exception) -> None:
        self._send_json(status, {"status": "error", "message": _safe_error(exc)})

    def _review_run(self, parsed):
        params = parse_qs(parsed.query, keep_blank_values=True)
        if not params:
            return self.repository.paths.root/'tmp/trade-aware-interpretation-v1-first/run'
        if set(params) != {'run_id'} or len(params['run_id']) != 1:
            raise ValueError('invalid review run selector')
        run_id = params['run_id'][0]
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError('invalid review run id')
        root = self.output_root.resolve()
        run = root/run_id
        if run.is_symlink() or not run.is_dir() or run.resolve().parent != root:
            raise ValueError('review run missing or unsafe')
        return run

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == '/api/saved-interpretation-review':
            from .interpretation_review_store import packet
            try:
                run=self._review_run(parsed)
                from .research_data_link import research_data_link
                self._send_json(HTTPStatus.OK,{**packet(run),
                    'data_report':research_data_link(self.repository.paths.root,run)})
            except (ValueError,OSError):
                self._error(HTTPStatus.CONFLICT,WebRequestError('审阅资料缺失或已变更'))
            return
        if parsed.path == '/api/saved-interpretation-draft':
            from .interpretation_review_store import reviewed_draft
            try:
                run=self._review_run(parsed)
                self._send_text(HTTPStatus.OK,reviewed_draft(run),'text/markdown; charset=utf-8')
            except (ValueError,OSError):
                self._error(HTTPStatus.CONFLICT,WebRequestError('审阅稿尚未具备导出条件，或审阅资料已变更'))
            return
        if parsed.path.startswith('/api/research-artifact/'):
            try:
                parts=parsed.path.split('/')
                if len(parts)!=5 or not RUN_ID_PATTERN.fullmatch(parts[3]) or parts[4] not in ('source-packet.zh-CN.md','interpretation-pending.zh-CN.md'):
                    raise WebRequestError('资料路径无效')
                root=self.output_root.resolve()
                path=(root/parts[3]/parts[4]).resolve()
                if not path.is_relative_to(root): raise WebRequestError('资料路径越界')
                self._send_text(HTTPStatus.OK,path.read_text(encoding='utf-8'),'text/plain; charset=utf-8')
            except (ValueError,WebRequestError):
                self._error(HTTPStatus.BAD_REQUEST,WebRequestError('资料路径无效'))
            except FileNotFoundError:
                self._error(HTTPStatus.NOT_FOUND,WebRequestError('资料尚未生成'))
            return
        try:
            if parsed.path == '/api/cases':
                from .policy_cases import public_case_catalog
                self._send_json(HTTPStatus.OK, public_case_catalog())
                return
            if parsed.path == "/api/health":
                self._send_json(HTTPStatus.OK, health_payload())
                return
            if parsed.path == "/api/policy":
                self._send_json(HTTPStatus.OK, policy_payload(self.repository))
                return
            if parsed.path == '/api/update-brief':
                from .update_brief import current_update_brief
                self._send_text(HTTPStatus.OK,current_update_brief(self.repository.paths.root,self.output_root),'text/plain; charset=utf-8')
                return
            if parsed.path == '/api/version-report':
                from .version_report import version_report
                query=parse_qs(parsed.query, keep_blank_values=True)
                if set(query)-{'version'} or ('version' in query and (len(query['version'])!=1 or not re.fullmatch(r'[0-9a-f]{64}',query['version'][0]))):
                    raise WebRequestError('数据版本参数无效')
                self._send_text(HTTPStatus.OK,version_report(self.repository.paths.root,query.get('version',[None])[0]),'text/html; charset=utf-8')
                return
            if parsed.path == "/api/update":
                self._send_json(HTTPStatus.OK, update_payload(self.repository.paths.root))
                return
            if parsed.path == "/api/exposure":
                repository = pin_repository(self.repository)
                params = validate_exposure_params(
                    parse_qs(parsed.query, keep_blank_values=True), root=repository.paths.root
                )
                result = version_bound_exposure(repository, **params)
                self._send_json(HTTPStatus.OK, result)
                return
            if parsed.path.startswith("/api/report/"):
                run_id = unquote(parsed.path[len("/api/report/"):])
                report = safe_report_path(self.output_root, run_id)
                self._send_text(HTTPStatus.OK, report.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")
                return
            if parsed.path in {"/", "/index.html"}:
                index = self.static_root / "index.html"
                if not index.is_file():
                    raise FileNotFoundError("页面文件不存在")
                self._send_text(HTTPStatus.OK, index.read_text(encoding="utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == '/demo/solar':
                demo = self.static_root / 'solar-demo.html'
                if not demo.is_file():
                    raise FileNotFoundError('只读示例尚未生成')
                self._send_text(HTTPStatus.OK, demo.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
                return
            if parsed.path == '/demo/research-review':
                review = self.static_root / 'research-review.html'
                if not review.is_file():
                    raise FileNotFoundError('研究审阅页面尚未生成')
                self._send_text(HTTPStatus.OK, review.read_text(encoding='utf-8'), 'text/html; charset=utf-8')
                return
            if parsed.path == '/review/interpretation':
                self._send_text(HTTPStatus.OK,(self.static_root/'interpretation-review.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
                return
            self._error(HTTPStatus.NOT_FOUND, WebRequestError("页面或接口不存在"))
        except WebRequestError as exc:
            self._error(HTTPStatus.BAD_REQUEST, exc)
        except FileNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, exc)
        except VersionStoreError as exc:
            self._send_json(HTTPStatus.CONFLICT, {"status": "error", "message": str(exc)})
        except (RepositoryError, ToolError, ValueError) as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc)
        except Exception as exc:  # keep the server alive for another request
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/ai-demo", "/api/research", "/api/research-structured", "/api/saved-interpretation-review"):
            self._error(HTTPStatus.NOT_FOUND, WebRequestError("页面或接口不存在"))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 16_384:
                raise WebRequestError("请求体过大")
            raw = self.rfile.read(length)
            payload = _decode_json_object(raw)
            if parsed.path == '/api/saved-interpretation-review':
                if self.headers.get('Origin') != 'http://'+self.headers.get('Host',''):
                    raise WebRequestError('审阅提交必须来自同源本地页面')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise WebRequestError('审阅必须为JSON')
                from .interpretation_review_store import submit
                result=submit(self._review_run(parsed),payload)
                self._send_json(HTTPStatus.OK,result)
                return
            if parsed.path == '/api/research-structured':
                origin=self.headers.get('Origin')
                if origin and origin != 'http://'+self.headers.get('Host',''):
                    raise WebRequestError('只允许本地页面提交任务')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise WebRequestError('请求必须为application/json')
                result=self.coordinator.structured(payload,repository=self.repository,output_root=self.output_root)
                self._send_json(HTTPStatus.BAD_GATEWAY if result['status']=='failed' else HTTPStatus.OK,result)
                return
            if parsed.path == '/api/research':
                origin = self.headers.get('Origin')
                if origin and origin != 'http://' + self.headers.get('Host', ''):
                    raise WebRequestError('只允许本地页面提交问题')
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise WebRequestError('请求必须为application/json')
                if set(payload) not in ({'question'}, {'question', 'policy_id'}):
                    raise WebRequestError('请求只能包含question及可选policy_id')
                selected = payload.get('policy_id')
                if selected is not None and not isinstance(selected, str):
                    raise WebRequestError('policy_id必须为字符串或null')
                result = self.coordinator.ask(payload['question'], repository=self.repository,
                                              output_root=self.output_root, policy_id=selected)
                self._send_json(HTTPStatus.BAD_GATEWAY if result['status'] == 'failed' else HTTPStatus.OK, result)
                return
            if not isinstance(payload, dict) or set(payload) != {"case"} or not isinstance(payload["case"], str):
                raise WebRequestError("请求必须是 {case: ...} 对象")
            result = self.coordinator.run(
                payload["case"], repository=self.repository, output_root=self.output_root
            )
            self._send_json(HTTPStatus.OK if result["status"] != "failed" else HTTPStatus.BAD_GATEWAY, result)
        except DemoBusyError as exc:
            self._error(HTTPStatus.CONFLICT, exc)
        except WebRequestError as exc:
            self._error(HTTPStatus.BAD_REQUEST, exc)
        except (ModelAdapterError, ValueError) as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, exc)
        except Exception as exc:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, exc)


def create_server(
    *,
    root: Path | None = None,
    host: str = DEFAULT_WEB_HOST,
    port: int = DEFAULT_WEB_PORT,
    output_root: Path | None = None,
) -> ThreadingHTTPServer:
    """Create a configured local server; useful for the CLI and offline tests."""

    project_root = _configured_root(root)
    repository = EvidenceRepository()
    # EvidenceRepository resolves the package checkout by default.  Tests can
    # provide an alternate root without changing global process state.
    if root is not None:
        from .repository import DataPaths

        repository = EvidenceRepository(DataPaths(project_root))
    target_output = (output_root or project_root / DEFAULT_OUTPUT_ROOT_NAME).resolve()
    static_root = project_root / "web"

    class ConfiguredHandler(TradeIntelHandler):
        pass

    ConfiguredHandler.repository = repository
    ConfiguredHandler.output_root = target_output
    ConfiguredHandler.coordinator = DemoCoordinator()
    ConfiguredHandler.static_root = static_root
    ConfiguredHandler.version_store = ExposureVersionStore(project_root)
    return ThreadingHTTPServer((host, port), ConfiguredHandler)


__all__ = [
    "CASES",
    "DEFAULT_WEB_HOST",
    "DEFAULT_WEB_PORT",
    "DemoBusyError",
    "DemoCoordinator",
    "TradeIntelHandler",
    "create_server",
    "health_payload",
    "policy_payload",
    "safe_report_path",
    "update_payload",
    "validate_exposure_params",
]
