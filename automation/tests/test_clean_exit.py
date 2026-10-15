"""Small real-model checks for victory semantics and checkpoint/cache identity."""
import json
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest

from automation.library import NATIVE_DIR, load_catalog, table_header
from automation.six_template_finish import validate_configuration

GENERATOR=NATIVE_DIR/'tallnum_reachable_clean.exe'


class CleanExitTests(unittest.TestCase):
    @unittest.skipUnless(GENERATOR.exists(),'Build clean-exit generator first')
    def test_incremental_reuse_matches_fresh_graph(self):
        def canonical(path):
            with path.open('rb') as file:
                def get(fmt):return struct.unpack(fmt,file.read(struct.calcsize(fmt)))
                self.assertEqual(file.read(8),b'TALLTRN4')
                _,_,_,count,_,_,bases=get('<IIIQIII')
                get('<'+'I'*bases)
                rows=[]
                for _ in range(count):
                    code,flags,n=get('<QBI');rows.append((code,flags,get('<'+'Q'*n)))
                boards=[]
                for _ in range(get('<Q')[0]):
                    n,fpos=get('<IB');boards.append((fpos,tuple(get('<HBB') for _ in range(n))))
            mask=(1<<54)-1
            return {(boards[c&mask],(c>>54)&7,(c>>57)&7):
                    (flags,frozenset((boards[t&mask],(t>>54)&7) for t in nxt))
                    for c,flags,nxt in rows}
        with tempfile.TemporaryDirectory(prefix='tallnum-reuse-') as temp:
            base=[str(GENERATOR),'--cells','3','--target','24','--max-value','48','--max-goal-cells','1']
            for name,args in [('old',['--success-no-extra-combos','0']),('fresh',[]),
                              ('reused',['--reuse-table','old.bin'])]:
                result=subprocess.run(base+args+['--output',name+'.bin'],cwd=temp,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(canonical(Path(temp)/'fresh.bin'),canonical(Path(temp)/'reused.bin'))

    def test_clean_catalog_cannot_reuse_old_certified_probability(self):
        base={'ruleSha256':'edge-recheck-v1',
              'petsc':{'verified':True,'exitEvaluationRounds':2}}
        old={**base,'id':'old','exitSemantics':'success-board-v2'}
        clean={**base,'id':'clean','exitSemantics':'success-board-clean-v3',
               'successNoExtraCombos':True}
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp)/'catalog.json').write_text(json.dumps({'policies':[old,clean]}))
            policies=load_catalog(temp,certified_only=True,clean_only=True)['policies']
            self.assertEqual([p['id'] for p in policies],['clean'])

    def test_configuration_cannot_use_legacy_table(self):
        config={'cells':6,'target':32,'exit':'single','maxGoalCells':1,
                'maxValue':48,'bases':[1,3,5,15],'successSide':'above',
                'successNoExtraCombos':True}
        header={**config,'above':1}
        validate_configuration(config,header)
        with self.assertRaisesRegex(ValueError,'successNoExtraCombos'):
            validate_configuration(config,{**header,'successNoExtraCombos':False})

    @unittest.skipUnless(GENERATOR.exists(),'Build clean-exit generator first')
    def test_generator_default_checkpoint_and_legacy_metadata(self):
        with tempfile.TemporaryDirectory(prefix='tallnum-clean-exit-') as temp:
            args=[str(GENERATOR),'--cells','3','--target','24','--max-value','48',
                  '--max-goal-cells','1','--output','table.bin','--checkpoint','search.ckpt']
            first=subprocess.run(args,cwd=temp,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            table=Path(temp)/'table.bin'
            self.assertTrue(table_header(table)['successNoExtraCombos'])
            resumed=subprocess.run(args,cwd=temp,capture_output=True,text=True)
            self.assertEqual(resumed.returncode,0,resumed.stderr)
            wrong=subprocess.run(args+['--success-no-extra-combos','0'],cwd=temp,capture_output=True,text=True)
            self.assertNotEqual(wrong.returncode,0)
            self.assertIn('checkpoint success rules mismatch',wrong.stderr)
            meta=Path(str(table)+'.model.json')
            meta.write_text(json.dumps({'maxValue':48}))
            self.assertFalse(table_header(table)['successNoExtraCombos'])
            meta.write_text(json.dumps({'maxValue':48,'successNoExtraCombos':'true'}))
            with self.assertRaisesRegex(ValueError,'successNoExtraCombos'):
                table_header(table)


if __name__=='__main__':unittest.main()
