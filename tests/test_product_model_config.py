import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from src.tradeintel_ai.model_adapter import ModelAdapterError

from src.tradeintel_ai import local_provider_config


class ProductModelConfigTests(unittest.TestCase):
    def test_product_setting_is_private_and_does_not_return_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'product-model.json'
            with patch.object(local_provider_config, 'PRODUCT_CONFIG_PATH', path):
                result = local_provider_config.save_product_config(
                    'glm', 'glm-4.7', 'sample-test-key-123456')
                self.assertEqual(result, {'provider': 'glm', 'model': 'glm-4.7',
                                          'configured': True})
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(local_provider_config.load_product_config().model,
                                 'glm-4.7')
                self.assertNotIn('sample-test-key', str(result))
                with self.assertRaises(ValueError):
                    local_provider_config.save_product_config('other', 'model',
                                                              'sample-test-key-123456')

    def test_existing_key_can_change_model_and_probe_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'product-model.json'
            with patch.object(local_provider_config, 'PRODUCT_CONFIG_PATH', path):
                local_provider_config.save_product_config('deepseek', 'deepseek-flash',
                                                          'sample-test-key-123456')
                with self.assertRaisesRegex(ValueError, 'deepseek-flash'):
                    local_provider_config.save_product_config('deepseek', 'flash', '')
                local_provider_config.save_product_config('deepseek', 'deepseek-v4-pro', '', 'high')
                self.assertEqual(local_provider_config.product_status()['connection'], 'untested')
                with patch('src.tradeintel_ai.model_adapter.OpenAICompatibleModel') as provider:
                    provider.return_value.complete.return_value = SimpleNamespace(
                        metadata={'model':'deepseek-v4-pro'})
                    result = local_provider_config.probe_product_model()
                    self.assertEqual(result['status'], 'connected')
                    self.assertEqual(provider.return_value.complete.call_count, 1)
                self.assertEqual(local_provider_config.product_status()['connection'], 'connected')
                local_provider_config.save_product_config('deepseek', 'deepseek-flash', '')
                self.assertEqual(local_provider_config.product_status()['connection'], 'untested')
                self.assertNotIn('sample-test-key', str(local_provider_config.product_status()))

    def test_http_400_is_rejected_not_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'product-model.json'
            with patch.object(local_provider_config, 'PRODUCT_CONFIG_PATH', path):
                local_provider_config.save_product_config('deepseek', 'deepseek-flash',
                                                          'sample-test-key-123456')
                with patch('src.tradeintel_ai.model_adapter.OpenAICompatibleModel') as provider:
                    provider.return_value.complete.side_effect = ModelAdapterError(
                        '模型服务返回 HTTP 400', details={'http_status':400, 'param':'model'})
                    result = local_provider_config.probe_product_model()
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(result['provider_param'], 'model')
                self.assertEqual(local_provider_config.product_status()['connection'], 'rejected')
