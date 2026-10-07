"""Browser and simulation execution of v2 prefix contracts on full real-rule boards."""
from collections import OrderedDict
from . import game
from .runtime import Executor, RouteFailure, IncompatibleState, check_observed
from .library import PolicyWorker


class StageExecutor(Executor):
    def _next_action(self, obs):
        if self.stage >= len(self.leaves):
            return None
        try:
            return super()._next_action(obs)
        except IncompatibleState as error:
            if str(error) in ('Illegal group', 'Cannot extend/nest existing Group'):
                raise RouteFailure('residual-group-blocked-policy') from error
            raise


class RouteExecutor:
    def __init__(self, route, catalog, worker_factory=PolicyWorker):
        if route.get('version') != 2 or route.get('kind') != 'stages':
            raise ValueError('Expected v2 stage route')
        self.route, self.catalog, self.worker_factory = route, catalog, worker_factory
        self.inner = None
        self.workers = OrderedDict()
        self.reset()

    def reset(self):
        self.inner = None
        self.stage = 0
        self.fixed_ids = set()
        self.pending_ids = None
        self.failure_reason = None
        self.failure_context = None
        self.entry_bridge_events = []
        self.buffer_rescue = None
        self.buffer_rescue_events = []
        self.search_events = []
        self.single_exit_events = []
        self.buffer_rescue_attempts = set()
        self.initial_bound=not bool(self.route.get('initialPrefix'))

    def bind_initial(self,obs):
        expected=self.route.get('initialPrefix',[])
        count=len(expected)
        actual=[[t['value'],t['physicalCount'],t['kind']=='group'] for t in obs['tower'][:count]]
        if actual!=expected:raise IncompatibleState('Initial protected prefix differs from observation')
        self.fixed_ids={t['id'] for t in obs['tower'][:count]}
        self.initial_bound=True

    def close(self):
        for worker in self.workers.values():
            worker.close()
        self.workers.clear()

    def _indices(self, obs):
        indices = [i for i, t in enumerate(obs['tower']) if t['id'] in self.fixed_ids]
        if len(indices) != len(self.fixed_ids) or indices and indices != list(range(indices[0], indices[-1]+1)):
            raise RouteFailure('protected-prefix-no-longer-contiguous')
        return indices

    def _contract(self, obs, expected):
        actual = [[obs['tower'][i]['value'], obs['tower'][i]['physicalCount'], obs['tower'][i]['kind']=='group']
                  for i in self._indices(obs)]
        if len(actual)!=len(expected):raise RouteFailure('stage-exit-contract-mismatch')
        for got,want in zip(actual,expected):
            if len(want)==4 and want[3]:
                if got[0]!=want[0] or not 1<=got[1]<=want[1]:raise RouteFailure('stage-exit-contract-mismatch')
            elif got!=want:raise RouteFailure('stage-exit-contract-mismatch')

    def next_action(self, obs):
        if not self.initial_bound:self.bind_initial(obs)
        if obs['towerLimit'] != self.route['cells'] or obs['numberSet'] != 'standard' or obs.get('poolVersion', 2) != 2:
            raise IncompatibleState('Route game configuration differs from observation')
        # Target is recognized even on a full terminal board, before abandonment.
        if any(t['kind']=='tile' and t['value']==self.route['target'] for t in obs['tower']):
            return None
        if obs['gameOver']:
            raise RouteFailure(self.failure_reason or 'tower-full')
        if self.failure_reason:
            return {'kind': 'drop'}
        try:
            return self._next(obs)
        except RouteFailure as error:
            self.failure_reason = str(error)
            self.failure_context={'stage':self.stage,'reason':str(error),'board':game.signature(obs),'queue':obs['queue'][:]}
            return {'kind': 'drop'}

    def _next(self, obs):
        if self.buffer_rescue is not None:
            return self._next_buffer_rescue(obs)
        while self.stage < len(self.route['steps']):
            step = self.route['steps'][self.stage]
            if self.inner is not None:
                action = self.inner.next_action(obs)
                self.search_events.extend(self.inner.search_events)
                self.inner.search_events.clear()
                if self.inner.failure_reason:
                    if self._start_buffer_rescue(obs, self.inner.failure_reason):
                        return self._next_buffer_rescue(obs)
                    raise RouteFailure(self.inner.failure_reason)
                if action is not None:
                    return action
                self.fixed_ids = set(self.inner.fixed_ids)
                self._contract(obs, step['after'])
                if step.get('policyCells')==6 and step.get('exit')=='single':
                    residual=[t for t in obs['tower'] if t['id'] not in self.fixed_ids]
                    policy=self.inner.policies[step['policy']]
                    tidy=(sum(t['physicalCount'] for t in residual)<=1
                          and all(t['kind']=='tile' and t['value']<=8 for t in residual))
                    self.single_exit_events.append({'stage':self.stage,'policy':step['policy'],
                        'residual':game.signature({'tower':residual}),'tidy':tidy,
                        'strict':bool(policy.get('singleTidyExit'))})
                    if policy.get('singleTidyExit') and not tidy:
                        raise RouteFailure('single-exit-residual-exceeds-limit')
                self.inner = None
                self.stage += 1
                continue
            self._contract(obs, step['before'])
            indices = self._indices(obs)
            if step['kind'] == 'leaf':
                # A same-head residual below a match anchor is a known risky
                # entrance: a later GROUP can turn it into an unhandled block.
                # Spend one certified buffer rescue before that happens.
                if (step.get('exit') == 'match' and indices
                        and any(t['kind'] == 'tile' and t['value'] != step['target']
                                and t['value']//10 == step['target']//10
                                for t in obs['tower'][:indices[0]])
                        and self._start_buffer_rescue(obs, 'risky-match-entry')):
                    return self._next_buffer_rescue(obs)
                capacity=step.get('policyCells',5)
                if self.route['cells']-sum(obs['tower'][i]['physicalCount'] for i in indices) < capacity:
                    raise RouteFailure('insufficient-five-cell-workspace' if capacity==5 else 'insufficient-policy-workspace')
                entry_action=self.prepare_leaf_entry(obs,step)
                if entry_action is not None:return entry_action
                leaf = {**step, 'kind': 'leaf'}
                wrapper = {'target': -1, 'towerLimit': self.route['cells'], 'kind': 'stage', 'children': [leaf]}
                self.inner = StageExecutor(wrapper, self.catalog, self.worker_factory)
                self.inner.workers = self.workers
                self.inner.fixed_ids = self.fixed_ids.copy()
                self.inner.entry_bridge_events = self.entry_bridge_events
                self.inner.entry_route_stage = self.stage
                continue
            action = {'kind': step['kind']}
            if step['kind'] == 'group':
                action['indices'] = [indices[i] for i in step['indices']]
                if any(t['kind']=='group' for t in obs['tower']):
                    raise RouteFailure('residual-group-prevents-connection')
            try:
                predicted = game.predict(obs, action)
            except ValueError as error:
                raise RouteFailure('connection-unavailable: '+str(error)) from error
            ids = {t['id'] for t in predicted['tower']
                   if self.fixed_ids.intersection(t.get('_sources', [t['id']]))}
            previous = self.fixed_ids
            self.fixed_ids = ids
            try:
                self._contract(predicted, step['after'])
            finally:
                self.fixed_ids = previous
            self.pending_ids = ids
            return action
        raise RouteFailure('route-finished-without-target')

    def _start_buffer_rescue(self, obs, reason):
        """Try a smaller same-head buffer, then EDGE away the match anchor."""
        if reason not in ('risky-match-entry', 'fixed-policy-dead', 'five-cell-capacity',
                          'fixed-policy-action-would-merge-protected-segment'):
            return False
        if self.stage in self.buffer_rescue_attempts or self.stage < 1:
            return False
        step = self.route['steps'][self.stage]
        if step.get('kind') != 'leaf' or step.get('exit') != 'match':
            return False
        # A match can consume an anchor made by another match (40→80 or
        # 32→64). Removing it must rewind to the leaf that started that chain.
        prefix = step['before'][:-1]
        rewind = next((i for i in range(self.stage - 1, -1, -1)
                       if self.route['steps'][i].get('before') == prefix), None)
        if rewind is None:
            return False
        target = step['target']
        choices = self.route.get('bufferRescuePolicies', {}).get(str(target), [])
        indices = self._indices(obs)
        if not choices or not indices:
            return False
        anchor = obs['tower'][indices[-1]]
        if anchor['kind'] != 'tile' or anchor['value'] != target:
            return False
        for policy_id in choices:
            item = self.catalog.get('policies', [])
            item = next((p for p in item if p['id'] == policy_id), None)
            if (item is None or item.get('exit') != 'buffer'
                    or item.get('cells') != step.get('policyCells', 5)
                    or item.get('maxValue', 0) < 48
                    or item.get('maxGoalCells', 5) > 4
                    or item['target'] == target
                    or item['target'] // 10 != target // 10):
                continue
            if (reason == 'risky-match-entry' and not any(
                    t['kind'] == 'tile' and t['value'] == item['target']
                    for t in obs['tower'][:indices[0]])):
                continue
            if reason == 'risky-match-entry':
                # Commit only when the ready buffer can be rotated next to
                # the anchor and the resulting EDGE safely restores the
                # previous contract. Other entries keep the normal match.
                try:
                    rotated = game.predict(obs, {'kind': 'up'})
                    anchor_pos = next(i for i, t in enumerate(rotated['tower'])
                                      if t['id'] == anchor['id'])
                    ready = rotated['tower'][anchor_pos+1]
                    reduced = game.predict(rotated, {'kind': 'edge'})
                    survivors = {t['id'] for t in reduced['tower']}
                    if (rotated['gameOver'] or reduced['gameOver']
                            or ready['value'] != item['target']
                            or ready['physicalCount'] > 4
                            or (self.fixed_ids-{anchor['id']}) - survivors
                            or anchor['id'] in survivors):
                        continue
                    self.fixed_ids = self.fixed_ids-{anchor['id']}
                    try:
                        self._contract(reduced, prefix)
                    finally:
                        self.fixed_ids.add(anchor['id'])
                except (ValueError, StopIteration, IndexError, RouteFailure):
                    continue
            leaf = {'kind': 'leaf', 'target': item['target'], 'exit': 'buffer',
                    'policy': policy_id, 'policyCells': item['cells']}
            wrapper = {'target': -1, 'towerLimit': self.route['cells'],
                       'kind': 'stage', 'children': [leaf]}
            rescue = StageExecutor(wrapper, self.catalog, self.worker_factory)
            rescue.workers = self.workers
            rescue.fixed_ids = self.fixed_ids.copy()
            if reason != 'risky-match-entry':
                direct_goal = (indices[-1]+1 < len(obs['tower'])
                    and obs['tower'][indices[-1]+1]['value'] == item['target']
                    and obs['tower'][indices[-1]+1]['physicalCount'] <= 4)
                if direct_goal:
                    try:
                        reduced = game.predict(obs, {'kind': 'edge'})
                        if (reduced['gameOver'] or anchor['id'] in
                                {t['id'] for t in reduced['tower']}):
                            continue
                        original_ids = self.fixed_ids
                        self.fixed_ids = original_ids-{anchor['id']}
                        try:
                            self._contract(reduced, prefix)
                        finally:
                            self.fixed_ids = original_ids
                    except (ValueError, RouteFailure):
                        continue
                else:
                    active, gap, _, _ = rescue._project(obs)
                    reply = rescue._worker(leaf).query(active, gap, obs['queue'])
                    if reply.get('status') != 'ok':
                        continue
            self.buffer_rescue_attempts.add(self.stage)
            self.buffer_rescue = {'executor': rescue, 'phase': 'buffer',
                                  'stage': self.stage, 'rewind': rewind,
                                  'policy': policy_id,
                                  'reason': reason, 'anchor': anchor['id'],
                                  'keep': self.fixed_ids - {anchor['id']},
                                  'actionsTaken': 0,
                                  'startBoard': game.signature(obs),
                                  'startQueue': obs['queue'][:]}
            self.inner = None
            return True
        return False

    def _next_buffer_rescue(self, obs):
        rescue = self.buffer_rescue
        if rescue['phase'] == 'buffer':
            action = rescue['executor'].next_action(obs)
            self.search_events.extend(rescue['executor'].search_events)
            rescue['executor'].search_events.clear()
            if rescue['executor'].failure_reason:
                failure = rescue['executor'].failure_reason
                self.buffer_rescue_events.append({'fromStage': rescue['stage'],
                    'policy': rescue['policy'], 'reason': rescue['reason'],
                    'outcome': 'unavailable', 'detail': failure,
                    'startBoard': rescue['startBoard'],
                    'startQueue': rescue['startQueue']})
                self.buffer_rescue = None
                if rescue['reason'] == 'risky-match-entry' and not rescue['actionsTaken']:
                    return self._next(obs)
                raise RouteFailure(rescue['reason'])
            if action is not None:
                return action
            rescue['phase'] = 'edge'
        if rescue['phase'] == 'edge':
            action = {'kind': 'edge'}
            try:
                predicted = game.predict(obs, action)
            except ValueError as error:
                raise RouteFailure('buffer-rescue-edge-unavailable') from error
            survivors = {t['id'] for t in predicted['tower']}
            if (predicted['gameOver'] or not rescue['keep'] <= survivors
                    or rescue['anchor'] in survivors):
                raise RouteFailure('buffer-rescue-damaged-prefix')
            old = self.fixed_ids
            self.fixed_ids = rescue['keep']
            try:
                self._contract(predicted, self.route['steps'][rescue['rewind']]['before'])
            finally:
                self.fixed_ids = old
            rescue['phase'] = 'edge-pending'
            return action
        raise IncompatibleState('Buffer rescue awaits observed EDGE')

    def prepare_leaf_entry(self,obs,step):
        return None

    def accept(self, before, action, after):
        check_observed(before, action, after)
        if self.failure_reason:
            return
        if self.buffer_rescue is not None:
            rescue = self.buffer_rescue
            if rescue['phase'] == 'edge-pending':
                self.fixed_ids = rescue['keep']
                self.stage = rescue['rewind']
                self.buffer_rescue_events.append({'fromStage': rescue['stage'],
                    'toStage': self.stage, 'policy': rescue['policy'],
                    'reason': rescue['reason'], 'outcome': 'recovered',
                    'startBoard': rescue['startBoard'],
                    'startQueue': rescue['startQueue'],
                    'before': game.signature(before),
                    'after': game.signature(after)})
                self.buffer_rescue = None
            else:
                rescue['executor'].accept(before, action, after)
                rescue['actionsTaken'] += 1
        elif self.inner is not None:
            self.inner.accept(before, action, after)
        elif self.pending_ids is not None:
            self.fixed_ids = self.pending_ids
            self.pending_ids = None
            self.stage += 1
