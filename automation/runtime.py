"""Compose executable leaves without projecting fixed blocks away blindly."""
from __future__ import annotations

from copy import deepcopy
from collections import OrderedDict
import os
from . import game
from .library import PolicyWorker


class RouteFailure(Exception):
    pass


class IncompatibleState(Exception):
    pass


def flatten(route):
    if route['kind'] == 'leaf':
        return [route]
    return [leaf for c in route['children'] for leaf in flatten(c)]


def check_observed(before, action, after):
    expected = game.predict(before, action)
    if (game.signature(expected) != game.signature(after) or expected['actions'] != after['actions']
            or expected['drops'] != after['drops'] or expected['gameOver'] != after['gameOver']):
        raise IncompatibleState('Observed board/count differs from prediction')
    if action['kind'] in ('drop','up','down'):
        if after['queue'][0] != before['queue'][1]:
            raise IncompatibleState('Preview did not advance once')
    elif before['queue'] != after['queue']:
        raise IncompatibleState('Free action changed preview')


class Executor:
    def __init__(self, route, catalog, worker_factory=PolicyWorker):
        self.route = route
        self.leaves = flatten(route)
        self.policies = {p['id']: p for p in catalog['policies']}
        for leaf in self.leaves:
            item=self.policies[leaf['policy']]
            if (item.get('target',leaf['target'])!=leaf['target']
                    or item.get('exit',leaf['exit'])!=leaf['exit']
                    or leaf['exit']=='single' and item.get('maxGoalCells',1)!=1
                    or leaf['exit']=='buffer' and item.get('maxGoalCells',4)>4):
                raise IncompatibleState('Leaf target/exit differs from its policy; single requires an ordinary one-cell goal')
            if leaf.get('policyCells',item.get('cells',5))!=item.get('cells',5):
                raise IncompatibleState('Leaf workspace differs from its policy')
        self.workers = OrderedDict()
        self.worker_factory = worker_factory
        self.reset()

    def reset(self):
        self.stage = 0
        self.fixed_ids = None
        self.queue = []
        self.finish_after_queue = False
        self.pending_expected = None
        self.final_fixed_indices = None
        self.virtual_gap = 0
        self.macro_board = None
        self.free_seen = set()
        self.failure_reason = None
        self.entry_bridge_events = []
        self.entry_bridge_probe = False
        self.search_events = []
        self.real_board_excluded = {}
        self.real_board_query = None

    def close(self):
        for worker in self.workers.values():
            worker.close()
        self.workers.clear()

    def _worker(self, leaf):
        item=self.policies[leaf['policy']]
        key = item.get('workerKey',leaf['policy'])
        if key not in self.workers:
            # Building any new query cache can load the full transition table
            # and multiple work arrays, even for a five-cell template.
            if (not getattr(self.worker_factory,'transient_query_cache',False)
                    and not item.get('pendingValue') and item.get('policy')
                    and not os.path.exists(os.path.splitext(item['policy'])[0]+'.query.bin')):
                for worker in self.workers.values():worker.close()
                self.workers.clear()
            budget = int(os.environ.get('TALLNUM_POLICY_CACHE_MB','2048'))*1024*1024
            estimate = lambda k: (os.path.getsize(self.policies[k]['pendingValue'])*2
                                  if self.policies[k].get('pendingValue') else
                                  int(self.policies[k].get('states',0))*28)
            while self.workers and sum(estimate(k) for k in self.workers)+estimate(key)>budget:
                _, worker = self.workers.popitem(last=False)
                worker.close()
            self.workers[key] = self.worker_factory(item)
        self.workers.move_to_end(key)
        return self.workers[key]

    def _project(self, obs):
        tower = obs['tower']
        fixed = [i for i,t in enumerate(tower) if t['id'] in self.fixed_ids]
        if len(fixed) != len(self.fixed_ids) or fixed and fixed != list(range(fixed[0], fixed[-1]+1)):
            raise IncompatibleState('Fixed segment changed or split')
        active_indices = [i for i,t in enumerate(tower) if t['id'] not in self.fixed_ids]
        fpos = fixed[0] if fixed else self.virtual_gap
        return [tower[i] for i in active_indices], fpos, active_indices, fixed

    def _advance(self, obs):
        self.stage += 1
        self.fixed_ids = {obs['tower'][i]['id'] for i in self.final_fixed_indices}
        self.final_fixed_indices = None
        self.free_seen.clear()
        self.finish_after_queue = False

    def _single_connection_indices(self, predicted, leaf):
        """Accept only the prescribed real merge of an ordinary single producer.

        The real equal anchor can merge before the virtual F model calls the
        single goal terminal. All prefix sources and the exact post-connection
        shape must survive; a different collision cannot finish this step.
        """
        expected = leaf.get('singleConnectionAfter')
        if leaf['exit'] != 'single' or expected is None or not self.fixed_ids:
            return None
        if self.fixed_ids <= {t['id'] for t in predicted['tower']}:
            return None
        protected = [i for i, t in enumerate(predicted['tower'])
                     if self.fixed_ids.intersection(t.get('_sources', [t['id']]))]
        sources = {s for i in protected for s in predicted['tower'][i].get(
            '_sources', [predicted['tower'][i]['id']])}
        actual = [[predicted['tower'][i]['value'], predicted['tower'][i]['physicalCount'],
                   predicted['tower'][i]['kind'] == 'group'] for i in protected]
        if (predicted['gameOver'] or not protected or not self.fixed_ids <= sources
                or protected != list(range(protected[0], protected[-1] + 1))
                or actual != expected
                or any(t['kind'] == 'group' for i, t in enumerate(predicted['tower'])
                       if i not in protected)):
            return None
        if not self._tidy_single_exit(leaf,[t for i,t in enumerate(predicted['tower']) if i not in protected]):
            return None
        return protected

    def _tidy_single_exit(self,leaf,residual):
        if not self.policies[leaf['policy']].get('singleTidyExit',False):
            return True
        return (sum(t['physicalCount'] for t in residual)<=1
                and all(t['kind']=='tile' and t['value']<=8 for t in residual))

    def accept(self, before, action, after, legacy_opening=False):
        check_observed(before,action,after)
        if action['kind'] in ('drop','up','down'):
            self.free_seen.clear()
        if self.failure_reason is not None:
            # The route has been abandoned, but the real game must finish so
            # its normal score/replay submission panel becomes available.
            return
        if not self.fixed_ids:
            # F is virtual in the opening. Preserve its position when the real
            # macro matches the model, so the next query follows that policy.
            # Extra real merges across the empty F invalidate this projection.
            if not legacy_opening and not self.queue and self.macro_board is not None:
                actual=[(t['value'],t['physicalCount'],t['kind']=='group') for t in after['tower']]
                wanted=[(t['value'],t['span'],t['combo']) for t in self.macro_board['blocks']]
                self.virtual_gap=self.macro_board['fpos'] if actual==wanted else 0
            elif legacy_opening or self.macro_board is None:
                self.virtual_gap=0
        elif not self.queue and not self.finish_after_queue and self.macro_board is not None:
            active, _, _, _ = self._project(after)
            actual = [(t['value'],t['physicalCount'],t['kind']=='group') for t in active]
            wanted = [(t['value'],t['span'],t['combo']) for t in self.macro_board['blocks']]
            if actual != wanted:
                raise IncompatibleState('Real macro differs from fixed-policy model')
            self.virtual_gap = self.macro_board['fpos']
        if self.finish_after_queue and not self.queue:
            self._advance(after)

    def next_action(self, obs):
        if obs['numberSet'] != 'standard' or obs['towerLimit'] != self.route.get('towerLimit', 7) or obs.get('poolVersion',2) != 2:
            raise IncompatibleState('Requires Standard seven-cell poolVersion 2')
        if self.failure_reason is not None:
            if obs['gameOver']:
                raise RouteFailure(self.failure_reason)
            return {'kind':'drop'}
        try:
            return self._next_action(obs)
        except (RouteFailure,IncompatibleState) as error:
            invalid_terminal=str(error) in ('Missing ordinary exit','Ordinary goal is not adjacent to protected segment',
                                           'No ordinary extension exit','Expected neighboring equal block to merge',
                                           'Terminal protected segment is not contiguous','Extension did not normalize')
            alternatives_enabled=(self.real_board_query is not None or
                any(p.get('realBoardAlternatives') for p in getattr(self,'policies',{}).values()))
            if isinstance(error,IncompatibleState) and (not invalid_terminal or not alternatives_enabled):
                raise
            if ((str(error) in ('fixed-policy-action-would-merge-protected-segment',
                              'fixed-policy-exit-rejected','fixed-policy-next-entry-rejected',
                              'single-exit-residual-exceeds-limit','single-exit-has-extra-group') or invalid_terminal)
                    and self.real_board_query is not None):
                key,post=self.real_board_query
                excluded=self.real_board_excluded.setdefault(key,[])
                if len(excluded)<32 and post not in excluded:
                    excluded.append(post)
                    self.queue.clear();self.macro_board=None;self.finish_after_queue=False
                    self.free_seen.discard((self.stage,tuple(game.signature(obs)),tuple(obs['queue'])))
                    return self.next_action(obs)
            if obs['gameOver']:
                raise
            self.failure_reason = 'fixed-policy-exit-rejected' if invalid_terminal else str(error)
            self.queue.clear()
            self.finish_after_queue = False
            self.macro_board = None
            return {'kind':'drop'}

    def _next_action(self, obs):
        if obs['gameOver']:
            raise RouteFailure('tower-full')
        if any(t['kind']=='tile' and t['value']==self.route['target'] for t in obs['tower']):
            return None
        if self.stage >= len(self.leaves):
            raise IncompatibleState('Route ended without final ordinary target')
        if self.queue:
            return self.queue.pop(0)
        leaf = self.leaves[self.stage]
        if self.fixed_ids is None:
            self.fixed_ids = set()  # website opening 2,4 belongs to first task
        active, fpos, mapping, fixed = self._project(obs)
        # Terminal boards are not all present in the reachable-state table:
        # the original enumerator stops at success. Recognize the real exit
        # before attempting a dictionary lookup.
        if leaf['exit'] in ('single','buffer'):
            goal_index = fixed[-1]+1 if fixed else next(
                (i for i,t in enumerate(obs['tower']) if t['kind']=='tile' and t['value']==leaf['target']), -1)
            if 0<=goal_index<len(obs['tower']):
                goal=obs['tower'][goal_index]
                clean = (not self.policies[leaf['policy']].get('successNoExtraCombos')
                         or not any(t['kind']=='group' for t in active if t['id']!=goal['id']))
                clean = clean and self._tidy_single_exit(leaf,[t for t in active if t['id']!=goal['id']])
                if clean and goal['value']==leaf['target'] and (goal['kind']=='tile' if leaf['exit']=='single' else goal['physicalCount']<=4):
                    self.final_fixed_indices=fixed+[goal_index]
                    self._advance(obs)
                    return self.next_action(obs)
        elif leaf['exit']=='extend' and len(fixed)>=2:
            # A predecessor may leave an ordinary b immediately above 2a.
            # Such terminal boards are intentionally absent from the table.
            goal_index=fixed[-1]+1
            if goal_index<len(obs['tower']):
                goal=obs['tower'][goal_index]
                selected=[fixed[-1],goal_index]
                if (goal['kind']=='tile' and goal['value']==leaf['target']
                        and not any(t['kind']=='group' for t in obs['tower'])
                        and obs['tower'][selected[0]-1]['value']==sum(obs['tower'][i]['value'] for i in selected)):
                    self._check_extension(obs,selected)
                    after=game.predict(obs,{'kind':'group','indices':selected})
                    if after['gameOver']:
                        raise RouteFailure('predicted-tower-full')
                    self.final_fixed_indices=[i for i,t in enumerate(after['tower'])
                                              if self.fixed_ids.intersection(t.get('_sources',[t['id']]))]
                    self.finish_after_queue=True
                    self.macro_board=None
                    return {'kind':'group','indices':selected}
        capacity=self.policies[leaf['policy']].get('cells',5)
        if sum(t['physicalCount'] for t in active) >= capacity:
            raise RouteFailure('five-cell-capacity' if capacity==5 else f'{capacity}-cell-capacity')
        item=self.policies[leaf['policy']]
        minimum=item.get('equivalentProtectedMinimum')
        maximum=item.get('maxValue')
        expected=item.get('singleProtectedValue')
        equivalent=(item.get('exit')=='single' and fixed and isinstance(minimum,int)
                    and isinstance(maximum,int) and isinstance(expected,int)
                    and minimum>=10*(maximum//10+1) and expected>=minimum
                    and obs['tower'][fixed[-1]]['value']>=minimum)
        if not equivalent and item.get('singleProtectedHead') is not None:
            if not fixed or obs['tower'][fixed[-1]]['value']//10!=item['singleProtectedHead']:
                raise IncompatibleState('Explicit single boundary head differs from actual protected anchor')
        if not equivalent and item.get('singleProtectedValue') is not None:
            if not fixed or obs['tower'][fixed[-1]]['value']!=item['singleProtectedValue']:
                raise IncompatibleState('Explicit single boundary value differs from actual protected anchor')
        self.real_board_query=None
        if item.get('realBoardAlternatives'):
            key=(leaf['policy'],tuple(game.signature(obs)),tuple(obs['queue']))
            reply=self._worker(leaf).query(active,fpos,obs['queue'],self.real_board_excluded.get(key,()))
            if reply.get('post') is not None:self.real_board_query=(key,reply['post'])
        else:
            reply = self._worker(leaf).query(active, fpos, obs['queue'])
        if self.policies[leaf['policy']].get('pendingValue'):
            self.search_events.append({'stage': self.stage, 'target': leaf['target'],
                'routeStage':getattr(self,'entry_route_stage',None),'policy':leaf['policy'],
                'cells':capacity,'fpos':fpos,'activeBoard':game.signature({'tower':active}),
                'error':reply.get('searchError') or reply.get('error'),
                'score': reply.get('score'), 'status': reply.get('status'),
                'searchFallback': reply.get('searchFallback'),
                'ops': reply.get('ops', []), 'board': game.signature(obs),
                'queue': obs['queue'][:]})
        if reply['status'] == 'dead':
            raise RouteFailure('fixed-policy-dead')
        if reply['status'] == 'incompatible-exit':
            raise RouteFailure('fixed-policy-exit-rejected')
        if reply.get('error') in ('out-of-model-board','out-of-model-state'):
            if self.entry_bridge_probe:
                raise RouteFailure('fixed-policy-entry-outside-domain')
            if fixed and fpos > 0:
                from .entry_bridge import find_entry_bridge
                from .route_runtime import StageExecutor

                def viable(candidate):
                    projected, gap, _, _ = self._project(candidate)
                    response = self._worker(leaf).query(projected, gap, candidate['queue'])
                    if response.get('status') != 'ok':
                        return False
                    # A dictionary hit alone is insufficient: compile the
                    # policy against the real protected segment as well.
                    probe = StageExecutor({'target': -1, 'towerLimit': candidate['towerLimit'],
                                           'kind': 'stage', 'children': [leaf]},
                                          {'policies': list(self.policies.values())}, self.worker_factory)
                    probe.workers = self.workers
                    probe.fixed_ids = self.fixed_ids.copy()
                    probe.entry_bridge_probe = True
                    try:
                        probe.next_action(candidate)
                        return probe.failure_reason is None
                    except (RouteFailure, IncompatibleState, ValueError):
                        return False

                bridge = find_entry_bridge(obs, self.fixed_ids, leaf,
                                           self.policies[leaf['policy']], viable)
                if bridge is not None:
                    self.macro_board = None
                    self.queue = bridge['actions'][1:]
                    self.entry_bridge_events.append({'stage': getattr(self, 'entry_route_stage', self.stage),
                                                    'policy': leaf['policy'],
                                                    'board': game.signature(obs), 'queue': obs['queue'][:],
                                                    **bridge})
                    return bridge['actions'][0]
            # A successful predecessor can leave only blocks BELOW F, which
            # are absent from tables generated from an empty active region.
            # Deterministically rotate one such block upward (one real drop),
            # then re-query. This is boundary alignment, not a six-cell search.
            if fixed and fpos>0:
                action={'kind':'up'}
                after=game.predict(obs,action)
                connected = self._single_connection_indices(after, leaf)
                if connected is not None:
                    self.final_fixed_indices=connected
                    self.finish_after_queue=True
                    self.macro_board=None
                    return action
                surviving_ids={t['id'] for t in after['tower']}
                tail=obs['tower'][fixed[-1]]
                prefix_ids=self.fixed_ids-{tail['id']}
                # Alignment can itself complete a match: [8,F(48,16)]
                # with incoming 8 rotates to [48,32]. Losing the tail's ID
                # is then the intended terminal merge, not boundary damage.
                goal=next((i for i,t in enumerate(after['tower'])
                           if t['kind']=='tile' and t['value']==2*leaf['target']
                           and tail['id'] in t.get('_sources',[]) and t['id']!=tail['id']),None)
                if (not after['gameOver'] and leaf['exit']=='match' and tail['value']==leaf['target']
                        and prefix_ids<=surviving_ids and goal is not None):
                    protected=[i for i,t in enumerate(after['tower']) if t['id'] in prefix_ids or i==goal]
                    if protected==list(range(protected[0],protected[-1]+1)):
                        self.final_fixed_indices=protected
                        self.finish_after_queue=True
                        self.macro_board=None
                        return action
                if after['gameOver'] or not self.fixed_ids <= surviving_ids:
                    raise RouteFailure('boundary-alignment-unavailable')
                self.macro_board=None
                return action
            # A prescribed conservative abort, not an input/recognition error.
            # Such entries can occur under the small-target approximation or
            # correlated exits; their spent drops remain in failure statistics.
            raise RouteFailure('fixed-policy-entry-outside-domain')
        if reply['status'] != 'ok':
            raise IncompatibleState(reply.get('error', reply['status']))
        self.macro_board = reply.get('board')
        mark = (self.stage, tuple(game.signature(obs)), tuple(obs['queue']))
        if mark in self.free_seen:
            raise RouteFailure('fixed-policy-free-action-cycle')
        self.free_seen.add(mark)
        # Compile one macro against the full tower; retain IDs of protected
        # blocks. Index mappings are recomputed after every free action.
        current = deepcopy(obs)
        actions = []
        ops = reply['ops']
        single_connected = None
        for index, op in enumerate(ops):
            _, _, indices, fixed = self._project(current)
            action = {'kind': op['kind']}
            if not self.fixed_ids and len(current['tower']) < 2 and action['kind'] in ('up','down'):
                action['kind'] = 'drop'
            if op['kind'] == 'group':
                selected = indices[op['l']:op['r']+1]
                if len(selected) != op['r']-op['l']+1:
                    raise IncompatibleState('Group mapping failed')
                model_board=op.get('board',{})
                model_blocks=model_board.get('blocks',[])
                goal_pos=model_board.get('fpos',0)
                creates_goal_group=(goal_pos<len(model_blocks) and (model_blocks[goal_pos]['combo']
                                    or self.policies[leaf['policy']].get('extensionExit'))
                                    and model_blocks[goal_pos]['value']==leaf['target'])
                if (reply['success'] and leaf['exit']=='extend' and index==len(ops)-1 and creates_goal_group
                        and sum(current['tower'][i]['value'] for i in selected)==leaf['target']):
                    if not fixed or selected[0] != fixed[-1]+1:
                        raise IncompatibleState('Extended group is not adjacent')
                    selected = [fixed[-1]] + selected
                    self._check_extension(current, selected)
                action['indices'] = selected
            try:
                after = game.predict(current, action)
            except ValueError as error:
                raise IncompatibleState(str(error)) from error
            # Before the terminal operation all fixed blocks must survive.
            terminal_op = reply['success'] and index==len(ops)-1
            connected = self._single_connection_indices(after, leaf) if op['kind'] != 'edge' else None
            if connected is not None:
                actions.append(action);current=after
                single_connected=connected
                reply['success']=True;self.macro_board=None
                break
            # A real boundary can finish a match before the virtual policy
            # reports success. Verify the whole exit and all protected sources.
            if leaf.get('allowEarlyRealMatch') and leaf.get('exit')=='match' and leaf.get('after'):
                protected=[i for i,t in enumerate(after['tower'])
                           if self.fixed_ids.intersection(t.get('_sources',[t['id']]))]
                sources={s for i in protected for s in after['tower'][i].get('_sources',[after['tower'][i]['id']])}
                actual=[[after['tower'][i]['value'],after['tower'][i]['physicalCount'],after['tower'][i]['kind']=='group']
                        for i in protected]
                if (protected and protected==list(range(protected[0],protected[-1]+1))
                        and self.fixed_ids<=sources and actual==leaf['after']):
                    actions.append(action);current=after
                    reply['success']=True;self.macro_board=None
                    break
            if not terminal_op:
                ids = {t['id'] for t in after['tower']}
                if not self.fixed_ids <= ids:
                    raise RouteFailure('fixed-policy-action-would-merge-protected-segment')
            actions.append(action)
            current = after
            # The public site's Edge recomputes decimal heads after each
            # merge, unlike the historical temporary-head model. When a
            # checked real free action diverges, discard the remaining macro
            # and query the same fixed policy at the observed successor.
            if op.get('board') and self.fixed_ids <= {t['id'] for t in current['tower']}:
                projected, _, _, _ = self._project(current)
                real = [(t['value'],t['physicalCount'],t['kind']=='group') for t in projected]
                model = [(t['value'],t['span'],t['combo']) for t in op['board']['blocks']]
                if real != model:
                    if op['kind']=='edge' or not self.fixed_ids:
                        self.macro_board=None
                        reply['success']=False
                        break
                    if not terminal_op:
                        raise IncompatibleState('Unexpected model divergence during preflight')
        if reply['success']:
            kind = leaf['exit']
            if kind == 'extend':
                # Ordinary b exits use a new two-block group with the lower 2a.
                surviving = [i for i,t in enumerate(current['tower']) if t['id'] in self.fixed_ids]
                if len(surviving)==len(self.fixed_ids):
                    i = surviving[-1] if surviving else -1
                    if i<1 or i+1>=len(current['tower']) or current['tower'][i+1]['value']!=leaf['target']:
                        raise IncompatibleState('No ordinary extension exit')
                    selected = [i, i+1]
                    self._check_extension(current, selected)
                    action = {'kind':'group','indices':selected}
                    current = game.predict(current, action)
                    actions.append(action)
                # Result must be an ordinary double of the matching boundary.
                if not any(t['id'] not in self.fixed_ids and t['kind']=='tile' for t in current['tower']):
                    raise IncompatibleState('Extension did not normalize')
            elif kind == 'buffer':
                # Buffer keeps its lower anchor until EDGE; equal buffers can
                # instead normalize immediately into an ordinary doubled tile.
                surviving=self.fixed_ids <= {t['id'] for t in current['tower']}
                if not surviving:
                    tail=obs['tower'][fixed[-1]] if fixed else None
                    if tail is None or tail['value']!=leaf['target']:
                        raise RouteFailure('buffer-damaged-protected-anchor')
            elif kind == 'single' and single_connected is None:
                if not any(t['id'] not in self.fixed_ids and t['kind']=='tile' and t['value']==leaf['target'] for t in current['tower']):
                    raise IncompatibleState('Missing ordinary exit')
            elif kind != 'single':
                if self.fixed_ids and self.fixed_ids <= {t['id'] for t in current['tower']}:
                    raise IncompatibleState('Expected neighboring equal block to merge')
            protected = [i for i,t in enumerate(current['tower'])
                         if self.fixed_ids.intersection(t.get('_sources', [t['id']]))]
            if kind=='single' and single_connected is None or kind=='buffer' and self.fixed_ids <= {t['id'] for t in current['tower']}:
                boundary = max(protected)+1 if protected else next(
                    (i for i,t in enumerate(current['tower']) if t['kind']=='tile' and t['value']==leaf['target']), -1)
                if boundary >= len(current['tower']) or current['tower'][boundary]['value'] != leaf['target']:
                    raise IncompatibleState('Ordinary goal is not adjacent to protected segment')
                if kind=='buffer' and current['tower'][boundary]['physicalCount']>4:
                    raise RouteFailure('buffer-exceeds-four-cells')
                protected.append(boundary)
            if (self.policies[leaf['policy']].get('successNoExtraCombos')
                    and any(t['kind']=='group' for i,t in enumerate(current['tower']) if i not in protected)):
                raise RouteFailure('single-exit-has-extra-group')
            if not self._tidy_single_exit(leaf,[t for i,t in enumerate(current['tower']) if i not in protected]):
                raise RouteFailure('single-exit-residual-exceeds-limit')
            if not protected or protected != list(range(protected[0], protected[-1]+1)):
                raise IncompatibleState('Terminal protected segment is not contiguous')
            expected=leaf.get('singleConnectionAfter') or leaf.get('after')
            if expected:
                actual=[[current['tower'][i]['value'],current['tower'][i]['physicalCount'],
                         current['tower'][i]['kind']=='group'] for i in protected]
                valid=len(actual)==len(expected) and all(
                    (got[0]==want[0] and 1<=got[1]<=want[1]) if len(want)==4 and want[3]
                    else got==want for got,want in zip(actual,expected))
                if not valid:raise RouteFailure('fixed-policy-exit-rejected')
            handoff=getattr(self,'handoff_validator',None)
            if handoff is not None and not handoff(current,protected):
                raise RouteFailure('fixed-policy-next-entry-rejected')
            self.final_fixed_indices = protected
            self.finish_after_queue = True
        if current['gameOver']:
            # Never execute a terminal projection which the real game loses.
            raise RouteFailure('predicted-tower-full')
        if not actions:
            if reply['success']:
                self._advance(obs)
                return self.next_action(obs)
            raise IncompatibleState('Empty nonterminal macro')
        self.queue = actions
        return self.queue.pop(0)

    @staticmethod
    def _check_extension(obs, selected):
        tower = obs['tower']
        if selected[0]<1 or len(selected)>5 or selected != list(range(selected[0], selected[-1]+1)):
            raise IncompatibleState('Illegal extension range')
        if any(t['kind']=='group' for t in tower):
            raise IncompatibleState('Cannot extend/nest existing Group')
        if tower[selected[0]-1]['value'] != sum(tower[i]['value'] for i in selected):
            raise IncompatibleState('Missing lower equal-value boundary')


class VirtualBoundaryExecutor:
    is_virtual=True
    is_virtual=True
    """Reuse the right half with a virtual boundary; verify all real inputs.

    Only policy selection sees the half-value boundary. The site/save is never
    changed. A virtual terminal merge may leave a real Group beside the larger
    anchor; after this first divergence only ordinary finishing drops are safe.
    """
    def __init__(self, route, catalog, observation, worker_factory=PolicyWorker):
        self.stage=0
        self.failure_reason=None
        self.inner=None
        self.anchor_id=None
        target=route['target']
        tower=observation['tower']
        if (route.get('kind')!='binary' or len(route.get('children',[]))!=2
                or not tower or tower[0]['kind']!='tile' or tower[0]['value']!=target):
            self.failure_reason='continuation-boundary-unavailable'
            return
        self.anchor_id=tower[0]['id']
        self.virtual_value=target//2
        self.shadow=deepcopy(observation)
        self.shadow['tower'][0]['value']=self.virtual_value
        continuation={'target':target,'kind':'binary','children':[route['children'][1]]}
        self.inner=Executor(continuation,catalog,worker_factory)
        self.inner.fixed_ids={self.anchor_id}
        self.last_actual=deepcopy(observation)

    def next_action(self, observation):
        if observation['gameOver']:
            raise RouteFailure(self.failure_reason or 'tower-full-after-target')
        if self.failure_reason is not None:
            return {'kind':'drop'}
        if (game.signature(observation)!=game.signature(self.last_actual)
                or observation['actions']!=self.last_actual['actions']
                or observation['queue']!=self.last_actual['queue']):
            raise IncompatibleState('Real continuation board changed outside automation')
        action=self.inner.next_action(self.shadow)
        self.stage=self.inner.stage
        if action is None:
            self.failure_reason='virtual-target-completed'
            return {'kind':'drop'}
        if self.inner.failure_reason is not None:
            self.failure_reason=self.inner.failure_reason
        return action

    def accept(self, before, action, after):
        check_observed(before,action,after)
        if self.failure_reason is not None:
            return
        predicted=game.predict(self.shadow,action)
        # Future previews come exclusively from the actual public observation.
        predicted['queue']=after['queue'][:]
        shadow_after=game.observation(predicted)
        self.inner.accept(self.shadow,action,shadow_after)
        projected=deepcopy(after)
        for tile in projected['tower']:
            if tile['id']==self.anchor_id:
                tile['value']=self.virtual_value
        if game.signature(projected)!=game.signature(shadow_after):
            if any(t['kind']=='tile' and t['value']==self.inner.route['target'] for t in shadow_after['tower']):
                self.failure_reason='virtual-target-completed'
            else:
                raise IncompatibleState('Unexpected nonterminal virtual/real divergence')
        self.shadow=shadow_after
        self.last_actual=deepcopy(after)
        self.stage=self.inner.stage

    def close(self):
        if self.inner is not None:
            self.inner.close()
