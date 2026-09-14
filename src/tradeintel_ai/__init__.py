"""Evidence-grounded TradeShock AI MVP."""

from .agent import ChatModel, MockModel, ModelResponse, ModelToolCall, ToolCallingAgent, enforce_causal_safety
from .model_adapter import (
    DEFAULT_BASE_URL,
    DEFAULT_SYSTEM_PROMPT,
    ModelAdapterError,
    OpenAICompatibleConfig,
    OpenAICompatibleModel,
)
from .repository import DataPaths, EvidenceRepository, RepositoryError
from .router import answer_question, classify_question
from .tools import (
    ToolError,
    ToolRegistry,
    build_evidence_bundle,
    default_registry,
    get_causal_readiness,
    get_data_quality_status,
    get_descriptive_change,
    get_policy_event,
    get_trade_series,
)
from .policy_exposure_tools import (
    POLICY_EXPOSURE_ID,
    PolicyExposureRegistry,
    get_policy_exposure_series,
)

__all__ = [
    "DataPaths",
    "EvidenceRepository",
    "RepositoryError",
    "ChatModel",
    "MockModel",
    "ModelResponse",
    "ModelToolCall",
    "ToolCallingAgent",
    "ToolError",
    "ToolRegistry",
    "answer_question",
    "build_evidence_bundle",
    "classify_question",
    "default_registry",
    "get_causal_readiness",
    "get_data_quality_status",
    "get_descriptive_change",
    "get_policy_event",
    "get_trade_series",
    "get_policy_exposure_series",
    "PolicyExposureRegistry",
    "POLICY_EXPOSURE_ID",
    "enforce_causal_safety",
    "DEFAULT_BASE_URL",
    "DEFAULT_SYSTEM_PROMPT",
    "ModelAdapterError",
    "OpenAICompatibleConfig",
    "OpenAICompatibleModel",
]
