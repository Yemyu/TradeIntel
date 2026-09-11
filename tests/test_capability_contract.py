from copy import deepcopy
import unittest
from unittest.mock import patch
from src.tradeintel_ai.capability_contract import assess_trade_request,describe_capabilities


def request(**changes):
    result={'policy_id':'us_301_list1_2018','operation':'read','metric':'import_value_consumption_usd',
            'origin':'China','granularity':'policy_aggregate','months':['2017-03'],
            'hs6':None,'causal_effect':False}
    result.update(changes)
    return result


class CapabilityTests(unittest.TestCase):
    def test_read_capability_is_not_execution_or_semantic_verification(self):
        r=request();before=deepcopy(r)
        with patch('src.tradeintel_ai.evidence_v21.trade_v21',side_effect=AssertionError('must not query amounts')):
            result=assess_trade_request(r)
        self.assertEqual(result['status'],'within_declared_capability')
        self.assertFalse(result['executed'])
        self.assertFalse(result['intent_verified'])
        self.assertFalse(result['data_observed'])
        self.assertEqual(r,before)

    def test_write_company_country_and_gdp_not_substituted(self):
        for changes,field in (({'operation':'delete'},'operation'),({'origin':'Germany'},'origin'),
                              ({'granularity':'company'},'granularity'),({'metric':'GDP'},'metric')):
            result=assess_trade_request(request(**changes))
            self.assertEqual(result['status'],'unsupported_request')
            self.assertIn(field,[r['field'] for r in result['reasons']])
            self.assertFalse(result['executed'])

    def test_causal_request_uses_actual_gate(self):
        result=assess_trade_request(request(causal_effect=True))
        self.assertEqual(result['status'],'unsupported_request')
        self.assertFalse(result['capabilities']['causal_allowed'])
        self.assertTrue(result['capabilities']['causal_status_verified'])

    def test_mixed_and_all_outside_time_ranges(self):
        result=assess_trade_request(request(months=['2015-08','2019-02']))
        self.assertEqual(result['status'],'partially_in_coverage')
        self.assertEqual(result['months_in_declared_coverage'],['2019-02'])
        self.assertEqual(assess_trade_request(request(months=['2025-01']))['status'],'outside_coverage')

    def test_missing_unknown_or_bad_type_requires_clarification(self):
        for r in ({},request(sql='DROP TABLE x'),request(causal_effect=1),request(months=['2019-13']),
                  request(months=['2017-01']*2),request(origin=None),request(months=[])):
            self.assertEqual(assess_trade_request(r)['status'],'needs_clarification')

    def test_hs6_grain_constraints(self):
        self.assertEqual(assess_trade_request(request(granularity='hs6_2017'))['status'],'unsupported_request')
        self.assertEqual(assess_trade_request(request(hs6='123456'))['status'],'unsupported_request')
        self.assertEqual(assess_trade_request(request(granularity='hs6_2017',hs6='000000'))['status'],'unsupported_request')

    def test_capabilities_have_versioned_sources_and_only_read_tools(self):
        result=describe_capabilities()
        self.assertEqual(result['allowed_operations'],['read'])
        self.assertNotIn('build_evidence_bundle',result['model_tools'])
        self.assertTrue(all(s.get('sha256') for s in result['sources']))


if __name__=='__main__':unittest.main()
