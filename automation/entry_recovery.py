"""Use spare real cells to align an entry to an unchanged certified policy.

No policy file or probability graph is changed. Only the two observed previews
are used; the resulting whole-game controller must be measured empirically.
"""
from collections import Counter
from . import game
from .bootstrap10240 import actions
from .opening128_40 import ContractExecutor
from .runtime import RouteFailure
from .route_runtime import StageExecutor
from .runtime import IncompatibleState


def match_completion_ids(state,fixed_ids,step):
    """Recognize an exact real match exit, with protected source provenance."""
    if step['kind']!='leaf' or step.get('exit')!='match':return None
    protected=[t for t in state['tower'] if fixed_ids.intersection(t.get('_sources',[t['id']]))]
    sources={s for t in protected for s in t.get('_sources',[t['id']])}
    if not fixed_ids<=sources:return None
    indices=[i for i,t in enumerate(state['tower']) if t in protected]
    if not indices or indices!=list(range(indices[0],indices[-1]+1)):return None
    actual=[[t['value'],t['physicalCount'],t['kind']=='group'] for t in protected]
    if actual!=step['after']:return None
    if any(t['kind']=='group' for t in state['tower'] if t not in protected):return None
    return {t['id'] for t in protected}


def leaf_completion_ids(state,fixed_ids,step,policy=None):
    ids=_leaf_completion_ids(state,fixed_ids,step)
    if ids is None:return None
    residual=[t for t in state['tower'] if t['id'] not in ids]
    if policy and policy.get('successNoExtraCombos') and any(t['kind']=='group' for t in residual):return None
    if policy and policy.get('singleTidyExit'):
        if len(residual)>1 or any(t['kind']!='tile' or t['value']>8 for t in residual):return None
    return ids


def _leaf_completion_ids(state,fixed_ids,step):
    """Complete ordinary/buffer leaves in spare real cells, using exact exits."""
    if step['kind']!='leaf':return None
    if step.get('exit')=='match':return match_completion_ids(state,fixed_ids,step)
    if step.get('exit')=='extend':
        return match_completion_ids(state,fixed_ids,{**step,'exit':'match'})
    if step.get('singleConnectionAfter') is not None:
        connected={**step,'exit':'match','after':step['singleConnectionAfter']}
        ids=match_completion_ids(state,fixed_ids,connected)
        if ids is None:return None
        residual=[t for t in state['tower'] if t['id'] not in ids]
        if len(residual)>1 or any(t['kind']!='tile' or t['value']>8 for t in residual):return None
        return ids
    if step.get('exit') not in ('single','buffer'):return None
    tower=state['tower'];positions=[i for i,t in enumerate(tower) if t['id'] in fixed_ids]
    if len(positions)!=len(fixed_ids):return None
    if positions and positions!=list(range(positions[0],positions[-1]+1)):return None
    candidates=[positions[-1]+1] if positions else range(len(tower))
    for index in candidates:
        if index>=len(tower):continue
        goal=tower[index]
        if goal['value']!=step['target']:continue
        if step['exit']=='single' and goal['kind']!='tile':continue
        if step['exit']=='buffer' and goal['physicalCount']>4:continue
        selected=positions+[index]
        actual=[[tower[i]['value'],tower[i]['physicalCount'],tower[i]['kind']=='group'] for i in selected]
        expected=step['after']
        if len(actual)!=len(expected):continue
        valid=all((got[0]==want[0] and 1<=got[1]<=want[1]) if len(want)==4 and want[3]
                  else got==want for got,want in zip(actual,expected))
        if valid:return {tower[i]['id'] for i in selected}
    return None


def recovery_action(obs,fixed_ids,target,maximum,seen=(),*,width=24,depth=6,diagnostics=None,completion=None,entry=None):
    original_order=[t['id'] for t in obs['tower'] if t['id'] in fixed_ids]
    def rank(state):
        active=[t for t in state['tower'] if t['id'] not in fixed_ids]
        occupied=sum(t['physicalCount'] for t in active)
        groups=sum(t['kind']=='group' for t in active)
        useful=sum(min(t['value'],target) for t in active if t['kind']=='tile' and target%t['value']==0)
        return -1000*occupied-250*groups+useful
    frontier=[(obs,None,0)];best=None;visited=set();entry_checks=0
    for _ in range(depth):
        following=[]
        for state,first,cost in frontier:
            for action in actions(state):
                try:after=game.predict(state,action)
                except (ValueError,IndexError):continue
                if after['gameOver']:continue
                terminal=completion is not None and completion(after) is not None
                if not terminal and not fixed_ids<={t['id'] for t in after['tower']}:continue
                if not terminal and fixed_ids:
                    positions=[i for i,t in enumerate(after['tower']) if t['id'] in fixed_ids]
                    if positions!=list(range(positions[0],positions[-1]+1)):continue
                    if [after['tower'][i]['id'] for i in positions]!=original_order:continue
                if not terminal and any(t['value']>maximum for t in after['tower'] if t['id'] not in fixed_ids):continue
                mark=(tuple(game.signature(after)),tuple(after['queue']))
                if mark in visited or mark in seen:continue
                visited.add(mark)
                total=cost+(1 if action['kind'] in ('drop','up','down') else .05)
                search_entry=(after,first or action,total)
                # Free bridges retain BOTH observed previews. Verify a real
                # policy macro before preferring re-entry over cell heuristics.
                viable=False
                if not terminal and entry is not None and total<1 and entry_checks<32:
                    entry_checks+=1;viable=entry(after)
                score=(1000000 if terminal else 100000 if viable else rank(after))-total
                if best is None or score>best[0]:best=(score,search_entry[1])
                if not terminal and not viable:following.append((score,search_entry))
        frontier=[search_entry for _,search_entry in sorted(following,key=lambda pair:pair[0],reverse=True)[:width]]
    if diagnostics is not None:
        diagnostics.update(bestScore=None if best is None else best[0],visitedStates=len(visited),entryChecks=entry_checks)
    return None if best is None else best[1]


