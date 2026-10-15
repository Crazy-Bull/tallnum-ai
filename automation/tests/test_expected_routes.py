import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.common import fingerprint
from automation.expected_routes import build_weights, score_route, search, standard, weight


def snapshot(charges):
    entries = {}
    for key,cost in charges.items():
        _, target, exit = key.split(':')
        stats = {'p': 1, 'u': cost, 'v': 0, 'usable': True, 'nonterminationProbability': 0}
        entries[key] = {'target': int(target), 'exit': exit, 'policyId': key,
                        'weightExact': str(weight(stats)), 'statistics': stats}
    return {'entries': entries, 'metric': '(u+v)/p', 'approximation': 'test local retry sum'}


class ExpectedRouteTests(unittest.TestCase):
    def test_small_bound_cannot_beat_correct_bound_by_cheaper_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root/'fixed.bin'
            policy.write_bytes(b'fixed')
            base = {'target': 8, 'exit': 'single', 'policy': str(policy),
                    'policySha256': fingerprint(policy), 'variantAggressiveness': 0,
                    'ruleSha256': 'edge-recheck-v1', 'exitSemantics': 'success-board-v2',
                    'petsc': {'verified': True, 'exitEvaluationRounds': 2},
                    'statistics': {'p': .5, 'u': 1, 'v': 2, 'usable': True}}
            catalog = root/'catalog.json'
            bad = {**base, 'id': 'old-bound', 'maxValue': 8}
            good = {**base, 'id': 'correct-bound', 'maxValue': 48,
                    'statistics': {'p': .5, 'u': 10, 'v': 20, 'usable': True}}
            catalog.write_text(json.dumps({'policies': [bad, good]}))
            report = build_weights([catalog])
            self.assertEqual(report['entries']['5:8:single']['policyId'], 'correct-bound')
            self.assertEqual(len(report['excluded']), 1)
            catalog.write_text(json.dumps({'policies': [bad]}))
            with self.assertRaises(ValueError):
                build_weights([catalog])

    def test_legacy_risk_zero_evaluation_is_not_a_zero_risk_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            policy=root/'policy.bin'
            policy.write_bytes(b'fixed')
            evidence=root/'actual.json'
            evidence.write_text(json.dumps({'input_aggressiveness':.05,'aggressiveness':0}))
            base={'target':128,'exit':'match','policy':str(policy),
                  'policySha256':fingerprint(policy),'aggressiveness':0,
                  'ruleSha256':'edge-recheck-v1','exitSemantics':'success-board-v2',
                  'statistics':{'p':.5,'u':100,'v':200,'usable':True}}
            legacy={**base,'id':'aggressive','statistics':{'p':.1,'u':1,'v':1,'usable':True},
                    'petsc':{'verified':True,'exitEvaluationRounds':2,'improvementResult':str(evidence)}}
            zero={**base,'id':'baseline','petsc':{'verified':True,'exitEvaluationRounds':2}}
            catalog=root/'catalog.json'
            catalog.write_text(json.dumps({'policies':[legacy,zero]}))
            result=build_weights([catalog],alpha=0)
            self.assertEqual(result['entries']['5:128:match']['policyId'],'baseline')
            self.assertEqual(result['entries']['5:128:match']['alpha'],0)
            self.assertEqual(len(result['excluded']),1)
            catalog.write_text(json.dumps({'policies':[legacy]}))
            with self.assertRaises(ValueError):build_weights([catalog],alpha=0)
            self.assertEqual(build_weights([catalog],alpha=.05)['entries']['5:128:match']['alpha'],.05)

    def test_restart_cost_not_single_attempt_cost(self):
        self.assertEqual(weight({'p': .25, 'u': 1, 'v': 2, 'usable': True}),12)
        for change in ({'p':0}, {'p':float('nan')}, {'usable':False}, {'nonterminationProbability':.1}):
            with self.assertRaises(ValueError):
                weight({'p':1,'u':1,'v':0,'usable':True,**change})

    def test_larger_peak_can_win_on_actual_weight(self):
        data = snapshot({'5:16:single':10, '5:16:match':10,
                         '5:32:single':1, '5:32:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            result = search(tmp,data,target=64,node_limit=0)
        self.assertTrue(result['minimumAdditiveWeightProvenInScope'])
        self.assertEqual(result['score']['totalWeight'],2)
        self.assertEqual(result['score']['leafCounts'],{'5:32:single':1,'5:32:match':1})
        self.assertFalse(result['globallyOptimal'])

    def test_match_has_separate_price_and_repeats_are_charged(self):
        data = snapshot({'5:16:single':3, '5:16:match':1,
                         '5:32:single':2, '5:32:match':9})
        with tempfile.TemporaryDirectory() as tmp:
            result = search(tmp,data,target=64,node_limit=0)
        self.assertEqual(result['score']['totalWeight'],6)
        self.assertEqual(result['score']['leafCounts'],{'5:16:single':1,'5:16:match':1,'5:32:single':1})

    def test_resume_and_changed_statistics_have_separate_caches(self):
        data = snapshot({'5:16:single':3,'5:16:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            partial = search(tmp,data,target=64,node_limit=1)
            complete = search(tmp,data,target=64,node_limit=0)
            repeated = search(tmp,data,target=64,node_limit=0)
            changed = search(tmp,snapshot({'5:16:single':6,'5:16:match':2}),target=64,node_limit=0)
        self.assertEqual(partial['status'],'paused')
        self.assertFalse(partial['minimumAdditiveWeightProvenInScope'])
        self.assertEqual(complete['score']['totalWeight'],8)
        self.assertEqual(repeated['nodesThisRun'],0)
        self.assertEqual(changed['score']['totalWeight'],16)
        self.assertNotEqual(changed['runIdentity'],complete['runIdentity'])

    def test_missing_cost_never_becomes_zero(self):
        data = snapshot({'5:16:single':3})
        scored = score_route({'steps':[{'kind':'leaf','target':16,'exit':'single'},
                                      {'kind':'leaf','target':16,'exit':'match'}]},data)
        self.assertIsNone(scored['totalWeight'])
        self.assertEqual(scored['missing'],['5:16:match'])
        self.assertFalse(scored['complete'])

    def test_one_certified_variant_and_no_nonstandard_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            policy_file=directory/'policy.bin'
            policy_file.write_bytes(b'fixed policy')
            policies=[]
            for target, alpha in ((16,0),(16,.01),(14,0)):
                policies.append({'id':str((target,alpha)), 'target':target,'exit':'single','maxValue':48,
                                 'policy':str(policy_file),'policySha256':fingerprint(policy_file),
                                 'aggressiveness':alpha,'ruleSha256':'edge-recheck-v1',
                                 'petsc':{'verified':True,'exitEvaluationRounds':2},
                                 'exitSemantics':'success-board-v2',
                                 'statistics':{'p':.5,'u':1,'v':2,'usable':True}})
            file=directory/'catalog.json'
            file.write_text(json.dumps({'policies':policies}))
            result=build_weights([file],alpha=.01)
        self.assertEqual(list(result['entries']),['5:16:single'])
        self.assertEqual(result['entries']['5:16:single']['alpha'],.01)
        self.assertEqual(result['entries']['5:16:single']['weight'],6)
        self.assertFalse(standard(54))
        self.assertFalse(standard(3))

    def test_moment_cache_reuses_graph_and_invalidates_changed_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            policy=directory/'policy.bin'
            policy.write_bytes(b'fixed policy')
            graph=directory/'baseline.graph.bin'
            graph.write_bytes(b'first graph')
            stats={'p':.5,'u':1,'v':2,'usable':True}
            file=directory/'catalog.json'
            file.write_text(json.dumps({'policies':[{
                'id':'baseline','target':16,'exit':'single','maxValue':48,'policy':str(policy),
                'policySha256':fingerprint(policy),'ruleSha256':'edge-recheck-v1',
                'petsc':{'verified':True,'exitEvaluationRounds':2},
                'exitSemantics':'success-board-v2','statistics':stats}]}))
            with patch('automation.statistics.evaluate_file', return_value=stats) as evaluate:
                first=build_weights([file],recalculate=True,measurement_directory=directory)
                build_weights([file],recalculate=True,measurement_directory=directory)
                self.assertEqual(evaluate.call_count,1)
                graph.write_bytes(b'changed graph')
                changed=build_weights([file],recalculate=True,measurement_directory=directory)
                self.assertEqual(evaluate.call_count,2)
            self.assertNotEqual(first['entries']['5:16:single']['graphSha256'],
                                changed['entries']['5:16:single']['graphSha256'])


if __name__ == '__main__':
    unittest.main()
