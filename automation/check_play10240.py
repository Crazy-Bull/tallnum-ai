"""Check browser route assembly against the independent phase executors."""
import os
from copy import deepcopy
from . import game
from .play10240 import ROOT,prepare
from .execution import create_executor
from .opening128_40 import ContractExecutor
from .route_runtime import RouteExecutor
from .full10240 import bind40

def main():
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    route,catalog=prepare()
    opening=deepcopy(route)
    opening.update(steps=route['steps'][:10],target=-1,completionContract=[[40,1,False]])
    suffix=deepcopy(route)
    suffix.update(steps=route['steps'][10:],initialPrefix=[[40,1,False]])
    suffix.pop('browserOpeningContract',None)
    combined=create_executor(route,catalog)
    separate=ContractExecutor(opening,catalog)
    # Share immutable workers so the comparison does not load two cache copies.
    separate.workers=combined.workers
    state=game.new_game(1121083590,10)
    try:
        joined=False
        for count in range(2000):
            before=game.observation(state)
            expected=separate.next_action(before)
            if expected is None and not joined:
                separate=RouteExecutor(suffix,catalog)
                separate.workers=combined.workers
                bind40(separate,before)
                joined=True
                expected=separate.next_action(before)
            actual=combined.next_action(before)
            if actual!=expected or combined.failure_reason or separate.failure_reason:
                raise AssertionError((count,actual,expected,combined.failure_reason,separate.failure_reason))
            if joined:
                assert combined.fixed_ids==separate.fixed_ids
                print(f'PASS: {count} opening actions; dynamic continuation action and anchors agree')
                return
            state=game.apply(state,actual)
            after=game.observation(state)
            combined.accept(before,actual,after)
            separate.accept(before,expected,after)
        raise AssertionError('Opening action budget exceeded')
    finally:combined.close()

if __name__=='__main__':main()
