import gzip
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from automation.library import table_header,table_fingerprint,table_rule
from automation.common import fingerprint


class CompressedTableTests(unittest.TestCase):
    def test_logical_hash_header_and_rule_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            table=Path(tmp)/'table.bin'
            content=b'TALLTRN4'+struct.pack('<IIIQIII',4,5,36,36,1,1,1)+struct.pack('<I',9)
            model=Path(str(table)+'.model.json')
            model.write_text(json.dumps({'maxValue':48,'successNoExtraCombos':True}))
            Path(str(table)+'.rules.json').write_text(json.dumps({'ruleSha256':'edge-recheck-v1',
                'tableSha256':hashlib.sha256(content).hexdigest(),'modelSha256':fingerprint(model)}))
            with gzip.open(str(table)+'.gz','wb') as out:out.write(content)
            self.assertEqual(table_fingerprint(table),hashlib.sha256(content).hexdigest())
            self.assertEqual(table_header(table)['target'],36)
            self.assertEqual(table_header(table)['cells'],5)
            self.assertEqual(table_rule(table),'edge-recheck-v1')
            with gzip.open(str(table)+'.gz','wb') as out:out.write(content+b'changed')
            with self.assertRaises(ValueError):table_rule(table)
