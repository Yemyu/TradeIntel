"""Project-local provider settings, excluded from Git and never logged."""
import json
import os
from pathlib import Path
import stat
import re
import tempfile
import hashlib
from datetime import datetime, timezone

from .model_adapter import OpenAICompatibleConfig, ModelAdapterError

CONFIG_PATH = Path(__file__).resolve().parents[2] / '.local' / 'glm.json'
PRODUCT_CONFIG_PATH = Path(__file__).resolve().parents[2] / '.local' / 'product-model.json'
PRODUCT_PROVIDERS = {
    'glm': 'https://open.bigmodel.cn/api/paas/v4',
    'deepseek': 'https://api.deepseek.com',
    'qianwen': 'https://maas.qianwenaiapi.com/compatible-mode/v1',
}
PRODUCT_MODELS = {
    'glm': ('glm-4.7', 'glm-4.6v', 'glm-4.5-air'),
    'deepseek': ('deepseek-flash', 'deepseek-v4-pro'),
    'qianwen': (),
}
REASONING_LEVELS = {'default', 'none', 'low', 'high', 'max'}


def load_config(path=CONFIG_PATH):
    path = Path(path)
    if not path.exists():
        return OpenAICompatibleConfig.from_env()
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise ValueError('unsafe local config path')
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('local config must be readable only by its owner')
    settings = json.loads(path.read_text())
    # Environment overrides remain useful for explicit model changes.
    values = {**settings, **{k: v for k, v in os.environ.items() if k.startswith('TRADEINTEL_MODEL_')}}
    return OpenAICompatibleConfig.from_env(values)


def load_product_config():
    """Use the product's own key without changing frozen experiment settings."""
    if PRODUCT_CONFIG_PATH.exists():
        return load_config(PRODUCT_CONFIG_PATH)
    return load_config()


def _product_file() -> dict[str, str]:
    path = PRODUCT_CONFIG_PATH
    if not path.exists():
        return {}
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise ValueError('unsafe local config path')
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError('local config must be readable only by its owner')
    return json.loads(path.read_text(encoding='utf-8'))


def product_status() -> dict[str, object]:
    settings = _product_file()
    config = load_product_config()
    provider = next((name for name, base in PRODUCT_PROVIDERS.items()
                     if base.rstrip('/') == config.base_url.rstrip('/')), None)
    return {'configured': bool(config.api_key), 'provider': provider,
            'model': config.model, 'reasoning': settings.get('PRODUCT_REASONING', 'default'),
            'connection': settings.get('PRODUCT_CONNECTION', 'untested'),
            'checked_at': settings.get('PRODUCT_CHECKED_AT'),
            'models': {name: list(values) for name, values in PRODUCT_MODELS.items()}}


def _write_product_file(values: dict[str, str]) -> None:
    path = PRODUCT_CONFIG_PATH
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('unsafe config path')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.product-model-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def product_request_params(*, probe: bool = False) -> dict[str, object]:
    status = product_status()
    params: dict[str, object] = {'max_tokens': 256 if probe else 8192}
    if status['provider'] == 'deepseek':
        effort = status['reasoning']
        if effort == 'default':
            effort = 'high'
        params['thinking'] = {'type': 'disabled' if effort == 'none' else 'enabled'}
        if effort != 'none':
            params['reasoning_effort'] = effort
    return params


def product_config_identity() -> str:
    values = _product_file()
    fields = {name: values.get(name) for name in
              ('TRADEINTEL_MODEL_BASE_URL', 'TRADEINTEL_MODEL_NAME',
               'TRADEINTEL_MODEL_API_KEY', 'PRODUCT_REASONING')}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def mark_product_connection(result: str, *, expected_identity: str) -> None:
    if result not in {'connected', 'rejected', 'unavailable'}:
        raise ValueError('invalid connection result')
    values = _product_file()
    if not values:
        raise ValueError('product settings not saved')
    if product_config_identity() != expected_identity:
        raise ValueError('模型配置在测试过程中已更改，请重新测试')
    values['PRODUCT_CONNECTION'] = result
    values['PRODUCT_CHECKED_AT'] = datetime.now(timezone.utc).isoformat()
    _write_product_file(values)


