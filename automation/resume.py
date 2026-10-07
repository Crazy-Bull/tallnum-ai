"""Restore a route from confirmed observations without resetting the game."""
import json
from pathlib import Path

from .runtime import Executor, IncompatibleState
from .execution import create_executor, continuation_executor


def same_observation(a,b):
    return {k:v for k,v in a.items() if k!='revision'}=={k:v for k,v in b.items() if k!='revision'}


def restore_executor(route,catalog,journal,observed,worker_factory=None):
    records=[]
    with Path(journal).open(encoding='utf-8') as source:
        for line in source:
            record=json.loads(line)
            if 'before' not in record:
                continue
            if record['before']['actions']==0:
                records=[]
            records.append(record)
    if not records or records[0]['before']['actions']!=0:
        raise IncompatibleState('当前局缺少完整操作记录，无法恢复原路线阶段')
    executor=create_executor(route,catalog,worker_factory)
    try:
        previous=None
        for record in records:
            if record.get('routeId') and record['routeId']!=route.get('id'):
                raise IncompatibleState('Recorded route identity differs; board retained')
            before,after=record['before'],record['after']
            if previous is not None and not same_observation(previous,before):
                raise IncompatibleState('当前局操作记录不连续，已保留盘面')
            action=executor.next_action(before)
            if action is None:
                executor.close()
                executor=continuation_executor(route,catalog,before,worker_factory)
                action=executor.next_action(before)
            if action!=record['action']:
                raise IncompatibleState('当前路线与本局操作记录不同，已保留盘面')
            if route.get('version')==2 or getattr(executor,'is_virtual',False):
                executor.accept(before,action,after)
            else:executor.accept(before,action,after,legacy_opening=record.get('openingBoundaryVersion',1)<2)
            previous=after
        if not same_observation(previous,observed):
            if observed['actions']!=previous['actions']+1:
                raise IncompatibleState('实际盘面与已记录盘面不同，无法恢复原路线')
            stage=executor.stage
            action=executor.next_action(previous)
            if action is None:
                executor.close()
                executor=continuation_executor(route,catalog,previous,worker_factory)
                action=executor.next_action(previous)
            executor.accept(previous,action,observed)
            with Path(journal).open('a',encoding='utf-8') as file:
                file.write(json.dumps({'before':previous,'action':action,'after':observed,
                                       'openingBoundaryVersion':2,'stageBefore':stage,'recovered':True,
                                       'routeId':route.get('id'),'routeVersion':route.get('version',1),
                                       'executionPhase':'virtual' if getattr(executor,'is_virtual',False) else 'ordinary',
                                       **{k:records[-1].get(k) for k in ('roundSuccess','dropsToTarget','roundId')}},ensure_ascii=False)+'\n')
                file.flush()
        executor.restored_round={k:records[-1].get(k) for k in ('executionPhase','roundSuccess','dropsToTarget','roundId')}
        return executor
    except Exception:
        executor.close()
        raise
