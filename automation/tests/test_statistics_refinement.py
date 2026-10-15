import unittest
from unittest.mock import patch
import numpy as np

from automation.statistics import evaluate


class MomentRefinementTests(unittest.TestCase):
    def graph(self):
        # 50,000 transient states force the iterative solver branch. Each
        # pays one drop, then reaches success paying the final drop.
        n=50000
        return ([0]*n+[1],[1]*(n+1),np.vstack((np.full((n,6),n),np.zeros((1,6),dtype=int))))

    def test_tighten_precision_without_relaxing_residual_check(self):
        calls=[]
        def solver(matrix,rhs,**kwargs):
            calls.append(kwargs)
            return (rhs+1e-5 if len(calls)==1 else rhs.copy()),0
        with patch('automation.statistics.bicgstab',side_effect=solver):
            result=evaluate(*self.graph(),initial=[0])
        self.assertEqual(result['p'],1)
        self.assertEqual(result['expectedTotalDrops'],2)
        self.assertEqual(result['maxResidual'],0)
        self.assertLess(calls[1]['rtol'],calls[0]['rtol'])
        self.assertIsNotNone(calls[1]['x0'])

    def test_persistent_bad_solution_still_rejected(self):
        def solver(matrix,rhs,**kwargs):return rhs+1e-5,0
        with patch('automation.statistics.bicgstab',side_effect=solver) as solve:
            with self.assertRaisesRegex(RuntimeError,'Invalid moment solution'):
                evaluate(*self.graph(),initial=[0])
        self.assertEqual(solve.call_count,4)
