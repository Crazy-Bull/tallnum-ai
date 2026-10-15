import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from automation.runtime import Executor

class CacheBuildMemoryTests(unittest.TestCase):
    def test_new_five_cell_cache_releases_existing_workers_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            old={'id':'old','target':32,'exit':'single','cells':6,'states':1,
                 'policy':str(Path(directory)/'old.policy.bin')}
            new={'id':'new','target':60,'exit':'single','cells':5,'states':1,
                 'policy':str(Path(directory)/'new.policy.bin')}
            class Existing:
                closed=False
                def close(self):self.closed=True
            previous=Existing()
            def factory(item):
                self.assertTrue(previous.closed)
                self.assertFalse(executor.workers)
                return Existing()
            leaf={'kind':'leaf','policy':'new','target':60,'exit':'single'}
            executor=Executor(leaf,{'policies':[old,new]},factory)
            executor.workers=OrderedDict([('old',previous)])
            executor._worker(leaf)
            self.assertEqual(list(executor.workers),['new'])
            executor.close()
