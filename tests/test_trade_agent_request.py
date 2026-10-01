"""Scope contract acceptance. No provider/network calls; model behavior is scripted."""
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from tradeintel_ai.agent import ModelResponse, ModelToolCall
from tradeintel_ai.trade_agent import TradeResearchAgent, _primary_report
from tradeintel_ai.trade_agent_request import (derive_constraints, validate_query_constraints,
                                              validate_finished_scope)
from tradeintel_ai.trade_agent_tools import TradeAgentTools
from tradeintel_ai.trade_agent_store import read_session


DATA_ROOT = Path(__file__).resolve().parents[1] / 'tmp/handoff-runs/trade-demo-data-20260925'


def report(flow='import', partner='ALL_ORIGINS', code='1201', start='2026-05', end='2026-05'):
    return {'report_id': uuid.uuid4().hex, 'scope': {'flow':flow, 'partner':partner,
        'product_code':code, 'start_month':start, 'end_month':end}}


class RequestConstraintTests(unittest.TestCase):
    def test_explicit_dates_and_ranges(self):
        for question, bounds in [('2026年5月美国大豆进口', ('2026-05','2026-05')),
                                  ('2026年5月至7月美国大豆进口', ('2026-05','2026-07')),
                                  ('US soybean imports in 2026-05', ('2026-05','2026-05'))]:
            with self.subTest(question=question):
                c=derive_constraints(question)
                validate_query_constraints(c, {}, 'import', 'all', *bounds)
                with self.assertRaisesRegex(ValueError, '月份'):
                    validate_query_constraints(c, {}, 'import', 'all', '2026-07','2026-07')

    def test_missing_year_and_multiple_months_are_not_guessed(self):
        for q in ['美国大豆7月进口', '2026年5月与7月美国大豆进口']:
            with self.subTest(question=q):
                self.assertTrue(derive_constraints(q)['issues'])

    def test_direction_negation_and_followup_override(self):
        previous={'flow':'import', 'partner':'CHINA'}
        for q in ['出口呢？','不是进口，是出口','not imports, exports']:
            c=derive_constraints(q, previous)
            self.assertEqual(c['flow']['value'], 'export')
            self.assertEqual(c['partner']['value'], 'china')
            with self.assertRaisesRegex(ValueError, '方向'):
                validate_query_constraints(c, {}, 'import','china','2026-05','2026-05')

    def test_both_requires_matching_product_and_period(self):
        c=derive_constraints('美国大豆进出口分别如何？')
        with self.assertRaises(ValueError):
            validate_finished_scope(c,[report()])
        validate_finished_scope(c,[report(),report('export','ALL_DESTINATIONS')])
        with self.assertRaises(ValueError):
            validate_finished_scope(c,[report(),report('export','ALL_DESTINATIONS',code='1507')])
        with self.assertRaises(ValueError):
            validate_finished_scope(c,[report(),report('export','ALL_DESTINATIONS',end='2026-06')])

    def test_partner_required_at_finish_but_supplement_allowed(self):
        c=derive_constraints('美国大豆出口到中国')
        with self.assertRaisesRegex(ValueError,'伙伴'):
            validate_finished_scope(c,[report('export','ALL_DESTINATIONS')])
        validate_finished_scope(c,[report('export','ALL_DESTINATIONS'),report('export','CHINA')])
        c=derive_constraints('不要中国，只看全部美国大豆出口')
        self.assertFalse(c['issues'])
        options=[report('export','ALL_DESTINATIONS'),report('export','CHINA')]
        self.assertEqual(_primary_report(options,c['question'],{'partner':'CHINA'}),options[0])

    def test_exclusion_and_ambiguous_negation(self):
        for q in ['美国大豆出口排除中国','美国大豆出口，除中国以外','不要中国，只看大豆出口']:
            with self.subTest(q=q):
                self.assertTrue(derive_constraints(q)['issues'])

    def test_unsupported_roles_do_not_convert_to_us_all(self):
        for q in ['日本大豆进口多少','美国向巴西出口的大豆','美国从加拿大进口小麦',
                  '中国从美国进口大豆','美国向未知伙伴出口大豆']:
            with self.subTest(q=q):
                self.assertTrue(derive_constraints(q)['issues'])

    def test_context_country_and_policy_year_are_not_query_scope(self):
        for q in ['英国脱欧后美国大豆进口怎么变？','2018年那次政策与最近美国大豆进口有关吗？',
                  '中国政策背景下美国大豆进口有什么变化？']:
            with self.subTest(q=q):
                c=derive_constraints(q)
                self.assertFalse(c['issues'])
                self.assertEqual(c['period']['status'],'unspecified')
                self.assertEqual(c['partner']['status'],'unspecified')

    def test_negated_month_does_not_override_affirmative_month(self):
        c=derive_constraints('不是2026年5月，查2026年7月美国大豆进口')
        self.assertFalse(c['issues'])
        self.assertEqual(c['period']['value'],{'start':'2026-07','end':'2026-07'})

    def test_calendar_and_yoy_boundaries(self):
        self.assertFalse(derive_constraints('不是上月，查最新美国大豆进口')['issues'])
        self.assertTrue(derive_constraints('美国大豆进口同比如何')['issues'])


