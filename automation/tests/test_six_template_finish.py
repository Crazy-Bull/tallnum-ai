import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from automation.six_template_finish import simulate_graph, validate_configuration


class SixTemplateEvaluationTests(unittest.TestCase):
    def test_target_specific_configuration(self):
        config={'cells':6,'target':32,'exit':'single','maxGoalCells':1,
                'maxValue':48,'bases':[1,3,5,15],'successSide':'above'}
        header={**config,'above':1}
        validate_configuration(config,header)
        with self.assertRaises(ValueError):
            validate_configuration(config,{**header,'target':40})
        with self.assertRaises(ValueError):
            validate_configuration(config,{**header,'maxValue':32})

    def graph(self, directory, kind, cost, successors):
        path=Path(directory)/'graph.bin'
        with path.open('wb') as out:
            out.write(b'TNGRAPH1'+struct.pack('<Q',len(kind)))
            out.write(np.asarray(kind,dtype='u1').tobytes())
            out.write(np.asarray(cost,dtype='u1').tobytes())
            out.write(np.asarray(successors,dtype='<u4').tobytes())
        return path

    def test_final_success_drop_and_restart_cost(self):
        # Every preview starts in a state paying one drop; half terminate
        # successfully with another drop, half fail without another drop.
        with tempfile.TemporaryDirectory() as directory:
            path=self.graph(directory,[0]*36+[1,2],[1]*36+[1,0],
                            [[36]*3+[37]*3]*36+[[0]*6]*2)
            result=simulate_graph(path,attempts=10000,seed=5)
        self.assertEqual(result['limits'],0)
        self.assertAlmostEqual(result['p'],.5,delta=.02)
        self.assertAlmostEqual(result['u'],2*result['p'])
        self.assertAlmostEqual(result['v'],1-result['p'])
        self.assertAlmostEqual(result['expectedTotalDrops'],result['c']/result['p'])

    def test_censored_loop_is_not_finite_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            path=self.graph(directory,[0]*36,[1]*36,[[0]*6]*36)
            result=simulate_graph(path,attempts=20,limit=7)
        self.assertEqual(result['limits'],20)
        self.assertEqual(result['meanObservedDrops'],7)
        self.assertIsNone(result['c'])
        self.assertIsNone(result['expectedTotalDrops'])

    def test_truncated_graph_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'graph.bin'
            path.write_bytes(b'TNGRAPH1'+struct.pack('<Q',36))
            with self.assertRaises(ValueError):simulate_graph(path)
