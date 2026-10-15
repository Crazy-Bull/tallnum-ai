"""Executor selection and virtual continuation shared by browser and resume."""
from copy import deepcopy
from . import game
from .runtime import Executor, VirtualBoundaryExecutor, RouteFailure, IncompatibleState, check_observed


def create_executor(route,catalog,worker_factory=None):
    cls=Executor
    if route.get('version')==2:
        from .route_runtime import RouteExecutor
        cls=RouteExecutor
        if route.get('browserOpeningContract'):
            from .opening128_40 import ContractExecutor
            cls=ContractExecutor
        if route.get('entryRecovery'):
            from .entry_recovery import RecoveryExecutor
            cls=RecoveryExecutor
    return cls(route,catalog,**({'worker_factory':worker_factory} if worker_factory else {}))


def continuation_executor(route,catalog,observation,worker_factory=None):
    if route.get('version')!=2:
        return VirtualBoundaryExecutor(route,catalog,observation,**({'worker_factory':worker_factory} if worker_factory else {}))
    return VirtualRouteExecutor(route,catalog,observation,worker_factory)


class VirtualRouteExecutor:
    is_virtual=True
    def __init__(self,route,catalog,observation,worker_factory=None):
        self.stage=0;self.inner=None;self.failure_reason=None
        self.recovery=None;self.deferred_action=None;self.recovery_seen=set()
        self.route=route;self.catalog=catalog;self.worker_factory=worker_factory
        target=route['target'];tower=observation['tower']
        continuation=route.get('continuation')
        anchors=[t for t in tower if t['kind']=='tile' and t['value']==target]
        if not continuation or not anchors:
            self.failure_reason='continuation-boundary-unavailable';return
        self.anchor_id=anchors[0]['id'];self.virtual_value=target//2
        self.last_actual=deepcopy(observation)
        self.aligning=tower[0]['id']!=self.anchor_id
        if not self.aligning:self._start_virtual(observation)

    def _start_virtual(self,observation):
        self.shadow=deepcopy(observation);self.shadow['tower'][0]['value']=self.virtual_value
        self.last_actual=deepcopy(observation)
        self.inner=create_executor(self.route['continuation'],self.catalog,self.worker_factory)
        self.inner.bind_initial(self.shadow)
        self.aligning=False

    def next_action(self,obs):
        if obs['gameOver']:raise RouteFailure(self.failure_reason or 'tower-full-after-target')
        if self.failure_reason:return {'kind':'drop'}
        if {k:v for k,v in obs.items() if k!='revision'}!={k:v for k,v in self.last_actual.items() if k!='revision'}:
            raise IncompatibleState('Real continuation board changed outside automation')
        if self.aligning:
            indices=[i for i,t in enumerate(obs['tower']) if t['id']==self.anchor_id]
            if not indices:self.failure_reason='continuation-anchor-lost';return {'kind':'drop'}
            return {'kind':'down' if indices[0]==len(obs['tower'])-1 else 'up'}
        if self.deferred_action is not None:
            action=self.deferred_action;self.deferred_action=None;return action
        action=self.inner.next_action(self.shadow);self.stage=self.inner.stage
        if action is None:self.failure_reason='virtual-target-completed';return {'kind':'drop'}
        if self.inner.failure_reason:
            if self.inner.failure_reason=='fixed-policy-action-would-merge-protected-segment':
                recovery=self._recover_edge(obs)
                if recovery is not None:return recovery
            self.failure_reason=self.inner.failure_reason
        return action

    def _recover_edge(self,obs):
        """Sacrifice small progress only when both boards retain the anchor.

        The abstract F hides decimal-head collisions. A real EDGE can clear
        those collisions and restart the half-boundary suffix. Probe the new
        policy against the complete shadow board before committing any input.
        """
        mark=(tuple(game.signature(obs)),tuple(obs['queue']))
        if mark in self.recovery_seen:return None
        self.recovery_seen.add(mark)
        action={'kind':'edge'}
        try:
            actual=game.predict(obs,action);shadow=game.predict(self.shadow,action)
        except ValueError:return None
        for board,value in ((actual,self.route['target']),(shadow,self.virtual_value)):
            if board['gameOver'] or not board['tower']:return None
            anchor=board['tower'][0]
            if anchor['id']!=self.anchor_id or anchor['kind']!='tile' or anchor['value']!=value:return None
        if game.physical(shadow)>=game.physical(self.shadow):return None
        projected=deepcopy(actual);projected['tower'][0]['value']=self.virtual_value
        if game.signature(projected)!=game.signature(shadow):return None
        candidate=create_executor(self.route['continuation'],self.catalog,self.worker_factory)
        candidate.bind_initial(shadow)
        # Reuse the existing native workers. Do not double the six-cell cache.
        candidate.workers=self.inner.workers
        try:following=candidate.next_action(shadow)
        except (RouteFailure,IncompatibleState,ValueError):return None
        if candidate.failure_reason or following is None:return None
        self.recovery=(candidate,following)
        return action

    def accept(self,before,action,after):
        check_observed(before,action,after)
        if self.failure_reason:return
        if self.recovery is not None:
            shadow=game.observation(game.predict(self.shadow,action));shadow['queue']=after['queue'][:]
            projected=deepcopy(after);projected['tower'][0]['value']=self.virtual_value
            if game.signature(projected)!=game.signature(shadow):
                raise IncompatibleState('Recovery changed the real/virtual boundary')
            self.inner,self.deferred_action=self.recovery;self.recovery=None
            self.shadow=shadow;self.last_actual=deepcopy(after);self.stage=self.inner.stage
            return
        if self.aligning:
            self.last_actual=deepcopy(after)
            if after['tower'] and after['tower'][0]['id']==self.anchor_id:
                self._start_virtual(after)
            return
        predicted=game.predict(self.shadow,action);predicted['queue']=after['queue'][:]
        shadow_after=game.observation(predicted)
        self.inner.accept(self.shadow,action,shadow_after)
        projected=deepcopy(after)
        for tile in projected['tower']:
            if tile['id']==self.anchor_id:tile['value']=self.virtual_value
        if game.signature(projected)!=game.signature(shadow_after):
            if any(t['kind']=='tile' and t['value']==self.inner.route['target'] for t in shadow_after['tower']):
                self.failure_reason='virtual-target-completed'
            else:raise IncompatibleState('Unexpected nonterminal virtual/real divergence')
        self.shadow=shadow_after;self.last_actual=deepcopy(after);self.stage=self.inner.stage

    def close(self):
        if self.inner:self.inner.close()
