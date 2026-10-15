import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from automation.common import atomic_json

class AtomicJSONTests(unittest.TestCase):
    def test_transient_windows_sharing_conflict_retries_without_losing_data(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'progress.json';atomic_json(path,{'phase':1})
            original=os.replace;attempts=[]
            def replace(source,destination):
                attempts.append(1)
                if len(attempts)<3:
                    error=PermissionError('sharing conflict');error.winerror=5;raise error
                return original(source,destination)
            with patch('automation.common.os.replace',side_effect=replace),patch('automation.common.time.sleep'):
                atomic_json(path,{'phase':2})
            self.assertEqual(json.loads(path.read_text()),{'phase':2})
            self.assertEqual(len(attempts),3)
    def test_rejected_nonfinite_value_preserves_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checkpoint.json'
            atomic_json(path,{'state':'valid','text':'真实盘面'},indent=None)
            with self.assertRaises(ValueError):atomic_json(path,{'state':float('nan')})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),{'state':'valid','text':'真实盘面'})
