"""Integration checks against a real generated small policy, when available."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from automation.library import load_catalog, register, NATIVE_DIR, PolicyWorker

ROOT=Path(__file__).resolve().parents[2]
NATIVE=ROOT/'desktop/native/tallnum_automation.exe'
CATALOG=ROOT/'automation/runs/no80-dynamic/catalog.json'


@unittest.skipUnless(NATIVE.exists() and CATALOG.exists(),'build bridge and prepare five-cell fixtures first')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.item=next(p for p in load_catalog(CATALOG.parent)['policies']
                       if p['target']==24 and p['exit']=='single')

    def test_compact_queries_match_full_mdp(self):
        item=self.item
        query='0 0 2 4\n0 2 2 4 2 1 0 4 1 0\n9 0 2 4\n'
        cache=Path(item['policy']).with_suffix('.query.bin')
        if not cache.exists():
            self.skipTest('query cache has not been built')
        def call(args):
            p=subprocess.run([str(NATIVE),*map(str,args)],input=query,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr)
            return [json.loads(line) for line in p.stdout.splitlines() if line.startswith('{')]
        full=call([item['table'],item['policy'],'single','serve'])
        compact=call(['query',cache,'single'])
        self.assertEqual(full,compact)
        self.assertEqual(compact[-1]['status'],'error')

    def test_policy_identity_rejects_wrong_target(self):
        item=self.item
        with tempfile.TemporaryDirectory(prefix='tallnum-policy-identity-') as tmp:
            bad=Path(tmp)/'bad.policy.bin'
            data=bytearray(Path(item['policy']).read_bytes())
            # TALLPOL4 + version(uint32) + capacity(uint32) + target(uint32).
            data[16:20]=(99).to_bytes(4,'little')
            bad.write_bytes(data)
            result=subprocess.run([str(NATIVE),item['table'],str(bad),'single','serve'],
                                  input='',text=True,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('mismatch',result.stderr)

    def test_successful_draw_preserves_board_for_extension(self):
        item=next(p for p in load_catalog(CATALOG.parent)['policies']
                  if p['target']==16 and p['exit']=='extend' and p.get('maxValue',16)==16)
        worker=PolicyWorker(item)
        try:
            active=[{'value':v,'physicalCount':1,'kind':'tile'} for v in [6,8,15]]
            reply=worker.query(active,1,[8,8])
            self.assertEqual(reply['status'],'ok')
            self.assertTrue(reply['success'])
            goal=reply['board']['blocks'][reply['board']['fpos']]
            self.assertEqual(goal,{'value':16,'span':1,'combo':False})
        finally:
            worker.close()

    def test_uncertified_legacy_table_is_rejected(self):
        legacy=ROOT/'v4_5_128.bin'
        with tempfile.TemporaryDirectory(prefix='tallnum-old-rule-') as tmp:
            with self.assertRaisesRegex(ValueError,'old or uncertified EDGE rule'):
                register(tmp,legacy,self.item['source'],'single')

    def test_old_exit_statistics_cannot_be_used_as_certified(self):
        with tempfile.TemporaryDirectory(prefix='tallnum-exit-certification-') as tmp:
            base={'ruleSha256':'edge-recheck-v1','petsc':{'verified':True}}
            old=dict(base,id='old')
            one=dict(base,id='one',exitSemantics='success-board-v2',
                     petsc={'verified':True,'exitEvaluationRounds':1})
            current=dict(base,id='current',exitSemantics='success-board-v2',
                         petsc={'verified':True,'exitEvaluationRounds':2})
            (Path(tmp)/'catalog.json').write_text(json.dumps({'policies':[old,one,current]}))
            self.assertEqual([p['id'] for p in load_catalog(tmp,certified_only=True)['policies']],['current'])

    def test_bound_is_saved_and_checkpoint_cannot_change_bound(self):
        generator=NATIVE_DIR/'tallnum_reachable_legacy.exe'
        with tempfile.TemporaryDirectory(prefix='tallnum-bound-') as tmp:
            args=[str(generator),'--cells','3','--target','16','--max-value','32',
                  '--max-goal-cells','1','--output','table.bin','--checkpoint','search.ckpt']
            result=subprocess.run(args,cwd=tmp,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads((Path(tmp)/'table.bin.model.json').read_text())['maxValue'],32)
            args[args.index('32')]='48'
            resumed=subprocess.run(args,cwd=tmp,capture_output=True,text=True)
            self.assertNotEqual(resumed.returncode,0)
            self.assertIn('checkpoint rules mismatch',resumed.stderr)
