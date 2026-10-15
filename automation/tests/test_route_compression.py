import unittest
from automation.route_compression import compress_match64,select_match64_policy


class CompressionTests(unittest.TestCase):
    def test_variant_changes_only_certified_match64_calls(self):
        route={'steps':[{'kind':'leaf','target':64,'exit':'match','policyCells':5,'policy':'old'},
                        {'kind':'leaf','target':32,'exit':'match','policyCells':5,'policy':'keep'}]}
        policy={'id':'risk64','target':64,'exit':'match','maxValue':64,'variantAggressiveness':.01,
                'petsc':{'verified':True,'exitEvaluationRounds':2}}
        result,catalog=select_match64_policy(route,{'policies':[]},policy)
        self.assertEqual([s['policy'] for s in result['steps']],['risk64','keep'])
        self.assertEqual(route['steps'][0]['policy'],'old')
        self.assertEqual(result['match64Variant']['calls'],1)
        policy['petsc']['exitEvaluationRounds']=1
        with self.assertRaises(ValueError):select_match64_policy(route,{'policies':[]},policy)

    def test_exact_cascade_reduces_calls_without_changing_exit(self):
        before=[[640,1,False],[64,1,False]];middle=before+[[32,1,False]];after=[[640,1,False],[128,1,False]]
        route={'cells':10,'steps':[{'kind':'leaf','target':32,'exit':'single','before':before,'after':middle},
                                  {'kind':'leaf','target':32,'exit':'match','before':middle,'after':after}]}
        catalog={'policies':[{'id':'certified64','target':64,'exit':'match','cells':5,'maxValue':64,
                              'petsc':{'verified':True,'exitEvaluationRounds':2}}]}
        result=compress_match64(route,catalog)
        self.assertEqual(len(route['steps']),2)
        self.assertEqual(len(result['steps']),1)
        self.assertEqual(result['steps'][0]['target'],64)
        self.assertEqual(result['steps'][0]['after'],after)
        self.assertEqual(result['steps'][0]['before'],before)
        catalog['policies'][0]['petsc']['exitEvaluationRounds']=1
        with self.assertRaises(ValueError):compress_match64(route,catalog)