def probe_product_model() -> dict[str, object]:
    """One explicitly requested, bounded provider call with no report data."""
    from dataclasses import replace
    from .model_adapter import OpenAICompatibleModel

    identity = product_config_identity()
    config = load_product_config()
    if not _product_file() or not config.api_key:
        raise ValueError('请先保存模型设置，再测试连接')
    config = replace(config, timeout_seconds=min(config.timeout_seconds, 20))
    try:
        answer = OpenAICompatibleModel(
            config, system_prompt='', request_params=product_request_params(probe=True)
        ).complete(messages=[{'role': 'user', 'content': 'Reply with OK.'}], tools=[])
    except ModelAdapterError as exc:
        http_status = exc.details.get('http_status')
        rejected = isinstance(http_status, int) and 400 <= http_status < 500
        mark_product_connection('rejected' if rejected else 'unavailable',
                                expected_identity=identity)
        guidance = {
            400: '请求参数被拒绝；请核对模型 ID 和推理设置。',
            401: '凭证未通过验证。',
            403: '当前凭证没有该模型的调用权限。',
            404: '模型 ID 或接口地址不存在。',
            422: '请求参数不符合该模型的要求。',
            429: '请求受到限流或额度限制；仅凭状态码无法区分。',
        }.get(http_status, '模型服务未返回可用结果；如可能已产生费用，请查看服务商账单。')
        return {'status': 'rejected' if rejected else 'unavailable',
                'model': config.model, 'http_status': http_status,
                'provider_code': exc.details.get('code'),
                'provider_param': exc.details.get('param'),
                'message': guidance}
    mark_product_connection('connected', expected_identity=identity)
    return {'status': 'connected', 'model': config.model,
            'response_model': answer.metadata.get('model'),
            'checked_at': product_status()['checked_at'],
            'message': '短请求已连通；完整报告仍需单独验收。'}


def save_product_config(provider: str, model: str, key: str,
                        reasoning: str = 'default'):
    if provider not in PRODUCT_PROVIDERS:
        raise ValueError('unsupported provider')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9._-]{2,80}', model):
        raise ValueError('invalid model name')
    if provider == 'deepseek' and model == 'flash':
        raise ValueError('DeepSeek Flash 的请求型号是 deepseek-flash；请选正确型号后再测试')
    if reasoning not in REASONING_LEVELS or (provider != 'deepseek' and reasoning != 'default'):
        raise ValueError('这个服务商暂不支持所选推理档位')
    if not key:
        existing = _product_file()
        if existing.get('TRADEINTEL_MODEL_BASE_URL') == PRODUCT_PROVIDERS[provider]:
            key = existing.get('TRADEINTEL_MODEL_API_KEY', '')
    if (not isinstance(key, str) or not 12 <= len(key) <= 512
            or not key.isascii() or any(char.isspace() for char in key)):
        raise ValueError('请填写该服务商的有效 API Key')
    values = {'TRADEINTEL_MODEL_BASE_URL': PRODUCT_PROVIDERS[provider],
              'TRADEINTEL_MODEL_NAME': model,
              'TRADEINTEL_MODEL_API_KEY': key,
              'TRADEINTEL_MODEL_TIMEOUT': '90',
              'TRADEINTEL_MODEL_TEMPERATURE': '0',
              'PRODUCT_REASONING': reasoning,
              'PRODUCT_CONNECTION': 'untested'}
    OpenAICompatibleConfig.from_env(values)
    _write_product_file(values)
    return {'provider': provider, 'model': model, 'configured': True}


def save_glm_key(key, *, model='glm-4.7', path=CONFIG_PATH):
    if not key or not key.isascii() or any(c.isspace() for c in key):
        raise ValueError('invalid key format')
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('unsafe local config path')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    values = {'TRADEINTEL_MODEL_BASE_URL': 'https://open.bigmodel.cn/api/paas/v4',
              'TRADEINTEL_MODEL_NAME': model, 'TRADEINTEL_MODEL_API_KEY': key,
              'TRADEINTEL_MODEL_TIMEOUT': '60', 'TRADEINTEL_MODEL_TEMPERATURE': '0'}
    OpenAICompatibleConfig.from_env(values)
    # Exclusive creation: an existing key is never silently overwritten.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(values, stream)
        stream.flush()
        os.fsync(stream.fileno())
    return path
