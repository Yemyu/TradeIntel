import unittest
from src.tradeintel_ai.evidence_transport import pack, unpack


class EvidenceTransportTests(unittest.TestCase):
    def test_nested_shared_evidence_is_lossless(self):
        shared = {'source':'a'*64, 'text':'原始政策限定'*40}
        original = {'products':[{'id':1,'source':shared},{'id':2,'source':shared}],
                    'unknown':None, 'empty':[], 'zero':0, 'false':False}
        self.assertEqual(unpack(pack(original)), original)
        self.assertEqual(original['products'][0]['source'], shared)

    def test_reserved_key_and_bad_reference_rejected(self):
        with self.assertRaises(ValueError): pack({'x':{'$ref':'original'}})
        for table in ({}, {'R1':{'$ref':'R1'}}):
            with self.assertRaises(ValueError):
                unpack({'encoding':'exact-value-references-v1', 'references':table,'evidence':{'$ref':'R1'}})

    def test_mixed_row_shapes_and_nested_tables_roundtrip(self):
        value = [{'amount':i,'sources':[{'id':'same'*20},{'id':'same'*20}]} for i in range(5)]
        value.extend([{'scope':'all'}, None, {'different':True}])
        self.assertEqual(unpack(pack(value)), value)
        self.assertEqual(unpack(pack([])), [])

    def test_invalid_table_is_rejected(self):
        for table in ({'$columns':['a','a'],'$rows':[[1,2]]},
                      {'$columns':['a'],'$rows':[[1,2]]}):
            with self.assertRaises(ValueError):
                unpack({'encoding':'exact-value-references-v1','references':{},'evidence':table})
