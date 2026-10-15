import contextlib
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from automation.stream_replay_report import emit,attach


class CompressedReplayTests(unittest.TestCase):
    def test_gzip_evidence_stream_and_check_preserve_report(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'validation.json.gz'
            replay={'seed':42,'initial':{'queue':[2,4]},'trace':[]}
            with gzip.open(file,'wt',encoding='utf-8') as stream:
                json.dump({'reports':[{'mode':'test','replays':[replay]}]},stream)
            before=file.read_bytes();output=io.StringIO()
            with contextlib.redirect_stdout(output):emit(file)
            self.assertEqual(json.loads(output.getvalue()),{'mode':'test','replay':replay})
            check={'games':1,'actions':0,'seededRngParity':True,'forcedDraws':False}
            attach(file,json.dumps(check))
            self.assertEqual(file.read_bytes(),before)
            self.assertEqual(json.loads(Path(str(file)+'.engine-check.json').read_text()),check)
            with self.assertRaises(ValueError):attach(file,json.dumps({**check,'games':2}))


if __name__=='__main__':unittest.main()
