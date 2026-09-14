import json
import unittest
from scripts.compare_json_mode import judge

class ComparisonTests(unittest.TestCase):
    def test_strict_grading(self):
        items=[{'id':'A07','status':'supported','value':'蓝色','citation':'inventory:7'},
               {'id':'B12','status':'unknown','value':'','citation':''},
               {'id':'C03','status':'supported','value':'绿色','citation':'inventory:3'}]
        self.assertTrue(judge(json.dumps({'items':items})))
        self.assertFalse(judge('```json\n'+json.dumps({'items':items})+'\n```'))
        self.assertFalse(judge('{"items":[],"items":[]}'))
        items[0]['status']='known'
        self.assertFalse(judge(json.dumps({'items':items})))
        self.assertFalse(judge('null'))
