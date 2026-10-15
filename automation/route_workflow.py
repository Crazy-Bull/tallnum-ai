"""Resumable 640 preparation, 100-game selection, and optional live handoff."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time

from .common import atomic_json, event, execution_fingerprint
from .library import load_catalog
from .route_cli import main as route_command
from .route_search import RouteSearch, identity
from .route_baseline import legacy_structure
from .route_variants import manifest, prepare_variants
from .route_storage import prune_completed
from .validation import validate


def process_alive(pid):
    if os.name=='nt':
        import ctypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.restype=ctypes.c_void_p
        api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        api.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=api.OpenProcess(0x100000,False,pid)
        if not handle:
            error=ctypes.get_last_error()
            if error==87:return False
            raise OSError(error,'Unable to confirm old controller exit')
        try:return api.WaitForSingleObject(handle,0)==258
        finally:api.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


def run(directory,*,wait_baseline=False,play=False,previous=None,previous_pid=None):
    directory=Path(directory).resolve()
    config=json.loads((directory/'route-request.json').read_text(encoding='utf-8'))
    state_path=directory/'workflow.json'
    code_at_start=execution_fingerprint()
    def publish(stage,**data):
        atomic_json(state_path,{'stage':stage,'pid':os.getpid(),'updatedAt':time.time(),**data})
        event('workflow',stage=stage,**data)
    try:
        if wait_baseline:
            search=RouteSearch(directory,load_catalog(directory,certified_only=True),**config)
            baseline=legacy_structure(search)
            required={x['template']:search.requirement(x['target'],x['exit']) for x in baseline['steps'] if x['kind']=='leaf'}
            search.close()
            started=time.monotonic()
            while True:
                if execution_fingerprint()!=code_at_start:
                    raise RuntimeError('Execution code changed; restart the preparation workflow')
                prune_completed(directory)
                reports=[manifest(directory,r) for r in required.values()]
                missing=sum(len(r['missingAggressiveness']) for r in reports)
                if not missing:break
                publish('baseline-calculation',missingVariants=missing)
                if time.monotonic()-started>24*3600:raise RuntimeError('Baseline worker did not finish; inspect calculation logs')
                time.sleep(30)
        publish('structural-search',newNodeBudget=100000,batchSize=10000,candidateLimit=20)
        for batch in range(10):
            plan=route_command(['continue','--directory',str(directory),'--node-limit','10000'])
            publish('structural-search',batchesCompleted=batch+1,structures=len(plan['structures']),missingTemplates=len(plan['missing']))
            if plan['status']!='paused':break
        requirements=plan['requirements']
        for index,requirement in enumerate(sorted(requirements,key=lambda x:(x['target'],x['exit']))):
            prune_completed(directory)
            while shutil.disk_usage(directory).free<1024**3:
                publish('waiting-for-disk-space',minimumFreeBytes=1024**3)
                time.sleep(30)
            publish('template-calculation',completed=index,total=len(requirements),requirement=requirement)
            prepare_variants(directory,[requirement],1500)
        # A tiny continuation budget refreshes metrics without broadening the
        # already explored main graph. The CLI links the independent half route.
        plan=route_command(['continue','--directory',str(directory),'--node-limit','1'])
        if not plan['routes']:raise RuntimeError('No executable candidate in computed scope')
        for expansion in range(2):
            publish('validation',attemptsPerCandidate=100,holdoutAttempts=100,candidates=len(plan['routes']))
            validation=route_command(['validate','--directory',str(directory),'--attempts','100'])
            if expansion:break
            expanded={}
            by_id={r['id']:r for r in plan['routes']}
            for result in validation['results']:
                route=by_id[result['routeId']]
                for record in result['records']:
                    context=record.get('failureContext') or {}
                    if context.get('reason')!='fixed-policy-entry-outside-domain':continue
                    stage=context['stage']
                    if stage>=len(route['steps']):continue
                    step=route['steps'][stage]
                    if step['kind']!='leaf':continue
                    base=max(48,2*step['target']) if step['target']<48 else step['target']
                    key=step['template']
                    if config.get('template_bound_overrides',{}).get(key,base)>=2*base:continue
                    expanded[key]=min(config.get('max_value',2*config['target']),2*base)
            if not expanded:break
            config['template_bound_overrides']={**config.get('template_bound_overrides',{}),**expanded}
            atomic_json(directory/'route-request.json',config)
            plan=route_command(['continue','--directory',str(directory),'--node-limit','10000'])
            for requirement in plan['requirements']:
                prepare_variants(directory,[requirement],1500)
            plan=route_command(['continue','--directory',str(directory),'--node-limit','1'])
        if not validation['verified']:raise RuntimeError('No candidate passed the independent 100-game holdout; live play retained')
        selected=next(r for r in plan['routes'] if r['id']==validation['selectedRoute'])
        continuation=selected.get('continuation')
        if not continuation:raise RuntimeError('No executable half-boundary continuation')
        if not validation.get('continuationValidation',{}).get('verified'):
            raise RuntimeError('Continuation did not pass its independent 100-game checks')
        publish('ready',selectedRoute=selected['id'],validation=validation['holdout'],scope='bounded-candidates-not-global-optimum')
        if play:
            if previous:
                previous=Path(previous).resolve()
                # Ask the former controller to stop before taking its lease.
                atomic_json(previous/'control.json',{'mode':'stop','token':time.time_ns()})
                if previous_pid:
                    for attempt in range(120):
                        if not process_alive(previous_pid):break
                        time.sleep(1)
                    else:raise RuntimeError('Former controller did not exit; no handoff performed')
                from .controller_lock import controller_lease
                from .browser import play as browser_play
                from .runtime import IncompatibleState
                # New controllers hold a lease. Retry until it is released;
                # this never emits game input while another lease is active.
                for attempt in range(120):
                    try:
                        with controller_lease():pass
                        break
                    except RuntimeError:time.sleep(1)
                else:raise RuntimeError('Previous controller has not stopped')
                # Confirm journal stability for older controllers without leases.
                journal=previous/'actions.jsonl';stamp=journal.stat().st_mtime_ns if journal.exists() else None
                time.sleep(3)
                if journal.exists() and journal.stat().st_mtime_ns!=stamp:raise RuntimeError('Previous controller is still recording actions')
                old_route=json.loads((previous/'session.json').read_text(encoding='utf-8'))['route']
                atomic_json(previous/'control.json',{'mode':'run','stopAfterRound':True,'token':time.time_ns()})
                publish('finishing-previous-round',previous=str(previous))
                browser_play(old_route,load_catalog(previous,certified_only=True),previous,previous/'control.json',resume_current_game=True)
                atomic_json(previous/'control.json',{'mode':'stop','token':time.time_ns()})
            atomic_json(directory/'control.json',{'mode':'run','token':time.time_ns()})
            publish('live-play',selectedRoute=selected['id'])
            route_command(['play','--directory',str(directory), '--restart-settled-game' if previous else '--finish-current-game'])
    except Exception as error:
        publish('failed',error=str(error))
        raise


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--wait-baseline',action='store_true')
    parser.add_argument('--play',action='store_true')
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--previous-pid',type=int)
    args=parser.parse_args()
    run(args.directory,wait_baseline=args.wait_baseline,play=args.play,previous=args.previous,previous_pid=args.previous_pid)


if __name__=='__main__':main()
