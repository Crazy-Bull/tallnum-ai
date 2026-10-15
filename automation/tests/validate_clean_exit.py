"""Bounded end-to-end validation; does not register or replace library policies."""
import json
import os
from pathlib import Path
import subprocess

from automation.aggressive import PETSC_BIN
from automation.common import atomic_json
from automation.library import NATIVE_DIR, ROOT, table_header


def main():
    work=ROOT/'automation/runs/clean-exit-validation'
    work.mkdir(parents=True,exist_ok=True)
    bridge=NATIVE_DIR/'test_clean_exit_bridge.exe'
    (work/'legacy').mkdir(exist_ok=True)
    (work/'fresh').mkdir(exist_ok=True)
    def run(args,input=None,env=None):
        result=subprocess.run(list(map(str,args)),cwd=work,input=input,text=True,
                              capture_output=True,env=env)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout
    run([NATIVE_DIR/'tallnum_reachable_clean.exe','--cells',3,'--target',24,
         '--max-value',48,'--max-goal-cells',1,'--success-no-extra-combos','0',
         '--output','legacy/table.bin'])
    (work/'legacy').mkdir(exist_ok=True)
    # Creating the base in its own path above lets the stricter graph expand
    # just legacy success rows and retain every unaffected edge.
    reuse_output=run([NATIVE_DIR/'tallnum_reachable_clean.exe','--cells',3,'--target',24,
         '--max-value',48,'--max-goal-cells',1,'--success-no-extra-combos','1',
         '--reuse-table','legacy/table.bin','--output','table.bin'])
    assert 'reused transition rows' in reuse_output
    assert table_header(work/'table.bin')['successNoExtraCombos']
    run([NATIVE_DIR/'tallnum_reachable_clean.exe','--cells',3,'--target',24,
         '--max-value',48,'--max-goal-cells',1,'--success-no-extra-combos','1',
         '--output','fresh/table.bin'])
    run([NATIVE_DIR/'tallnum_vi_legacy.exe','table.bin',1500,'1e-10','values.bin'])
    run([NATIVE_DIR/'tallnum_vi_legacy.exe','fresh/table.bin',1500,'1e-10','fresh/values.bin'])
    output=run([bridge,'table.bin','values.bin','single','export','fixture'])
    metadata=json.loads(next(line for line in reversed(output.splitlines()) if line.startswith('{')))
    assert metadata['successNoExtraCombos']
    assert metadata['exitSemantics']=='success-board-clean-v3'
    fresh_out=run([bridge,'fresh/table.bin','fresh/values.bin','single','export','fresh/fixture'])
    fresh_metadata=json.loads(next(line for line in reversed(fresh_out.splitlines()) if line.startswith('{')))
    run([bridge,'table.bin','fixture.policy.bin','single','cache','query.bin'])
    assert (work/'query.bin').read_bytes()[:8]==b'TNQUERY3'
    queries='0 0 2 4\n0 2 2 4 2 1 0 4 1 0\n0 2 2 4 24 1 0 12 2 1\n'
    def answers(args):
        return [json.loads(line) for line in run(args,queries).splitlines() if line.startswith('{')]
    full=answers([bridge,'table.bin','fixture.policy.bin','single','serve'])
    compact=answers([bridge,'query','query.bin','single'])
    assert full==compact,(full,compact)
    assert not full[-1].get('success',False)
    env=os.environ.copy()
    env['PATH']=str(PETSC_BIN)+os.pathsep+env.get('PATH','')
    evaluations=[]
    for graph_name,prefix in (('fixture.graph.bin','reused'),('fresh/fixture.graph.bin','fresh')):
        for step,tolerance in ((1,'1e-11'),(2,'1e-12')):
            output=work/f'{prefix}-petsc-{step}.json'
            run([NATIVE_DIR/'petsc_graph_eval.exe',graph_name,output,
                 '-ksp_type','dgmres','-ksp_rtol',tolerance,'-ksp_atol','1e-13',
                 '-ksp_max_it',20000,'-pc_type','jacobi'],env=env)
            value=json.loads(output.read_text())
            assert value['converged'],value
            evaluations.append(value)
        pair=evaluations[-2:]
        assert abs(pair[0]['successProbability']-pair[1]['successProbability'])<1e-8
    assert abs(evaluations[0]['successProbability']-evaluations[2]['successProbability'])<1e-8
    result={'passed':True,'fixtureOnly':True,'cells':3,'target':24,'maxValue':48,
            'successNoExtraCombos':True,'cacheFormat':'TNQUERY3','fullCacheQueriesMatch':True,
            'incrementalReuseMatchesFresh':True,'reusedTransitionRows':True,
            'PETScFixedPolicyRounds':2,'evaluations':evaluations}
    atomic_json(work/'validation.json',result)
    print(json.dumps(result))


if __name__=='__main__':main()
