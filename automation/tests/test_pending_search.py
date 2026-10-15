import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.common import fingerprint
from automation.library import PolicyWorker, current_rule
from automation.pending_search_mode import DEFAULT_BASELINE, DEFAULT_DYNAMIC, prepare
from automation.prepare_pending_search import ROOT


class FakeProcess:
    def __init__(self, *args, **kwargs):
        from io import StringIO
        self.args = args
        self.stdin = StringIO()
        self.stdout = StringIO('{"status":"ready"}\n{"status":"ok","score":0.75,"ops":[]}\n')
    def poll(self):
        return None


class StatusProcess(FakeProcess):
    def __init__(self, *args, second='ok', error=None, **kwargs):
        from io import StringIO
        self.args=args; self.stdin=StringIO()
        reply={'status':second,'score':0.6,'ops':[]}
        if error is not None: reply['error']=error
        self.stdout=StringIO('{"status":"ready"}\n'+json.dumps(reply)+'\n')


class PendingSearchTests(unittest.TestCase):
    def test_alternate_10240_mode_keeps_traditional_route_untouched(self):
        route_hash = fingerprint(DEFAULT_BASELINE / 'route.json')
        catalog_hash = fingerprint(DEFAULT_BASELINE / 'catalog.json')
        with tempfile.TemporaryDirectory() as tmp:
            mode = prepare(Path(tmp) / 'alternate', DEFAULT_DYNAMIC, DEFAULT_BASELINE)
            alternate = json.loads((Path(tmp) / 'alternate' / 'route.json').read_text(encoding='utf-8'))
            traditional = json.loads((DEFAULT_BASELINE / 'route.json').read_text(encoding='utf-8'))
            self.assertEqual(alternate, traditional)
            self.assertEqual(mode['mode'], 'pending-probability-search')
            self.assertEqual(len(mode['searchDefinitions']), 21)
            self.assertEqual(mode['searchScope'], 'all five-cell route leaves and buffer rescues plus six-cell single definitions')
            self.assertEqual(fingerprint(DEFAULT_BASELINE / 'route.json'), route_hash)
            self.assertEqual(fingerprint(DEFAULT_BASELINE / 'catalog.json'), catalog_hash)

    def test_all_five_cell_route_definitions_register_without_changing_traditional_mode(self):
        dynamic = ROOT / 'automation/runs/binary10240/min24/pending-search-all-five-001'
        route_hash = fingerprint(DEFAULT_BASELINE / 'route.json')
        catalog_hash = fingerprint(DEFAULT_BASELINE / 'catalog.json')
        with tempfile.TemporaryDirectory() as tmp:
            mode = prepare(Path(tmp) / 'all-five', dynamic, DEFAULT_BASELINE)
            self.assertEqual(len(mode['searchDefinitions']), 12)
            self.assertEqual({d['exit'] for d in mode['searchDefinitions']}, {'single','match','extend'})
            self.assertEqual(mode['searchScope'], 'all routed five-cell single, match, and extend definitions; six-cell singles stay traditional')
            self.assertFalse(mode['traditionalFilesModified'])
            self.assertEqual(fingerprint(DEFAULT_BASELINE / 'route.json'), route_hash)
            self.assertEqual(fingerprint(DEFAULT_BASELINE / 'catalog.json'), catalog_hash)

    def test_pending_probability_worker_uses_runtime_search_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = root / 'table.bin'; table.write_bytes(b'table')
            policy = root / 'policy.bin'; policy.write_bytes(b'fixed-policy-used-for-identity')
            pending = root / 'pending.bin'; pending.write_bytes(b'probabilities-only')
            meta = root / 'pending.json'
            item = {'id': '32-single-test', 'target': 32, 'exit': 'single', 'cells': 5,
                    'maxValue': 64, 'table': str(table), 'policy': str(policy),
                    'policySha256': fingerprint(policy), 'hashes': {'table': fingerprint(table)},
                    'pendingValue': str(pending), 'pendingValueSha256': fingerprint(pending),
                    'pendingValueMeta': str(meta), 'pendingNative': 'pending-search.exe'}
            meta.write_text(json.dumps({'format': 'TNPEND02',
                'pendingSha256': item['pendingValueSha256'], 'tableSha256': item['hashes']['table'],
                'policySha256': item['policySha256'], 'target': 32, 'exit': 'single',
                'successNoExtraCombos': True, 'matchEdgeGuard': False,
                'maxValue':64,'maxGoalCells':1,'cells':5}), encoding='utf-8')
            with patch('automation.library.table_rule', return_value=current_rule()), \
                 patch('automation.library.table_header', return_value={
                    'maxValue': 64, 'maxGoalCells':1,'cells':5,
                    'successNoExtraCombos': True, 'matchEdgeGuard': False}), \
                 patch('automation.library.subprocess.Popen', side_effect=FakeProcess):
                worker = PolicyWorker(item)
                result = worker.query([], 0, [4, 6])
                self.assertEqual(result['score'], 0.75)
                self.assertIn('0 0 4 6', worker.process.stdin.getvalue())

    def test_pending_metadata_rejects_mismatched_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = root / 'table.bin'; table.write_bytes(b'table')
            policy = root / 'policy.bin'; policy.write_bytes(b'fixed-policy-used-for-identity')
            pending = root / 'pending.bin'; pending.write_bytes(b'probabilities-only')
            meta = root / 'pending.json'
            item = {'id': '32-single-test', 'target': 32, 'exit': 'single', 'cells': 5,
                    'maxValue': 64, 'table': str(table), 'policy': str(policy),
                    'policySha256': fingerprint(policy), 'hashes': {'table': fingerprint(table)},
                    'pendingValue': str(pending), 'pendingValueSha256': fingerprint(pending),
                    'pendingValueMeta': str(meta), 'pendingNative': 'pending-search.exe'}
            meta.write_text(json.dumps({'format': 'TNPEND02',
                'pendingSha256': item['pendingValueSha256'], 'tableSha256': item['hashes']['table'],
                'policySha256': item['policySha256'], 'target': 32, 'exit': 'single',
                'successNoExtraCombos': True, 'matchEdgeGuard': True,
                'maxValue':64,'maxGoalCells':1,'cells':5}), encoding='utf-8')
            with patch('automation.library.table_rule', return_value=current_rule()), \
                 patch('automation.library.table_header', return_value={
                    'maxValue': 64, 'maxGoalCells':1,'cells':5,
                    'successNoExtraCombos': True, 'matchEdgeGuard': False}):
                with self.assertRaisesRegex(ValueError, 'metadata does not match'):
                    PolicyWorker(item)

    def test_pending_match_search_requires_guarded_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            table = root / 'table.bin'; table.write_bytes(b'table')
            policy = root / 'policy.bin'; policy.write_bytes(b'fixed-match-policy')
            pending = root / 'pending.bin'; pending.write_bytes(b'probabilities-only')
            meta = root / 'pending.json'
            item = {'id': '32-match-test', 'target': 32, 'exit': 'match', 'cells': 5,
                    'maxValue': 64, 'table': str(table), 'policy': str(policy),
                    'policySha256': fingerprint(policy), 'hashes': {'table': fingerprint(table)},
                    'pendingValue': str(pending), 'pendingValueSha256': fingerprint(pending),
                    'pendingValueMeta': str(meta), 'pendingNative': 'pending-search.exe'}
            meta.write_text(json.dumps({'format': 'TNPEND02',
                'pendingSha256': item['pendingValueSha256'], 'tableSha256': item['hashes']['table'],
                'policySha256': item['policySha256'], 'target': 32, 'exit': 'match',
                'successNoExtraCombos': True, 'matchEdgeGuard': True,
                'maxValue':64,'maxGoalCells':5,'cells':5}), encoding='utf-8')
            with patch('automation.library.table_rule', return_value=current_rule()), \
                 patch('automation.library.table_header', return_value={
                    'maxValue':64,'maxGoalCells':5,'cells':5,
                    'successNoExtraCombos':True,'matchEdgeGuard':True}), \
                 patch('automation.library.subprocess.Popen', side_effect=FakeProcess):
                worker = PolicyWorker(item)
                result = worker.query([], 0, [4, 6])
                self.assertEqual(result['score'], 0.75)
                self.assertIn('0 0 4 6', worker.process.stdin.getvalue())

    def test_six_cell_single_pending_worker_accepts_streamed_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);table=root/'table.bin';table.write_bytes(b'table')
            policy=root/'policy.bin';policy.write_bytes(b'fixed-six-cell-policy')
            pending=root/'pending.bin';pending.write_bytes(b'six-cell-probabilities')
            meta=root/'pending.json'
            item={'id':'clean-six40-test','target':40,'exit':'single','cells':6,'maxValue':48,
                  'table':str(table),'policy':str(policy),'policySha256':fingerprint(policy),
                  'hashes':{'table':fingerprint(table)},'pendingValue':str(pending),
                  'pendingValueSha256':fingerprint(pending),'pendingValueMeta':str(meta),
                  'pendingNative':'pending-search-six.exe'}
            meta.write_text(json.dumps({'format':'TNPEND02','pendingSha256':item['pendingValueSha256'],
                'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                'target':40,'exit':'single','successNoExtraCombos':True,'matchEdgeGuard':False,
                'maxValue':48,'maxGoalCells':1,'cells':6}),encoding='utf-8')
            with patch('automation.library.table_rule',return_value=current_rule()), \
                 patch('automation.library.table_header',return_value={'maxValue':48,'maxGoalCells':1,
                    'cells':6,'successNoExtraCombos':True,'matchEdgeGuard':False}), \
                 patch('automation.library.subprocess.Popen',side_effect=FakeProcess):
                worker=PolicyWorker(item)
                result=worker.query([],0,[2,4])
                self.assertEqual(result['score'],0.75)
                self.assertIn('0 0 2 4',worker.process.stdin.getvalue())

    def test_out_of_model_search_query_falls_back_to_the_same_fixed_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);table=root/'table.bin';table.write_bytes(b'table')
            policy=root/'policy.bin';policy.write_bytes(b'fixed-policy-used-for-identity')
            pending=root/'pending.bin';pending.write_bytes(b'probabilities-only')
            meta=root/'pending.json';cache=policy.with_suffix('.query.bin')
            cache.write_bytes(b'legacy-query-cache')
            meta.write_text(json.dumps({'format':'TNPEND02','pendingSha256':fingerprint(pending),
                'tableSha256':fingerprint(table),'policySha256':fingerprint(policy),'target':32,
                'exit':'single','successNoExtraCombos':True,'matchEdgeGuard':False,
                'maxValue':64,'maxGoalCells':1,'cells':5}),encoding='utf-8')
            cache.with_suffix('.json').write_text(json.dumps({'policy':fingerprint(policy),
                'table':fingerprint(table),'format':'TNQUERY3','maxValue':64,
                'successNoExtraCombos':True,'sha256':fingerprint(cache)}),encoding='utf-8')
            item={'id':'32-single-test','target':32,'exit':'single','cells':5,'maxValue':64,
                  'successNoExtraCombos':True,'matchEdgeGuard':False,
                  'table':str(table),'policy':str(policy),'policySha256':fingerprint(policy),
                  'hashes':{'table':fingerprint(table)},'pendingValue':str(pending),
                  'pendingValueSha256':fingerprint(pending),'pendingValueMeta':str(meta),
                  'pendingNative':'pending-search.exe'}
            meta.write_text(json.dumps({'format':'TNPEND02','pendingSha256':item['pendingValueSha256'],
                'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                'target':32,'exit':'single','successNoExtraCombos':True,'matchEdgeGuard':False,
                'maxValue':64,'maxGoalCells':1,'cells':5}),encoding='utf-8')
            calls=[]
            def process(*args,**kwargs):
                calls.append(args)
                return StatusProcess(*args,
                    second='error' if len(calls)==1 else 'ok',
                    error='out-of-model-board' if len(calls)==1 else None)
            with patch('automation.library.table_rule',return_value=current_rule()), \
                 patch('automation.library.table_header',return_value={'maxValue':64,'maxGoalCells':1,
                    'cells':5,'successNoExtraCombos':True,'matchEdgeGuard':False}), \
                 patch('automation.library.subprocess.Popen',side_effect=process):
                worker=PolicyWorker(item)
                result=worker.query([],0,[4,6])
                self.assertEqual(result['status'],'ok')
                self.assertEqual(result['searchFallback'],'out-of-model')
                self.assertEqual(len(calls),2)


if __name__ == '__main__':
    unittest.main()
