"""Recompute only requested five-cell match templates with the EDGE guard."""
from pathlib import Path
import json
import msvcrt
import os
import time
from automation.common import atomic_json
from automation.route_variants import prepare_variants, manifest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'automation/runs/match-edge-guard'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'run.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('A match EDGE guard recalculation is already running')
        requirements=[dict(key=f'5:{target}:match',target=target,exit='match',maxValue=maximum,
                      maxGoalCells=5,bases=[1,3,5,15],successNoExtraCombos=True,matchEdgeGuard=True,
                      aggressiveness=[0] if target<48 else [0,.001,.005,.01,.05])
                      for target,maximum in ((32,64),(40,80),(48,48))]
        atomic_json(OUT/'configuration.json',{'requirements':requirements,'excludedTargets':[64,96,128],
                    'guard':'TARGET // 10 == blocks[fpos].value // 10 forbids EDGE; match only',
                    'fixedPolicyPETScRounds':2})
        complete=[]
        try:
            for req in requirements:
                atomic_json(OUT/'progress.json',dict(stage='computing',pid=os.getpid(),target=req['target'],
                            completed=complete,updatedAt=time.time()))
                prepare_variants(OUT,[req],rounds=5000)
                report=manifest(OUT,req)
                complete.append(req['target'])
                atomic_json(OUT/f"result-{req['target']}.json",report)
                print(json.dumps({'stage':'target-complete','target':req['target']}),flush=True)
            atomic_json(OUT/'progress.json',dict(stage='completed',completed=complete,updatedAt=time.time()))
        except BaseException as error:
            atomic_json(OUT/'progress.json',dict(stage='error',completed=complete,error=str(error),updatedAt=time.time()))
            raise

if __name__=='__main__':main()
