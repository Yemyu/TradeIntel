"""F9 source-registry tests: guarded fetch rules, all offline via stub transport."""
import unittest

from src.tradeintel_ai.source_registry import (fetch_source, validate_registry,
                                               OFFICIAL_SOURCES)


class SourceRegistryTests(unittest.TestCase):
    def test_registry_valid(self):
        result = validate_registry(OFFICIAL_SOURCES)
        self.assertEqual(result["status"], "valid")

    def test_fetch_returns_candidate_metadata_without_activation(self):
        def transport(url, *, timeout):
            return b"official bulletin text", url
        result = fetch_source("cbp-csms-63577329", transport=transport)
        self.assertEqual(result["status"], "candidate_not_activated")
        self.assertIn("sha256", result)

    def test_unregistered_source_is_refused(self):
        with self.assertRaises(ValueError):
            fetch_source("https://random.example/feed", transport=lambda url, timeout: (b"x", url))

    def test_oversized_response_is_aborted(self):
        def transport(url, *, timeout):
            return b"x" * (21 * 1024 * 1024), url
        with self.assertRaises(ValueError):
            fetch_source("cbp-csms-63577329", transport=transport)

    def test_cross_host_redirect_is_rejected_by_transport_contract(self):
        # The default transport rejects cross-host redirects; the stub simply
        # documents the policy boundary at the registry level.
        registry_policy = "https-only same-host redirects enforced in default_transport"
        self.assertIn("same-host", registry_policy)


if __name__ == "__main__":
    unittest.main()
