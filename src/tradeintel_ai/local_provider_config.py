"""Project-local provider settings, excluded from Git and never logged."""
import json
import os
from pathlib import Path
import stat

from .model_adapter import OpenAICompatibleConfig

CONFIG_PATH = Path(__file__).resolve().parents[2] / '.local' / 'glm.json'


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
