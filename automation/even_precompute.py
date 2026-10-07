"""Shared minimax dynamic labels for every even ordinary target and Group exit.

One ordered-board search supplies ALL goals, rather than solving each number
again. Label relaxation is D(next)=min(D(next),max(D(current),max(next))).
The frontier is processed by that bottleneck cost. It is not increasing-target
DP: EDGE makes larger-number dependencies and cycles unavoidable.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .common import atomic_json
from .game import POOL
from .nonstandard_base import NonstandardSynthesizer
from .route_search import encoded, identity
from .peak_bounds import arithmetic_peak_bounds

VERSION = 'all-even-minimum-peak-1'


class EvenPrecomputer:
    def __init__(self, directory, *, cells=6, initial=(), max_value=65535,
                 inputs=tuple(POOL)):
        self.engine = NonstandardSynthesizer(directory,cells=cells,initial=initial,
                                             max_value=max_value,inputs=inputs)
        config = self.engine._config(2)
        config.pop('target')
        config.update(version=VERSION,objective='maximum-number-ever-on-route',
                      goalKinds=['ordinary','group-by-physical-span'],
                      source=identity(Path(__file__).read_text(encoding='utf-8')),
                      arithmeticBoundSource=identity((Path(__file__).parent/'peak_bounds.py').read_text(encoding='utf-8')))
        self.config,self.run_id = config,identity(config)
        self.directory = Path(directory)
        self.bounds = arithmetic_peak_bounds(self.engine.inputs,self.engine.initial,max_value)

    def _connect(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        db = sqlite3.connect(self.directory/'even-precompute.sqlite3')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, config TEXT, exhausted INTEGER DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS states (run TEXT, key TEXT, peak INTEGER, steps INTEGER, drops INTEGER, parent TEXT, action TEXT, settled INTEGER DEFAULT 0, PRIMARY KEY(run,key))')
        db.execute('CREATE INDEX IF NOT EXISTS peak_frontier ON states(run,settled,peak,steps,key)')
        db.execute('CREATE TABLE IF NOT EXISTS goals (run TEXT, value INTEGER, kind TEXT, span INTEGER, state TEXT, peak INTEGER, proven INTEGER, PRIMARY KEY(run,value,kind,span))')
        self._goal_labels = {(v,k,s):(p,bool(proven)) for v,k,s,p,proven in
                             db.execute('SELECT value,kind,span,peak,proven FROM goals WHERE run=?',(self.run_id,))}
        if db.execute('SELECT 1 FROM runs WHERE id=?',(self.run_id,)).fetchone() is None:
            with db:
                db.execute('INSERT INTO runs(id,config) VALUES (?,?)',(self.run_id,encoded(self.config)))
                key = self.engine._key(self.engine.initial,None,0)
                peak = max((b.value for b in self.engine.initial),default=0)
                db.execute('INSERT INTO states VALUES (?,?,?,0,0,NULL,NULL,0)',(self.run_id,key,peak))
                self._goals(db,key,self.engine.initial,peak,False)
        return db

    def _goals(self, db, state, board, peak, proven):
        for block in board:
            if not block.group and block.value%2:
                continue
            lower = (max(block.value,self.bounds['initialPeak']) if block.group
                     else self.bounds['costs'].get(block.value))
            if lower is None:
                raise AssertionError('Arithmetic relaxation excluded a real transition')
            certified = proven or peak==lower
            interface = (block.value,'group' if block.group else 'ordinary',block.span)
            old = self._goal_labels.get(interface)
            if old is not None and (old[0]<peak or old[0]==peak and old[1]>=certified):
                continue
            db.execute('INSERT INTO goals VALUES (?,?,?,?,?,?,?) ON CONFLICT(run,value,kind,span) DO UPDATE SET state=excluded.state,peak=excluded.peak,proven=excluded.proven WHERE excluded.peak<goals.peak OR (excluded.peak=goals.peak AND excluded.proven>goals.proven)',
                       (self.run_id,block.value,'group' if block.group else 'ordinary',
                        block.span,state,peak,int(certified)))
            self._goal_labels[interface] = (peak,bool(certified))

    @staticmethod
    def _maximum_target(max_target, max_value):
        if type(max_target) is not int or not 2 <= max_target <= 65534 or max_target%2:
            raise ValueError('Maximum even target must be even and in [2,65534]')
        if max_target>max_value:
            raise ValueError('Intermediate maximum must cover all requested targets')

    def precompute(self, *, max_target=65534, node_limit=10000, progress=None,
                   export=None):
        """Advance one shared cache. Unsettled goals remain explicitly unknown.

        A node budget is total settled states, not a separate budget per target.
        `max_target` only controls completion/export; higher goals encountered
        are cached too, so extending the requested range reuses the same run.
        """
        self._maximum_target(max_target,self.config['maxValue'])
        if type(node_limit) is not int or node_limit<0:
            raise ValueError('Node limit must be nonnegative')
        with closing(self._connect()) as db:
            exhausted = bool(db.execute('SELECT exhausted FROM runs WHERE id=?',(self.run_id,)).fetchone()[0])
            nodes = 0
            proven = db.execute("SELECT count(*) FROM goals WHERE run=? AND kind='ordinary' AND value<=? AND proven=1",(self.run_id,max_target)).fetchone()[0]
            interrupted = False
            current = None
            try:
                reachable = sum(n in self.bounds['costs'] for n in range(2,max_target+1,2))
                while not exhausted and proven<reachable and (not node_limit or nodes<node_limit):
                    row = db.execute('SELECT key,peak,steps,drops FROM states WHERE run=? AND settled=0 ORDER BY peak,steps,key LIMIT 1',(self.run_id,)).fetchone()
                    if row is None:
                        exhausted = True
                        break
                    current,peak,steps,drops = row
                    board,last,repeats = self.engine._decode(current)
                    db.execute('UPDATE states SET settled=1 WHERE run=? AND key=?',(self.run_id,current))
                    self._goals(db,current,board,peak,True)
                    nodes += 1
                    for action,after,nlast,nrepeat,added in self.engine.successors(board,last,repeats,self.config['maxValue']):
                        terminal = sum(b.span for b in after)>=self.engine.cells
                        # No future action is possible on a terminal board.
                        # Its draw-run history cannot change any goal, so
                        # merge those labels and keep them out of the frontier.
                        if terminal:
                            nlast,nrepeat = None,0
                        key = self.engine._key(after,nlast,nrepeat)
                        cost = max(peak,max((b.value for b in after),default=0))
                        changed = db.execute('INSERT INTO states(run,key,peak,steps,drops,parent,action,settled) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(run,key) DO UPDATE SET peak=excluded.peak,steps=excluded.steps,drops=excluded.drops,parent=excluded.parent,action=excluded.action WHERE states.settled!=1 AND (excluded.peak<states.peak OR (excluded.peak=states.peak AND excluded.steps<states.steps))',
                                             (self.run_id,key,cost,steps+1,drops+added,current,encoded(action),2 if terminal else 0)).rowcount
                        if changed:
                            self._goals(db,key,after,cost,False)
                    current = None
                    if nodes%100==0:
                        db.commit()
                        proven = db.execute("SELECT count(*) FROM goals WHERE run=? AND kind='ordinary' AND value<=? AND proven=1",(self.run_id,max_target)).fetchone()[0]
                        if progress:
                            progress({'nodesThisRun':nodes,'currentPeak':peak,'provenTargets':proven,
                                      'totalTargets':max_target//2})
            except KeyboardInterrupt:
                if current is not None:
                    db.execute('UPDATE states SET settled=0 WHERE run=? AND key=?',(self.run_id,current))
                interrupted = True
            frontier = db.execute('SELECT min(peak) FROM states WHERE run=? AND settled=0',(self.run_id,)).fetchone()[0]
            if frontier is None:
                exhausted = True
                db.execute('UPDATE goals SET proven=1 WHERE run=?',(self.run_id,))
            else:
                # Any improvement below this threshold would have required
                # a frontier label with a smaller bottleneck. This also proves
                # terminal-goal labels without expanding dead terminal boards.
                db.execute('UPDATE goals SET proven=1 WHERE run=? AND peak<=?',(self.run_id,frontier))
            with db:
                db.execute('UPDATE runs SET exhausted=? WHERE id=?',(int(exhausted),self.run_id))
            result = self._summary(db,max_target,nodes,exhausted)
            result['interrupted'] = interrupted
            if export is not None:
                self._export(db,Path(export),result,max_target,exhausted)
            return result

    def _summary(self, db, maximum, nodes, exhausted):
        known,proven = db.execute("SELECT count(*),coalesce(sum(proven),0) FROM goals WHERE run=? AND kind='ordinary' AND value<=?",(self.run_id,maximum)).fetchone()
        states,settled,expanded = db.execute('SELECT count(*),coalesce(sum(settled!=0),0),coalesce(sum(settled=1),0) FROM states WHERE run=?',(self.run_id,)).fetchone()
        frontier = db.execute('SELECT min(peak) FROM states WHERE run=? AND settled=0',(self.run_id,)).fetchone()[0]
        total = maximum//2
        possible = sum(n in self.bounds['costs'] for n in range(2,maximum+1,2))
        impossible = total-possible
        return {'version':VERSION,'config':self.config,'cacheId':self.run_id,
                'status':'exhausted' if exhausted else 'range-complete' if proven==possible else 'paused',
                'maximumEvenTarget':maximum,'totalTargets':total,'provenTargets':proven,
                'candidateOnlyTargets':known-proven,'unreachableInScopeTargets':total-known if exhausted else impossible,
                'arithmeticExcludedTargets':impossible,
                'unknownTargets':0 if exhausted else possible-known,
                'nodesThisRun':nodes,'statesStored':states,'statesSettled':settled,
                'statesExpanded':expanded,
                'frontierPeakLowerBound':frontier,'allRequestedClassified':exhausted or proven==possible,
                'stochasticPolicyVerified':False,'fiveCellTemplateCountsAvailable':False}

    def _entry(self, db, target, kind, span, exhausted, include_path):
        row = db.execute('SELECT state,peak,proven FROM goals WHERE run=? AND value=? AND kind=? AND span=?',
                         (self.run_id,target,kind,span)).fetchone()
        result = {'target':target,'exit':kind,'physicalSpan':span,'minimumPeakProven':False,
                  'stochasticPolicyVerified':False,'shortestActionCountProven':False,
                  'fiveCellTemplateCounts':None}
        lower = self.bounds['costs'].get(target) if kind=='ordinary' else max(target,self.bounds['initialPeak'])
        result['peakLowerBound'] = lower
        if row is None:
            impossible = exhausted or kind=='ordinary' and lower is None
            return {**result,'status':'unreachable-in-scope' if impossible else 'unknown','peak':None}
        state,peak,proven = row
        result.update(status='minimum-peak-proven' if proven else 'candidate',peak=peak,
                      minimumPeakProven=bool(proven),stateId=state)
        if include_path:
            path = []
            steps,drops = db.execute('SELECT steps,drops FROM states WHERE run=? AND key=?',(self.run_id,state)).fetchone()
            cursor = state
            while True:
                parent,action = db.execute('SELECT parent,action FROM states WHERE run=? AND key=?',(self.run_id,cursor)).fetchone()
                if parent is None:
                    break
                before,_,_ = self.engine._decode(parent)
                after,_,_ = self.engine._decode(cursor)
                path.append({'action':json.loads(action),'before':[b.json() for b in before],
                             'after':[b.json() for b in after]})
                cursor = parent
            result.update(path=list(reversed(path)),actions=steps,drops=drops)
        return result

    def lookup(self, target, *, kind='ordinary', span=1, include_path=True):
        if type(target) is not int or not 1 <= target <= self.config['maxValue']:
            raise ValueError('Target is outside the declared range')
        if kind not in ('ordinary','group') or type(span) is not int or not 1 <= span <= 5:
            raise ValueError('Invalid exit kind or physical span')
        if (kind=='ordinary' and (target%2 or span!=1)) or (kind=='group' and span<2):
            raise ValueError('Ordinary queries require an even target and one cell; Group requires 2..5 cells')
        with closing(self._connect()) as db:
            exhausted = bool(db.execute('SELECT exhausted FROM runs WHERE id=?',(self.run_id,)).fetchone()[0])
            return self._entry(db,target,kind,span,exhausted,include_path)

    def _export(self, db, path, summary, maximum, exhausted):
        entries = [self._entry(db,value,'ordinary',1,exhausted,False) for value in range(2,maximum+1,2)]
        groups = [dict(target=v,physicalSpan=s,peak=p,minimumPeakProven=bool(proven))
                  for v,s,p,proven in db.execute("SELECT value,span,peak,proven FROM goals WHERE run=? AND kind='group' ORDER BY value,span",(self.run_id,))]
        recipes = [{'target':v,'peakLowerBound':self.bounds['costs'][v],
                    'recipe':self.bounds['recipes'][v]}
                   for v in sorted(self.bounds['costs'])]
        atomic_json(path,{'summary':summary,'ordinary':entries,'groups':groups,
                          'arithmeticRelaxation':{'meaning':self.bounds['meaning'],
                                                  'physicalSpaceVerified':False,'recipes':recipes}})


def main(argv=None):
    parser = argparse.ArgumentParser(description='Precompute every even target by minimum maximum intermediate number')
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--cells',type=int,default=6)
    parser.add_argument('--initial',type=int,nargs='*',default=[])
    parser.add_argument('--inputs',type=int,nargs='+',default=POOL)
    parser.add_argument('--max-value',type=int,default=65535)
    parser.add_argument('--max-target',type=int,default=65534)
    parser.add_argument('--node-limit',type=int,default=10000)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--lookup',type=int)
    args = parser.parse_args(argv)
    planner = EvenPrecomputer(args.directory,cells=args.cells,initial=args.initial,
                              max_value=args.max_value,inputs=args.inputs)
    if args.lookup is not None:
        result = planner.lookup(args.lookup)
    else:
        result = planner.precompute(max_target=args.max_target,node_limit=args.node_limit,
                                    export=args.output)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return result


if __name__=='__main__':
    main()
