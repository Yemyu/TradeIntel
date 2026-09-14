import json
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.tradeintel_ai.web_app import (
    DemoBusyError,
    DemoCoordinator,
    create_server,
    policy_payload,
    safe_report_path,
    update_payload,
    version_bound_exposure,
    validate_exposure_params,
)
from src.tradeintel_ai.exposure_version_store import ExposureVersionStore, VersionStoreError, content_digest
from tests.test_policy_exposure_tools import make_fixture


class WebAppTests(unittest.TestCase):
    def test_case_boundary_needs_no_model_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = make_fixture(root)
            coordinator = DemoCoordinator()
            with patch('src.tradeintel_ai.web_app.load_config', side_effect=AssertionError('must not load key')):
                for question, selected, status in [
                    ('光伏政策是什么', None, 'clarify'),
                    ('解释政策', 'us_301_solar2024', 'unsupported'),
                    ('85414300政策', 'us_301_review2025_tungsten_solar', 'clarify')]:
                    result = coordinator.ask(question, repository=repo, output_root=root/'runs', policy_id=selected)
                    self.assertEqual(result['status'], status)
                    self.assertEqual(result['model_calls'], 0)
                    self.assertFalse(result['report_available'])
                    self.assertIsNone(result['report_url'])

    def register_fixture(self, root):
        repository = make_fixture(root)
        policy = "us_301_review2025_tungsten_solar"
        monthly = root / "data/processed/policy_exposure/monthly"
        def sha(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()
        from src.tradeintel_ai.policy_exposure_tools import get_policy_exposure_series
        metrics = {r['month']: r for r in get_policy_exposure_series(repository=repository, start='2025-01', end='2025-02')['data']['series']}
        body = {
            "policy_id": policy, "start": "2025-01", "end": "2025-02",
            "months": {month: {"output_sha256": sha(monthly / f"{policy}_{month.replace('-', '_')}.csv"), 'metrics': metrics[month]}
                       for month in ("2025-01", "2025-02")},
            "policy_files": {str(path.relative_to(root)): sha(path)
                             for path in (root / "data/processed/policy").glob("*.csv")},
        }
        store = ExposureVersionStore(root)
        store.bootstrap({**body, "version": content_digest(body)})
        store.prepare_release(store.active_version())
        return repository, store

    def test_query_version_binding_and_failed_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, store = self.register_fixture(root)
            result = version_bound_exposure(repository, start="2025-01", end="2025-02")
            self.assertEqual(result["data_version"], store.active_version())
            store.record_failure(reason="fixture rejected")
            self.assertEqual(version_bound_exposure(repository, start="2025-01", end="2025-02"), result)
            with self.assertRaises(VersionStoreError):
                version_bound_exposure(repository, start="2025-01", end="2025-03")
            path = next((root / "data/processed/policy_exposure/monthly").glob("*.csv"))
            path.write_bytes(path.read_bytes() + b"\n")
            self.assertEqual(version_bound_exposure(repository, start="2025-01", end="2025-02"), result)
            self.assertEqual(update_payload(root)["status"], "ready")

    def test_change_during_query_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, store = self.register_fixture(root)
            def changing_query(**kwargs):
                path = next((kwargs['repository'].paths.root / "data/processed/policy").glob("*.csv"))
                path.write_bytes(path.read_bytes() + b"\n")
                return {"data": {}}
            with patch("src.tradeintel_ai.web_app.get_policy_exposure_series", side_effect=changing_query):
                with self.assertRaises(VersionStoreError):
                    version_bound_exposure(repository, start="2025-01", end="2025-02")

    def test_update_payload_exposes_status_without_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.register_fixture(root)
            payload = update_payload(root)
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertEqual(payload["status"], "ready")
            self.assertNotIn("snapshot_path", serialized)
            self.assertNotIn(str(root), serialized)

    def test_query_validation_is_narrow_and_lossless(self):
        self.assertEqual(
            validate_exposure_params(
                {"start": ["2025-01"], "end": ["2025-01"], "origin": ["China"], "hts8": ["1234.56.78"]},
                root=Path("/tmp"),
            )["hts8"],
            "12345678",
        )
        for query in [
            {"start": ["2024-12"], "end": ["2025-01"]},
            {"start": ["2025-02"], "end": ["2025-01"]},
            {"origin": ["made-up"]},
            {"start": ["2025-01", "2025-02"]},
            {"hts8": ["123"]},
        ]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                validate_exposure_params(query)

    def test_policy_payload_uses_corrected_public_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_fixture(root, include_second_month=False)
            payload = policy_payload(repository)
            self.assertEqual(payload["data_window"]["months"], 1)
            self.assertEqual(payload["products"][0]["hts8"], "12345678")
            self.assertEqual(len(payload["sources"]), 4)
            self.assertNotIn("api_key", json.dumps(payload))

    def test_safe_report_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "exposure-20260914T120000-abcdef12"
            run.mkdir(parents=True)
            report = run / "report.zh-CN.md"
            report.write_text("# test", encoding="utf-8")
            self.assertEqual(safe_report_path(root, run.name), report.resolve())
            for value in ["../secret", "not-a-run", run.name + "/../secret"]:
                with self.assertRaises(ValueError):
                    safe_report_path(root, value)

    def test_http_routes_query_policy_and_static_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_fixture(root)
            (root / "web").mkdir()
            (root / "web/index.html").write_text("<html>TradeShock AI 数据版本更新 /api/update 查询数据 AI 演示</html>", encoding="utf-8")
            (root / 'web/solar-demo.html').write_text('<html>只读演示</html>')
            (root / 'web/research-review.html').write_text('<html>真实结果，未批准</html>')
            (root / 'web/interpretation-review.html').write_text(
                (Path(__file__).resolve().parents[1] / 'web/interpretation-review.html').read_text(encoding='utf-8'),
                encoding='utf-8')
            server = create_server(root=root, host="127.0.0.1", port=0, output_root=root / "runs")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/policy") as response:
                    policy = json.loads(response.read())
                self.assertEqual(policy["policy_id"], "us_301_review2025_tungsten_solar")
                with urlopen(base + '/demo/solar') as response:
                    self.assertIn('只读演示', response.read().decode('utf-8'))
                with patch('src.tradeintel_ai.web_app.load_config', side_effect=AssertionError('candidate must not load credentials')):
                    task={'policy_id':'us_301_solar2024','month':'2026-07','product':'all','task':'source_and_investigation'}
                    request=Request(base+'/api/research-structured',data=json.dumps(task).encode(),headers={'Content-Type':'application/json'},method='POST')
                    with urlopen(request) as response:
                        result=json.loads(response.read())
                    self.assertEqual(result['status'],'not_available')
                    self.assertEqual(result['model_calls'],0)
                    request=Request(base+'/api/research-structured',data=json.dumps(task).encode(),headers={'Content-Type':'application/json','Origin':'https://foreign.invalid'},method='POST')
                    with self.assertRaises(HTTPError) as rejected: urlopen(request)
                    self.assertEqual(rejected.exception.code,400)
                run_id='exposure-20260914T120000-abcdef12'
                artifact=root/'runs'/run_id
                artifact.mkdir(parents=True)
                (artifact/'source-packet.zh-CN.md').write_text('未批准 <script>not executable</script>')
                with urlopen(base+'/api/research-artifact/'+run_id+'/source-packet.zh-CN.md') as response:
                    self.assertIn('text/plain',response.headers['Content-Type'])
                    self.assertIn('未批准',response.read().decode())
                with self.assertRaises(HTTPError) as forbidden:
                    urlopen(base+'/api/research-artifact/'+run_id+'/status.json')
                self.assertEqual(forbidden.exception.code,400)
                from src.tradeintel_ai.interpretation_review_store import FILES
                source=Path(__file__).resolve().parents[1]/'tmp/trade-aware-interpretation-v1-first/run'
                review_dir=root/'tmp/trade-aware-interpretation-v1-first/run'
                review_dir.mkdir(parents=True)
                for name in FILES:(review_dir/name).write_bytes((source/name).read_bytes())
                with patch('src.tradeintel_ai.web_app.load_config',side_effect=AssertionError('review must not load credentials')):
                    with urlopen(base+'/api/saved-interpretation-review') as response:
                        review=json.loads(response.read())
                    with self.assertRaises(HTTPError) as draft_pending:
                        urlopen(base+'/api/saved-interpretation-draft')
                    self.assertEqual(draft_pending.exception.code,409)
                    decisions={'fingerprint':review['fingerprint'],'reviewer':'fixture','facts_checked':False,
                               'decisions':[{'index':i,'verdict':'needs_revision','reason':'fixture only'} for i in range(len(review['notes']))]}
                    with self.assertRaises(HTTPError) as refused:
                        urlopen(Request(base+'/api/saved-interpretation-review',data=json.dumps(decisions).encode(),headers={'Content-Type':'application/json'}))
                    self.assertEqual(refused.exception.code,400)
                    decisions={'fingerprint':review['fingerprint'],'reviewer':'fixture','facts_checked':True,
                               'decisions':[{'index':0,'verdict':'reject','reason':'fixture rejects unsupported direction'},
                                            {'index':1,'verdict':'accept','reason':'fixture accepts tax burden limitation'}]}
                    with urlopen(Request(base+'/api/saved-interpretation-review',data=json.dumps(decisions).encode(),headers={'Content-Type':'application/json','Origin':base})) as response:
                        saved=json.loads(response.read())
                    self.assertEqual(saved['status'],'recorded')
                    self.assertFalse(saved['decision']['case_publication_allowed'])
                    with urlopen(base+'/api/saved-interpretation-draft') as response:
                        draft=response.read().decode('utf-8')
                        self.assertIn('AI建议（仅纳入人工采纳项）',draft)
                        self.assertIn('人工审阅稿',draft)
                        self.assertNotIn('第三国转运或轻微加工',draft)
                with patch('src.tradeintel_ai.web_app.load_config', side_effect=AssertionError('read only')):
                    with urlopen(base + '/demo/research-review') as response:
                        self.assertIn('未批准', response.read().decode('utf-8'))
                    with urlopen(base + '/review/interpretation') as response:
                        page = response.read().decode('utf-8')
                    self.assertIn('不是案例发布批准', page)
                    self.assertIn('只含采纳项；不发布案例', page)
                    with self.assertRaises(HTTPError) as failed:
                        urlopen(base + '/demo/research-review/../../.local/glm.json')
                    self.assertEqual(failed.exception.code,404)
                with patch('src.tradeintel_ai.web_app.load_config', side_effect=AssertionError('catalog must not load credentials')):
                    with urlopen(base + '/api/cases') as response:
                        catalog = json.loads(response.read())
                    self.assertEqual(len(catalog['cases']), 2)
                    solar = next(c for c in catalog['cases'] if c['policy_id'] == 'us_301_solar2024')
                    self.assertFalse(solar['query_enabled'])
                    self.assertNotIn('versions', solar)
                with urlopen(base + "/api/update") as response:
                    update = json.loads(response.read())
                self.assertEqual(update["status"], "uninitialized")
                with urlopen(base + "/api/exposure?start=2025-01&end=2025-02&origin=China") as response:
                    result = json.loads(response.read())
                self.assertEqual([row["value_usd"] for row in result["data"]["series"]], [20, 10])
                with urlopen(base + "/") as response:
                    page = response.read().decode("utf-8")
                self.assertIn("TradeShock AI", page)
                self.assertIn("数据版本更新", page)
                self.assertIn("/api/update", page)
                with patch.object(server.RequestHandlerClass.coordinator, 'ask', return_value={
                    'status':'clarify','message':'请补充月份','model_calls':1,'report_available':False
                }) as ask:
                    request = Request(base + '/api/research', data=json.dumps({'question':'请查登记商品'}).encode(),
                                      headers={'Content-Type':'application/json'})
                    with urlopen(request) as response:
                        self.assertEqual(json.loads(response.read())['status'], 'clarify')
                    self.assertEqual(ask.call_args.args, ('请查登记商品',))
                    request = Request(base + '/api/research', data=json.dumps({
                        'question':'解释政策','policy_id':'us_301_solar2024'}).encode(),
                        headers={'Content-Type':'application/json'})
                    with urlopen(request) as response:
                        self.assertEqual(json.loads(response.read())['status'], 'clarify')
                    self.assertEqual(ask.call_args.kwargs['policy_id'], 'us_301_solar2024')
                    request = Request(base + '/api/research', data=b'{"question":"test"}',
                                      headers={'Content-Type':'application/json','Origin':'https://example.test'})
                    with self.assertRaises(HTTPError):
                        urlopen(request)
                    self.assertEqual(ask.call_count,2)
                with self.assertRaises(HTTPError) as context:
                    urlopen(base + "/api/exposure?start=2024-01&end=2025-01")
                self.assertEqual(context.exception.code, 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_coordinator_marks_same_case_busy_and_returns_report_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = make_fixture(root, include_second_month=False)
            output_root = root / "runs"
            coordinator = DemoCoordinator()

            def fake_run(model, output, **kwargs):
                output.mkdir(parents=True)
                (output / "report.zh-CN.md").write_text("# report", encoding="utf-8")
                return {"status": "draft_needs_review", "model_calls": 3}

            with patch("src.tradeintel_ai.web_app.load_config") as load, patch(
                "src.tradeintel_ai.web_app.run_exposure_demo", side_effect=fake_run
            ):
                from src.tradeintel_ai.model_adapter import OpenAICompatibleConfig

                load.return_value = OpenAICompatibleConfig(
                    base_url="https://example.test", model="fixture", api_key="local-only", timeout_seconds=1.0
                )
                with coordinator._lock:
                    coordinator._running.add("may-tungsten")
                with self.assertRaises(DemoBusyError):
                    coordinator.run("may-tungsten", repository=repository, output_root=output_root)
                with coordinator._lock:
                    coordinator._running.clear()
                result = coordinator.run("may-tungsten", repository=repository, output_root=output_root)
            self.assertTrue(result["report_available"])
            self.assertEqual(result["report_url"].split("/")[-1], result["run_id"])


if __name__ == "__main__":
    unittest.main()
