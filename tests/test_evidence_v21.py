import unittest
from copy import deepcopy
from src.tradeintel_ai.evidence_v21 import EvidenceRegistryV21, EvidenceAgentV21, report_v21
from src.tradeintel_ai.agent import ModelResponse, ModelToolCall


class V21Tests(unittest.TestCase):
    def setUp(self):
        self.r = EvidenceRegistryV21()

    def test_discrete_months_sum_only_requested_values(self):
        args = {"origin":"other_origins","months":["2019-11","2019-02","2019-05"]}
        t = self.r.call("get_trade_series",args)
        self.assertEqual(t["data"]["total_usd"],116794271126)
        self.assertEqual([x["month"] for x in t["data"]["series"]],sorted(args["months"]))
        self.assertEqual({s["month"] for s in t["evidence"]["sources"] if "month" in s},set(args["months"]))

    def test_other_months_origin_and_overlapping_calls(self):
        a=self.r.call("get_trade_series",{"origin":"all_origins","months":["2017-01","2017-03"]})
        b=self.r.call("get_trade_series",{"origin":"all_origins","months":["2017-03"]})
        report=report_v21([a,b])
        total=next(f["value"] for f in report.facts if f["label"].startswith("上述已查询月份去重合计"))
        self.assertEqual(total,a["data"]["total_usd"])

    def test_invalid_selection_never_silently_widens(self):
        for args in ({},{"months":[]},{"months":["2019-02"]*2},
                     {"months":["2019-13"]},{"months":["2019-02"],"start":"2019-01"},
                     {"start":"2017-02"},{"start":"2019-01","end":"2018-01"},
                     {"months":["2015-01"],"origin":"invalid"},
                     {"months":["2015-01"],"scope":"anything"}):
            with self.subTest(args=args):
                self.assertEqual(self.r.call("get_trade_series",args)["status"],"error")

    def test_mixed_coverage_null_and_explanation(self):
        t=self.r.call("get_trade_series",{"months":["2015-01","2018-11"]})
        self.assertEqual(t["status"],"ok")
        self.assertIsNone(t["data"]["total_usd"])
        self.assertEqual(t["data"]["observed_total_usd"],1948740426)
        self.assertIn("2015-01 超出本项目数据覆盖范围",report_v21([t]).render())
        self.assertEqual(t["data"]["missing_months"],["2015-01"])

    def test_all_unavailable_not_zero(self):
        t=self.r.call("get_trade_series",{"months":["2021-06","2014-10"]})
        self.assertIsNone(t["data"]["total_usd"])
        self.assertTrue(all(r["value_usd"] is None for r in t["data"]["series"]))
        self.assertFalse(any("month" in s for s in t["evidence"]["sources"]))

    def test_policy_and_counts_explanations_use_evidence(self):
        policy=self.r.call("get_policy_event")
        ready=self.r.call("get_causal_readiness")
        text=report_v21([policy,ready]).render()
        self.assertIn("找到对照不代表平衡检验通过",text)
        changed=deepcopy(policy)
        changed["data"]["effective_date"]="2001-02-03"
        changed["data"]["additional_rate_percent"]=7.0
        self.assertIn("登记生效日为 2001-02-03，额外税率为 7.0%",report_v21([changed]).render())
        policy["evidence"]["sources"]=[]
        with self.assertRaises(ValueError):
            report_v21([policy])

    def test_model_prose_stays_private_and_failed_calls_visible(self):
        class Model:
            def complete(self,*,messages,tools):
                if len(messages)==1:
                    return ModelResponse(tool_calls=(
                        ModelToolCall("a","get_trade_series",{"months":["2019-99"]}),
                        ModelToolCall("b","get_policy_event",{})))
                return ModelResponse(text="unverified invented facts")
        result=EvidenceAgentV21(Model()).answer("查数据和政策")
        self.assertNotIn("unverified invented facts",result["response"])
        self.assertIn("部分工具请求失败",result["response"])
        self.assertEqual(len(result["failed_tool_requests"]),1)
        self.assertFalse(result["task_success_verified"])
