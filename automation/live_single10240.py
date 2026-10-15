"""One independent original-route game with a live progress file and streamed replay."""
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
import threading
import time
import msvcrt
from automation import game
from automation.common import atomic_json, fingerprint
from automation.opening128_40 import build, ContractExecutor
from automation.single_six import use_single_six
from automation.full10240 import bind40
from automation.route_runtime import RouteExecutor

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'automation/runs/binary10240/min24/strict-match-edge-guard-003'
OUT=ROOT/'automation/runs/binary10240/min24/live-single-guard-001'
SEED=1121083590


def phase(route,start,end):
    result=deepcopy(route)
    result['steps']=result['steps'][start:end]
    result['initialPrefix']=result['steps'][0]['before']
    result['completionContract']=result['steps'][-1]['after']
    release=route.get('releaseAtStage')
    result['releaseAtStage']=release-start if release is not None and start<=release<end else None
    return result


def run():
    route=json.loads((SOURCE/'continuation40.json').read_text())
    catalog=json.loads((SOURCE/'catalog.json').read_text())
    opener,opening_catalog=build(catalog)
    opener,opening_catalog=use_single_six(opener,opening_catalog)
    combined={'policies':catalog['policies']+opening_catalog['policies']}
    atomic_json(OUT/'configuration.json',{'seed':SEED,'cells':10,'target':10240,'source':str(SOURCE),
                'routeSha256':fingerprint(SOURCE/'continuation40.json'),'sixCellExecution':route['sixCellExecution'],
                'sameRoute':True,'visiblePreviews':2,'forcedDraws':False,'separateFromBatch':True})
    state=game.new_game(SEED,10)
    initial=deepcopy(state)
    live={'pid':os.getpid(),'seed':SEED,'status':'running','phase':'opening','phaseOffset':0,
          'completedStages':0,'furthestCompletedStages':0,'totalStages':10+len(route['steps']),
          'maxOrdinaryEver':0,'maxCombinationEver':0,'milestones':{},'failureReason':None,
          'failureContext':None,'decisionStartedAt':None,'lastAction':None}
    mutex=threading.Lock()
    stopped=threading.Event()
    active=None
    offset=0

    def capture(status=None,decision=False,executor=None):
        nonlocal active
        if executor is not None:active=executor
        with mutex:
            if status:live['status']=status
            live['phaseOffset']=offset
            if active is not None:
                stage=active.stage
                live['completedStages']=offset+stage
                live['furthestCompletedStages']=max(live['furthestCompletedStages'],offset+stage)
                steps=active.route['steps']
                step=steps[stage] if stage<len(steps) else None
                live['activeStep']=({k:step.get(k) for k in ('kind','target','exit','policyCells','template','policy')}
                                    if step else None)
                if active.failure_reason and not live['failureReason']:
                    live['failureReason']=active.failure_reason
                    live['failureContext']=deepcopy(active.failure_context)
            ordinary=[t['value'] for t in state['tower'] if t['kind']=='tile']
            combos=[t['value'] for t in state['tower'] if t['kind']=='group']
            live['maxOrdinaryEver']=max(live['maxOrdinaryEver'],max(ordinary,default=0))
            live['maxCombinationEver']=max(live['maxCombinationEver'],max(combos,default=0))
            for goal in (128,320,640,1280,2560,5120,10240):
                if goal in ordinary:live['milestones'].setdefault(str(goal),state['drops'])
            live.update(drops=state['drops'],actions=state['actions'],board=game.signature(state),
                        queue=game.observation(state)['queue'],unlocked=state['unlocked'][:],gameOver=state['gameOver'])
            live['decisionStartedAt']=time.time() if decision else None

    def write():
        with mutex:row=deepcopy(live)
        row['updatedAt']=time.time()
        row['decisionSeconds']=row['updatedAt']-row['decisionStartedAt'] if row['decisionStartedAt'] else 0
        atomic_json(OUT/'progress.json',row)
        label={'opening':'开局','continuation':'10240路线','draining':'失败后投放至真实结束','replay-check':'原引擎回放核对'}
        step=row.get('activeStep') or {}
        text=f"# 10格10240 · 独立局实时追踪\n\n种子：{SEED}\n\n状态：{row['status']}；阶段：{label.get(row['phase'],row['phase'])}\n\n"
        text+=f"最远完成阶段：{row['furthestCompletedStages']} / {row['totalStages']}\n\n历史最大单格数：{row['maxOrdinaryEver']}\n\n投放数：{row.get('drops',0)}；操作数：{row.get('actions',0)}\n\n"
        text+=f"当前定式：{step.get('template') or step.get('kind') or '阶段衔接'}\n\n盘面（底部→顶部）：{row.get('board',[])}\n\n"
        if row['decisionStartedAt']:text+=f"正在计算下一步，已用 {row['decisionSeconds']:.1f} 秒。\n\n"
        if row['failureReason']:text+=f"策略失败原因：{row['failureReason']}\n\n"
        if row.get('originalEngineCheck'):text+='原JavaScript引擎回放核对：通过。\n'
        temp=OUT/'live-status.tmp'
        temp.write_text(text,encoding='utf-8');os.replace(temp,OUT/'live-status.md')

    def heartbeat():
        while not stopped.wait(2):write()

    capture();write()
    monitor=threading.Thread(target=heartbeat,daemon=True);monitor.start()
    executors=[]
    trace=OUT/'trace.jsonl'
    if trace.exists():raise RuntimeError('Single-game output already has a replay; use a fresh directory')
    try:
        with trace.open('w',encoding='utf-8') as log:
            def apply_action(action,executor=None,before=None):
                nonlocal state
                state=game.apply(state,action)
                if executor:executor.accept(before,action,game.observation(state))
                log.write(json.dumps({'action':action,'board':game.signature(state),'queue':state['queue'][:],
                          'unlocked':state['unlocked'][:],'rngState':state['rngState'],'gameOver':state['gameOver']})+'\n')
                log.flush()
                with mutex:live['lastAction']=action
                capture()

            anchors=None
            opening_ok=True
            for start,end in ((0,4),(4,10)):
                offset=start
                executor=ContractExecutor(phase(opener,start,end),combined);executors.append(executor)
                if anchors is not None:
                    executor.fixed_ids=anchors;executor.initial_bound=True
                    executor._contract(game.observation(state),executor.route['initialPrefix'])
                for _ in range(3000):
                    if state['gameOver']:opening_ok=False;break
                    capture(decision=True,executor=executor)
                    before=game.observation(state);action=executor.next_action(before)
                    capture()
                    if executor.failure_reason:opening_ok=False;break
                    if action is None:anchors=set(executor.fixed_ids);break
                    apply_action(action,executor,before)
                else:raise RuntimeError('Opening action budget reached')
                executor.close()
                if not opening_ok:break

            if opening_ok and not state['gameOver']:
                offset=10
                executor=RouteExecutor(route,catalog);executors.append(executor)
                bind40(executor,game.observation(state))
                with mutex:live['phase']='continuation'
                for _ in range(20000):
                    if state['gameOver'] or any(t['kind']=='tile' and t['value']==10240 for t in state['tower']):break
                    capture(decision=True,executor=executor)
                    before=game.observation(state);action=executor.next_action(before)
                    capture()
                    if action is None:
                        if not any(t['kind']=='tile' and t['value']==10240 for t in state['tower']):
                            raise RuntimeError('Route ended without ordinary 10240')
                        break
                    apply_action(action,executor,before)
                else:raise RuntimeError('Continuation action budget reached')

            if not any(t['kind']=='tile' and t['value']==10240 for t in state['tower']) and not state['gameOver']:
                with mutex:live['phase']='draining'
                for _ in range(20000):
                    if state['gameOver']:break
                    apply_action({'kind':'drop'})
                else:raise RuntimeError('Game-over drain budget reached')

        outcome='success' if any(t['kind']=='tile' and t['value']==10240 for t in state['tower']) else 'failure'
        capture()
        with mutex:live['phase']='replay-check';live['outcome']=outcome
        replay={'seed':SEED,'initial':initial,'trace':[json.loads(x) for x in trace.read_text().splitlines()], 'outcome':outcome}
        output=OUT/'validation.json'
        atomic_json(output,{'reports':[{'mode':'fresh-strict-opening-same-original-seeds','replays':[replay]}]})
        with (OUT/'replay-check.log').open('w',encoding='utf-8') as logfile:
            result=subprocess.run(['node',str(ROOT/'automation/binary_random_check.mjs'),str(output)],stdout=logfile,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError('Original JavaScript engine replay check failed')
        with mutex:
            live['originalEngineCheck']=json.loads(output.read_text())['originalEngineCheck']
            live['status']='completed'
        atomic_json(OUT/'final-state.json',state)
    except BaseException as error:
        with mutex:live['status']='error';live['error']=repr(error)
        raise
    finally:
        stopped.set();monitor.join()
        for executor in executors:executor.close()
        write()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'run.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('Independent single game is already running')
        if (OUT/'trace.jsonl').exists():raise SystemExit('This independent game has already started')
        run()

if __name__=='__main__':main()