@unittest.skipUnless(DATA_ROOT.is_dir(), 'verified local data bundle absent')
class QueryConstraintIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.holder=tempfile.TemporaryDirectory()
        self.addCleanup(self.holder.cleanup)
        self.root=Path(self.holder.name)

    def test_wrong_tools_cannot_create_report_or_read_amounts(self):
        for q,flow in [('2026年5月美国大豆进口额是多少？','import'),
                       ('最近日本大豆进口多少？','import'),
                       ('最近美国向巴西出口的大豆多少？','export'),
                       ('最近美国大豆进口多少？','export')]:
            with self.subTest(q=q):
                t=TradeAgentTools(DATA_ROOT,self.root,question=q)
                t.search_products('大豆',flow)
                with patch('tradeintel_ai.trade_agent_tools.TradeDataRepository.query') as imp, \
                     patch('tradeintel_ai.trade_agent_tools.ExportDataRepository.query') as exp:
                    with self.assertRaises(ValueError):
                        t.query_trade(f'{flow}:1201',flow,'all',{'type':'latest_contiguous','count':1})
                    imp.assert_not_called();exp.assert_not_called()
                self.assertFalse(t.reports)

    def test_unsupported_request_is_saved_without_model_call(self):
        class NeverModel:
            def complete(self, **kwargs):
                raise AssertionError('No provider attempt allowed')
        agent=TradeResearchAgent(DATA_ROOT,self.root,NeverModel(),today=date(2026,9,30))
        rid=uuid.uuid4().hex
        first=agent.turn('日本大豆进口多少？',rid)
        self.assertEqual(first['turns'][-1]['status'],'needs_clarification')
        self.assertFalse(first['turns'][-1]['report_ids'])
        self.assertEqual(agent.turn('日本大豆进口多少？',rid),first)
        self.assertIn('request_constraints',read_session(self.root,first['session_id'])['turns'][-1])

    def test_repeated_wrong_direction_stops_after_one_correction(self):
        class WrongModel:
            calls=0
            def complete(inner,**kwargs):
                inner.calls+=1
                if inner.calls==1:
                    name,args='search_products',{'term':'大豆','flow':'export'}
                else:
                    name,args='query_trade',{'candidate_id':'export:1201','flow':'export',
                        'partner':'all','period':{'type':'latest_contiguous','count':1}}
                return ModelResponse(tool_calls=(ModelToolCall(uuid.uuid4().hex,name,args),))
        model=WrongModel()
        result=TradeResearchAgent(DATA_ROOT,self.root,model).turn('美国大豆进口多少？',uuid.uuid4().hex)
        self.assertEqual(result['turns'][-1]['status'],'needs_clarification')
        self.assertEqual(model.calls,3)
        self.assertFalse(result['turns'][-1]['report_ids'])

    def test_ambiguous_cotton_does_not_pick_one_product(self):
        t=TradeAgentTools(DATA_ROOT,self.root,question='美国棉花进口最近怎样？')
        t.search_products('棉花','import')
        with self.assertRaisesRegex(ValueError,'多个范围'):
            t.query_trade('import:5201','import','all',{'type':'latest_contiguous','count':1})
        self.assertFalse(t.reports)
        precise=TradeAgentTools(DATA_ROOT,self.root,question='美国未梳的棉花进口最近怎样？')
        self.assertFalse(precise.request_constraints['issues'])
        self.assertEqual(precise.request_constraints['product_anchors'],['5201'])
        coded=TradeAgentTools(DATA_ROOT,self.root,question='美国棉花 HS4 5201 进口')
        self.assertFalse(coded.request_constraints['issues'])
        self.assertEqual(coded.request_constraints['product_anchors'],['5201'])

    def test_missing_product_in_multi_product_answer_is_rejected(self):
        t=TradeAgentTools(DATA_ROOT,self.root,question='美国大豆和玉米进口分别怎样？')
        t.reports={'fake':report()}
        with self.assertRaisesRegex(ValueError,'全部商品'):
            t.validate_finish_period(['fake'])
