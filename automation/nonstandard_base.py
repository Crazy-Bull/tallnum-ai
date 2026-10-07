"""Exact shortest structural synthesis under controlled Standard draws.

Unlike macro planning, this search does not assume the requested odd base
already has a five-cell policy. Its edges are individual game operations.
SQLite retains the frontier, best state labels and predecessor actions.
It proves optimality ONLY in the stated controlled-draw bounded graph, not a
stochastic policy's success probability or restart-inclusive expected cost.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Callable

from .common import atomic_json
from .game import POOL
from .route_search import Block, edge_board, encoded, identity, normalize, ordinary_possible

VERSION = 'primitive-base-synthesis-1'


def odd_base(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError('Value must be a positive integer')
    while value%2==0:
        value //= 2
    return value


class NonstandardSynthesizer:
    """Reusable shortest-path search of ordered physical boards (1..7 cells).

    Inputs are hypothetical future draws, not numbers chosen by the player.
    Each path records the draws it requires. At most four successive identical
    random inputs are admitted, matching Standard's repetition restriction.
    `initial` is an explicit working board; default empty, not game opening.
    For a full seven-cell opening use initial=(2,4), cells=7.
    """

    def __init__(self, directory, *, cells=5, initial=(), inputs=tuple(POOL),
                 max_value=None, objective='actions'):
        if type(cells) is not int or not 1 <= cells <= 7:
            raise ValueError('Working cell count must be in [1,7]')
        if objective not in ('actions','drops'):
            raise ValueError('Objective must be actions or drops')
        inputs = tuple(dict.fromkeys(inputs))
        if not inputs or any(type(n) is not int or n not in POOL for n in inputs):
            raise ValueError('Inputs must be a nonempty subset of the Standard pool')
        board = tuple(v if isinstance(v,Block) else Block(v) for v in initial)
        if any(type(b.value) is not int or not 1 <= b.value <= 65535
               or type(b.span) is not int or not 1 <= b.span <= 5
               or type(b.group) is not bool
               or (not b.group and (b.span!=1 or not ordinary_possible(b.value)))
               or (b.group and b.span<2) for b in board):
            raise ValueError('Initial blocks must have legal ordinary values and physical spans')
        if sum(b.group for b in board)>1:
            raise ValueError('Only one Group is permitted')
        board = normalize(board)
        if sum(b.span for b in board)>cells:
            raise ValueError('Initial board exceeds available cells')
        if max_value is not None and (type(max_value) is not int or not 2 <= max_value <= 65535):
            raise ValueError('Maximum intermediate value must be in [2,65535]')
        self.directory = Path(directory)
        self.cells, self.initial, self.inputs = cells, board, inputs
        self.maximum, self.objective = max_value, objective

    def successors(self, board, last, repeats, maximum):
        """Generate exact legal structural actions, including rotation's drop."""
        if sum(b.span for b in board)>=self.cells:
            return
        for kind in ('drop','up','down'):
            if kind!='drop' and len(board)<2:
                continue
            rotated = board if kind=='drop' else normalize(
                (*board[1:],board[0]) if kind=='up' else (board[-1],*board[:-1]))
            for value in self.inputs:
                if value==last and repeats>=4:
                    continue
                after = normalize((*rotated,Block(value)))
                if any(b.value>maximum for b in after):
                    continue
                yield {'kind':kind,'input':value}, after, value, repeats+1 if value==last else 1, 1
        if not any(b.group for b in board):
            for start in range(len(board)):
                for end in range(start+2,min(len(board),start+5)+1):
                    members = board[start:end]
                    after = normalize((*board[:start],Block(sum(b.value for b in members),
                                      sum(b.span for b in members),True),*board[end:]))
                    if all(b.value<=maximum for b in after):
                        yield {'kind':'group','indices':list(range(start,end))}, after, last, repeats, 0
        after = edge_board(board)
        if after!=board and all(b.value<=maximum for b in after):
            yield {'kind':'edge'}, after, last, repeats, 0

    def search_base(self, base: int, *, exponent: int = 1, **options):
        """Search ordinary target base*2**exponent; a bare odd tile is distinct."""
        if type(base) is not int or not 1 <= base <= 65535 or base%2==0:
            raise ValueError('Base must be a positive odd integer')
        if type(exponent) is not int or not 0 <= exponent <= 15:
            raise ValueError('Exponent must be in [0,15]')
        return self.search(base*(2**exponent), **options)

    def _config(self, target):
        # EDGE producing target T needs precursors in [5*T,5*T+9]. A 2*T
        # ceiling would incorrectly exclude this essential nonstandard route.
        maximum = min(65535,max(48,5*target+9)) if self.maximum is None else self.maximum
        if maximum<target or any(b.value>maximum for b in self.initial):
            raise ValueError('Maximum must cover goal and initial board')
        return {'version':VERSION,'target':target,'cells':self.cells,'maxValue':maximum,
                'objective':self.objective,'initial':[b.json() for b in self.initial],
                'inputs':list(self.inputs),'maximumIdenticalInputs':4,
                'rules':identity({p: (Path(__file__).parent/p).read_text(encoding='utf-8')
                                 for p in ('game.py','route_search.py','nonstandard_base.py')}),
                'drawModel':'existential-controlled-inputs-not-a-stochastic-policy',
                'exit':'ordinary-single-target','fixedPrefix':False}

    @staticmethod
    def _key(board,last,repeats):
        return encoded([[b.json() for b in board],last,repeats])

    @staticmethod
    def _decode(key):
        blocks,last,repeats = json.loads(key)
        return tuple(Block(*b) for b in blocks),last,repeats

    def search(self, target: int, *, node_limit: int = 10000,
               progress: Callable[[dict],None] | None = None) -> dict:
        """Settle at most node_limit new states; 0 runs until proof/exhaustion.

        Repeating the same request automatically resumes. `paused` never
        means unreachable. Complete states have exact best labels, and are
        not revisited. The full ordered board and last-input run are cached.
        """
        if type(target) is not int or not 2 <= target <= 65535:
            raise ValueError('Ordinary target must be an integer in [2,65535]')
        if type(node_limit) is not int or node_limit<0:
            raise ValueError('Node limit must be nonnegative')
        config = self._config(target)
        result = {'target':target,'base':odd_base(target),'cells':self.cells,'config':config,
                  'status':'paused','path':None,'shortestInScopeProven':False,
                  'unreachableInScopeProven':False,
                  'stochasticReachabilityProven':False,'successProbability':None,
                  'scope':'bounded ordered-board graph with hypothetical controlled draws'}
        if not ordinary_possible(target):
            return {**result,'status':'excluded-by-rules','reason':'only-15-is-an-ordinary-odd-tile',
                    'search':{'nodesThisRun':0}}
        self.directory.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.directory/'synthesis.sqlite3')) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, config TEXT, status TEXT, goal TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS states (run TEXT, key TEXT, cost INTEGER, actions INTEGER, drops INTEGER, parent TEXT, action TEXT, settled INTEGER DEFAULT 0, PRIMARY KEY(run,key))')
            db.execute('CREATE INDEX IF NOT EXISTS synthesis_frontier ON states(run,settled,cost,actions,key)')
            run = identity(config)
            saved = db.execute('SELECT status,goal FROM runs WHERE id=?',(run,)).fetchone()
            if saved is None:
                with db:
                    db.execute('INSERT INTO runs VALUES (?,?,?,NULL)',(run,encoded(config),'paused'))
                    db.execute('INSERT INTO states VALUES (?,?,0,0,0,NULL,NULL,0)',
                               (run,self._key(self.initial,None,0)))
                saved = ('paused',None)
            status,goal = saved
            nodes = 0
            try:
                while status=='paused' and (not node_limit or nodes<node_limit):
                    row = db.execute('SELECT key,cost,actions,drops FROM states WHERE run=? AND settled=0 ORDER BY cost,actions,key LIMIT 1',(run,)).fetchone()
                    if row is None:
                        status = 'no-path-in-scope'
                        break
                    key,cost,actions,drops = row
                    board,last,repeats = self._decode(key)
                    db.execute('UPDATE states SET settled=1 WHERE run=? AND key=?',(run,key))
                    nodes += 1
                    if any(b.value==target and not b.group for b in board):
                        status,goal = 'found',key
                        break
                    for action,after,next_last,next_repeats,added in self.successors(board,last,repeats,config['maxValue']):
                        child = self._key(after,next_last,next_repeats)
                        child_cost = cost+(1 if self.objective=='actions' else added)
                        child_actions,child_drops = actions+1,drops+added
                        db.execute('INSERT INTO states(run,key,cost,actions,drops,parent,action) VALUES (?,?,?,?,?,?,?) ON CONFLICT(run,key) DO UPDATE SET cost=excluded.cost,actions=excluded.actions,drops=excluded.drops,parent=excluded.parent,action=excluded.action WHERE states.settled=0 AND (excluded.cost<states.cost OR (excluded.cost=states.cost AND excluded.actions<states.actions))',
                                   (run,child,child_cost,child_actions,child_drops,key,encoded(action)))
                    if nodes%100==0:
                        db.commit()
                        if progress:
                            progress({'target':target,'nodesThisRun':nodes,'currentCost':cost})
            except KeyboardInterrupt:
                # An interrupted expansion is retried in its entirety. Best
                # labels already written to children are harmless duplicates.
                if 'key' in locals():
                    db.execute('UPDATE states SET settled=0 WHERE run=? AND key=?',(run,key))
                status = 'paused'
            with db:
                db.execute('UPDATE runs SET status=?,goal=? WHERE id=?',(status,goal,run))
            result['status'] = status
            result['unreachableInScopeProven'] = status=='no-path-in-scope'
            total,settled = db.execute('SELECT count(*),sum(settled) FROM states WHERE run=?',(run,)).fetchone()
            frontier = db.execute('SELECT min(cost) FROM states WHERE run=? AND settled=0',(run,)).fetchone()[0]
            result['search'] = {'nodesThisRun':nodes,'statesStored':total,'statesSettled':settled or 0,
                                'frontierCostLowerBound':frontier,'cacheId':run}
            if goal is not None:
                path = []
                cursor = goal
                final = db.execute('SELECT cost,actions,drops FROM states WHERE run=? AND key=?',(run,goal)).fetchone()
                while True:
                    parent,action = db.execute('SELECT parent,action FROM states WHERE run=? AND key=?',(run,cursor)).fetchone()
                    if parent is None:
                        break
                    before,_,_ = self._decode(parent)
                    after,_,_ = self._decode(cursor)
                    path.append({'action':json.loads(action),'before':[b.json() for b in before],
                                 'after':[b.json() for b in after]})
                    cursor = parent
                path.reverse()
                result.update(path=path,cost=final[0],actions=final[1],drops=final[2],
                              shortestInScopeProven=True)
            return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Shortest primitive synthesis of a nonstandard odd base')
    goal = parser.add_mutually_exclusive_group(required=True)
    goal.add_argument('--base',type=int,help='Odd base; ordinary target is base*2**exponent')
    goal.add_argument('--target',type=int,help='Exact ordinary target')
    parser.add_argument('--exponent',type=int,default=1)
    parser.add_argument('--cells',type=int,default=5)
    parser.add_argument('--initial',type=int,nargs='*',default=[])
    parser.add_argument('--inputs',type=int,nargs='+',default=POOL)
    parser.add_argument('--max-value',type=int)
    parser.add_argument('--objective',choices=['actions','drops'],default='actions')
    parser.add_argument('--node-limit',type=int,default=10000)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args(argv)
    planner = NonstandardSynthesizer(args.directory,cells=args.cells,initial=args.initial,
                                    inputs=args.inputs,max_value=args.max_value,objective=args.objective)
    if args.base is not None:
        result = planner.search_base(args.base,exponent=args.exponent,node_limit=args.node_limit)
    else:
        result = planner.search(args.target,node_limit=args.node_limit)
    if args.output:
        atomic_json(args.output,result)
    else:
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    return result


if __name__=='__main__':
    main()