class RecoveryExecutor(ContractExecutor):
    def reset(self):
        super().reset();self.recovery_counts=Counter();self.recovery_events=[];self.recovery_seen=set()

    def prepare_leaf_entry(self,obs,step):
        active=[t for t in obs['tower'] if t['id'] not in self.fixed_ids]
        if not any(t['kind']=='group' for t in active):return None
        action={'kind':'edge'}
        try:after=game.predict(obs,action)
        except ValueError:return None
        if after['gameOver'] or not self.fixed_ids<={t['id'] for t in after['tower']}:return None
        if any(t['kind']=='group' for t in after['tower'] if t['id'] not in self.fixed_ids):return None
        # A real free cleanup takes precedence over entry rotation/draws.
        self.recovery_events.append({'stage':self.stage,'reason':'pre-entry-residual-group-clear',
                                     'board':game.signature(obs),'queue':obs['queue'][:],'action':action})
        return action

    def _next(self,obs):
        try:return super()._next(obs)
        except RouteFailure as error:
            if str(error) not in ('fixed-policy-dead','fixed-policy-exit-rejected','five-cell-capacity','6-cell-capacity','fixed-policy-entry-outside-domain','residual-group-prevents-connection','fixed-policy-action-would-merge-protected-segment','boundary-alignment-unavailable'):
                raise
            if self.stage>=len(self.route['steps']) or self.recovery_counts[self.stage]>=48:raise
            step=self.route['steps'][self.stage]
            if step['kind'] not in ('leaf','group') or game.physical(obs)>=obs['towerLimit']:raise
            if step['kind']=='leaf':
                item=next(p for p in self.catalog['policies'] if p['id']==step['policy'])
                target,maximum=step['target'],item['maxValue']
            else:
                target=max(24,step['before'][-1][0]);maximum=max(48,target)
            mark=(tuple(game.signature(obs)),tuple(obs['queue']))
            self.recovery_seen.add(mark)
            completion=lambda state:leaf_completion_ids(state,self.fixed_ids,step,item if step['kind']=='leaf' else None)
            def available(state):
                if step['kind']!='leaf':return False
                active=[t for t in state['tower'] if t['id'] not in self.fixed_ids]
                if sum(t['physicalCount'] for t in active)>=item.get('cells',5):return False
                if any(t['value']>item['maxValue'] for t in active):return False
                if len(state['queue'])!=2 or any(v is None for v in state['queue']):return False
                probe=StageExecutor({'target':-1,'towerLimit':self.route['cells'],'kind':'stage','children':[step]},
                                    self.catalog,self.worker_factory)
                probe.workers=self.workers;probe.fixed_ids=self.fixed_ids.copy()
                try:
                    candidate=probe.next_action(state)
                    score=probe.search_events[-1].get('score') if probe.search_events else None
                    return (candidate is not None and probe.failure_reason is None
                            and (score is None or score>1e-10))
                except (RouteFailure,IncompatibleState):return False
            # The bridge is a real-board controller, not a query outside the
            # certified table. Oversized intermediate blocks must be reduced
            # below the original table bound before verified policy re-entry.
            bridge_maximum=max(maximum,96,4*target) if step['kind']=='leaf' else maximum
            diagnostics={}
            action=recovery_action(obs,self.fixed_ids,target,bridge_maximum,self.recovery_seen,
                                   completion=completion,entry=available if step['kind']=='leaf' else None,
                                   diagnostics=diagnostics)
            if action is None:raise
            self.recovery_counts[self.stage]+=1
            self.recovery_events.append({'stage':self.stage,'reason':str(error),'board':game.signature(obs),
                                         'queue':obs['queue'][:],'action':action,'bridgeMaxValue':bridge_maximum,
                                         'verifiedEntryPreferred':diagnostics['bestScore']>=90000,
                                         'entryChecks':diagnostics['entryChecks']})
            # Discard the aborted macro, retaining shared immutable workers.
            # The next observation starts the SAME leaf with its exact anchors.
            self.inner=None
            # An intended match may consume protected IDs only when real
            # source provenance and the entire prescribed exit agree exactly.
            completed=completion(game.predict(obs,action))
            if completed is not None:self.pending_ids=completed
            return action
