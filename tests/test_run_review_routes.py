import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from src.tradeintel_ai.web_app import create_server
from src.tradeintel_ai.interpretation_review_store import FILES
from tests.test_policy_exposure_tools import make_fixture
from tests.review_fixture import write_review_fixture


class RunReviewRoutesTests(unittest.TestCase):
    def test_runs_are_independent_even_with_identical_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            make_fixture(root)
            ids=['exposure-20260914T120000-abcdef12','exposure-20260914T120001-abcdef13']
            for run_id in ids:
                target=root/'runs'/run_id
                target.mkdir(parents=True)
                write_review_fixture(target)
            server=create_server(root=root,host='127.0.0.1',port=0,output_root=root/'runs')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def get(route,run):
                return urlopen(base+route+'?run_id='+run)
            def post(run,payload):
                return urlopen(Request(base+'/api/saved-interpretation-review?run_id='+run,
                    data=json.dumps(payload).encode(),headers={'Origin':base,'Content-Type':'application/json'}))
            try:
                with patch('src.tradeintel_ai.web_app.load_config',side_effect=AssertionError('no API')):
                    packets=[]
                    for run in ids:
                        with get('/api/saved-interpretation-review',run) as response:
                            packets.append(json.load(response))
                    self.assertNotEqual(packets[0]['fingerprint'],packets[1]['fingerprint'])
                    payload={'fingerprint':packets[0]['fingerprint'],'reviewer':'fixture','facts_checked':True,
                        'decisions':[{'index':0,'verdict':'reject','reason':'unsupported'},
                                     {'index':1,'verdict':'accept','reason':'supported limitation'}]}
                    with self.assertRaises(HTTPError): post(ids[1],payload)
                    with post(ids[0],payload) as response:
                        self.assertEqual(json.load(response)['status'],'recorded')
                    with get('/api/saved-interpretation-draft',ids[0]) as response:
                        self.assertIn('现有数据为海关统计金额',response.read().decode())
                    with get('/api/saved-interpretation-review',ids[0]) as response:
                        latest=json.load(response)
                    self.assertEqual(latest['data_report']['status'],'unavailable')
                    revision={**payload,'base_review_digest':latest['review_digest'],
                              'change_reason':'withdraw after recheck',
                              'decisions':[{'index':0,'verdict':'reject','reason':'unsupported'},
                                           {'index':1,'verdict':'needs_revision','reason':'recheck needed'}]}
                    with post(ids[0],revision) as response:
                        revised=json.load(response)
                    self.assertEqual(revised['revision'],2)
                    self.assertEqual(len(revised['history']),2)
                    with self.assertRaises(HTTPError) as revoked:
                        get('/api/saved-interpretation-draft',ids[0])
                    self.assertEqual(revoked.exception.code,409)
                    with self.assertRaises(HTTPError) as pending:
                        get('/api/saved-interpretation-draft',ids[1])
                    self.assertEqual(pending.exception.code,409)
                    self.assertFalse((root/'runs'/ids[1]/'human-interpretation-review.json').exists())
                    for invalid in ['', '../outside', ids[0]+'&run_id='+ids[1], 'unknown']:
                        with self.subTest(invalid=invalid),self.assertRaises(HTTPError):
                            get('/api/saved-interpretation-review',invalid)
                    alias='exposure-20260914T120002-abcdef14'
                    (root/'runs'/alias).symlink_to(root/'runs'/ids[0],target_is_directory=True)
                    with self.assertRaises(HTTPError):get('/api/saved-interpretation-review',alias)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
