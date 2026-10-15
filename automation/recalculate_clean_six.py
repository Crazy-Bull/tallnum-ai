"""Recompute the commonly used six-cell single goals with clean exits."""
import json
from pathlib import Path
import subprocess
import sys

from .common import atomic_json
from .library import ROOT


def main():
    directory=Path('F:/TallnumData/tallnumai-six-cleanexit')
    directory.mkdir(parents=True,exist_ok=True)
    record=directory/'recalculation.json'
    state={'cells':6,'targets':[32,40,48],'maxValue':48,'exit':'single',
           'successNoExtraCombos':True,'completed':[],'failed':[]}
    atomic_json(record,state)
    command=[sys.executable,'-m','automation.six_template_compute','--targets',
             '32','40','48','--max-value','48','--aggressiveness','.01',
             '--data-root',str(directory/'models')]
    log=directory/'recalculation.log'
    with log.open('w',encoding='utf-8') as output:
        result=subprocess.run(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    state['returnCode']=result.returncode
    state['status']='completed' if result.returncode==0 else 'failed'
    for target in state['targets']:
        work=ROOT/f'automation/runs/six{target}-alpha001-cleanexit'
        manifest=work/'result.json'
        if manifest.exists():
            data=json.loads(manifest.read_text(encoding='utf-8'))
            (state['completed'] if data.get('successNoExtraCombos') and data.get('petsc',{}).get('exitEvaluationRounds',0)>=2
             else state['failed']).append({'target':target,'manifest':str(manifest),
                                           'probability':data.get('statistics',{}).get('p'),
                                           'error':None if data.get('petsc',{}).get('exitEvaluationRounds',0)>=2 else 'missing two PETSc checks'})
    atomic_json(record,state)
    if result.returncode:
        raise RuntimeError(log.read_text(encoding='utf-8',errors='replace')[-4000:])
    print(json.dumps(state,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
