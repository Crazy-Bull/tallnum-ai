"""Reusable seven-cell planning API and CLI, with no fixed goal or live play.

Structural searches use Python's standard library only. Five-cell policy
calculation and simulation remain separate optional stages in automation.route.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable, Iterable

from .common import atomic_json
from .route_search import RouteSearch


class SevenCellPlanner:
    """Query any ordinary goal with a persistent cache and supplied policy data.

    ``search`` does not generate five-cell policies or run simulations. Missing
    contracts are returned as requirements, not asserted to be reachable.
    Repeating the same query resumes incomplete work automatically.
    ``catalog=None`` reloads cache_directory/catalog.json for every query so
    newly computed variants are picked up without recreating the planner.
    """

    def __init__(self, cache_directory, *, catalog=None, max_value=None,
                 weights=None, candidate_limit=20, leaf_targets=None):
        self.cache_directory = Path(cache_directory)
        self.catalog = catalog
        self.options = {'max_value': max_value, 'weights': weights,
                        'candidate_limit': candidate_limit,
                        'leaf_targets': list(leaf_targets) if leaf_targets is not None else None}

    def _catalog(self):
        if self.catalog is not None:
            return self.catalog
        file = self.cache_directory/'catalog.json'
        if not file.exists():
            return {'policies': []}
        catalog = json.loads(file.read_text(encoding='utf-8'))
        # Keep this entry free of NumPy/PETSc/native imports. Certification and
        # endpoint matching are checked again by RouteSearch.available().
        rules = {'edge-recheck-v1', '91de4bf6f03efea924c3e277971227881760244572ef74d162d3df6098dcb06d'}
        return {**catalog, 'policies': [p for p in catalog.get('policies', [])
                                      if p.get('ruleSha256') in rules]}

    def search(self, target: int, *, node_limit: int = 0,
               progress: Callable[[dict], None] | None = None) -> dict:
        """Return structures, representative routes, missing policies and scope.

        node_limit limits NEW memo subproblems for this call (0 = unlimited).
        A budget pause is resumable and never means the target is unreachable.
        No plan.json/route-request.json is written; SQLite is the only required
        output. Save the returned dictionary explicitly if desired.
        """
        with RouteSearch(self.cache_directory, self._catalog(), target=target,
                         cells=7, node_limit=node_limit, progress=progress, **self.options) as search:
            result = search.plan(write_result=False)
        result['entryPoint'] = 'seven-cell-reusable-program'
        return result

    def search_many(self, targets: Iterable[int], *, node_limit: int = 0,
                    progress: Callable[[dict], None] | None = None) -> dict[int, dict]:
        """Query requested goals sequentially using the same cache directory.

        Fully validate the batch before starting, so a bad later input does not
        leave a half-executed batch. Duplicate goals are evaluated only once.
        The node budget applies independently to each requested goal.
        """
        targets = list(targets)
        if any(type(t) is not int or not 2 <= t <= 65535 for t in targets):
            raise ValueError('Targets must be integers in [2,65535]')
        if self.options['max_value'] is not None and any(t > self.options['max_value'] for t in targets):
            raise ValueError('All goals must fit the configured maximum intermediate value')
        return {target: self.search(target, node_limit=node_limit, progress=progress)
                for target in dict.fromkeys(targets)}


def search_seven(target: int, cache_directory, *, catalog=None, max_value=None,
                 weights=None, candidate_limit=20, leaf_targets=None,
                 node_limit: int = 0, progress=None) -> dict:
    """Convenience function; identical queries automatically reuse disk state."""
    planner = SevenCellPlanner(cache_directory, catalog=catalog, max_value=max_value,
                               weights=weights, candidate_limit=candidate_limit,
                               leaf_targets=leaf_targets)
    return planner.search(target, node_limit=node_limit, progress=progress)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Reusable seven-cell route search for arbitrary goals')
    parser.add_argument('--target', type=int, nargs='+', required=True, help='One or more ordinary goals in 2..65535')
    parser.add_argument('--directory', type=Path, required=True, help='Shared cache/policy directory')
    parser.add_argument('--max-value', type=int)
    parser.add_argument('--weights', type=Path, help='JSON mapping template keys to positive difficulty weights')
    parser.add_argument('--leaf-targets', type=int, nargs='+')
    parser.add_argument('--candidate-limit', type=int, default=20)
    parser.add_argument('--node-limit', type=int, default=0, help='New subproblem budget per target (0 = unlimited)')
    parser.add_argument('--output', type=Path, help='Optional JSON export; without it return JSON on stdout only')
    args = parser.parse_args(argv)
    weights = json.loads(args.weights.read_text(encoding='utf-8')) if args.weights else None
    planner = SevenCellPlanner(args.directory, max_value=args.max_value, weights=weights,
                               candidate_limit=args.candidate_limit, leaf_targets=args.leaf_targets)
    results = planner.search_many(args.target, node_limit=args.node_limit)
    result = next(iter(results.values())) if len(results)==1 else {'cells': 7, 'results': results}
    if args.output:
        atomic_json(args.output, result)
    else:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return result


if __name__ == '__main__':
    main()
