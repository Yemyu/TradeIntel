import unittest

from src.tradeintel_ai.product_scope import route_published_case


class ProductScopeTests(unittest.TestCase):
    def test_soybean_and_mixed_question_never_route_to_tungsten(self):
        for question in ('最近美国大豆贸易有什么变化', '美国大豆和钨的进口怎么样',
                         '美国铜和钨的进口怎么样', 'How are US soybean imports doing?'):
            with self.subTest(question=question):
                self.assertEqual(route_published_case(question)['status'], 'not_available')

    def test_tungsten_and_solar_select_only_asked_products(self):
        tungsten = route_published_case('最近美国钨进口情况怎么样？')
        self.assertEqual(tungsten['status'], 'supported_case')
        self.assertEqual(tungsten['selected_products'], ['81019400','81019910','81019980'])
        both = route_published_case('美国钨和光伏材料进口有什么变化？')
        self.assertEqual(len(both['selected_products']), 5)
        solar = route_published_case('美国光伏进口有什么变化？')
        self.assertEqual(solar['selected_products'], ['28046100','38180000'])

    def test_unknown_or_export_does_not_appear_supported(self):
        for question in ('最近美国进口有什么变化', '美国钨出口有什么变化',
                         '2025年美国钨进口怎么样', '美国钨进口同比怎么样',
                         '12019000 美国进口'):
            with self.subTest(question=question):
                self.assertNotEqual(route_published_case(question)['status'], 'supported_case')
