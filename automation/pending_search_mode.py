"""Register and run the isolated probability-search 10-cell 10240 route."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .common import atomic_json, fingerprint

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'automation/runs/binary10240/min24'
DEFAULT_DYNAMIC = RUNS / 'pending-search-all-policies-001'
DEFAULT_BASELINE = RUNS / 'buffer-rescue-all-007'
DEFAULT_OUT = RUNS / 'pending-search-route-all-definitions-001'


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def prepare(out: Path, dynamic: Path, baseline: Path, evidence: Path | None = None) -> dict:
    dynamic, baseline, out = dynamic.resolve(), baseline.resolve(), out.resolve()
    route = read_json(dynamic / 'route.json')
    catalog = read_json(dynamic / 'catalog.json')
    traditional_route = read_json(baseline / 'route.json')
    traditional_catalog = read_json(baseline / 'catalog.json')
    if evidence:
        evidence_dir=evidence.resolve()
    else:
        retry=dynamic/'validation-100-retry1'
        evidence_dir=retry if retry.exists() else dynamic/'validation-100'
    result = read_json(evidence_dir / 'summary.json')
    engine = read_json(evidence_dir / 'validation.json.engine-check.json')
    dynamic_config = read_json(dynamic / 'configuration.json')

    if route.get('cells') != 10 or route.get('target') != 10240:
        raise ValueError('Dynamic snapshot is not the complete 10-cell 10240 route')
    if route != traditional_route:
        raise ValueError('Dynamic mode must preserve the traditional route structure')
    if set(p['id'] for p in catalog['policies']) != set(p['id'] for p in traditional_catalog['policies']):
        raise ValueError('Dynamic mode must retain the traditional policy catalog')
    if result.get('attempts') != 100 or engine.get('games') != 100 or not engine.get('seededRngParity') or engine.get('forcedDraws'):
        raise ValueError('The 100-game paired run lacks a valid original-engine replay certificate')

    dynamic_policies = {p['id']: p for p in catalog['policies']}
    base_policies = {p['id']: p for p in traditional_catalog['policies']}
    all_five = bool(dynamic_config.get('allFiveCellExits'))
    six_singles = bool(dynamic_config.get('sixCellSingles'))
    buffer_search = bool(dynamic_config.get('bufferRescueSearch'))
    search_ids = {p['id'] for p in catalog['policies'] if p.get('pendingValue')}
    route_ids = {s['policy'] for s in route['steps'] if s.get('kind') == 'leaf'}
    buffer_ids = {ident for ids in route.get('bufferRescuePolicies', {}).values() for ident in ids}
    route_ids.update(buffer_ids)
    if not search_ids or not search_ids.issubset(route_ids):
        raise ValueError('Probability-search catalog must attach only to definitions used by the full route')
    definitions = []
    for ident in sorted(search_ids):
        p = dynamic_policies[ident]
        definitions.append({'id': ident, 'cells': p.get('cells'), 'target': p['target'],
                            'exit': p['exit'], 'maxGoalCells': p.get('maxGoalCells'),
                            'matchEdgeGuard': bool(p.get('matchEdgeGuard', False))})

    identity_fields = ('policySha256', 'table', 'tableSha256', 'hashes', 'exit', 'target', 'cells')
    for ident, old in base_policies.items():
        new = dynamic_policies[ident]
        if any(new.get(k) != old.get(k) for k in identity_fields):
            raise ValueError(f'Dynamic mode changed traditional policy identity: {ident}')
        supported_dynamic = ((new.get('cells') == 5 and
                              (new.get('exit') == 'single' or
                               (all_five and new.get('exit') in {'match', 'extend'}) or
                               (buffer_search and ident in buffer_ids and new.get('exit') == 'buffer'))) or
                             (six_singles and new.get('cells') == 6 and new.get('exit') == 'single'))
        if new.get('pendingValue') and not supported_dynamic:
            raise ValueError(f'Probability search is attached to unsupported definition {ident}')

    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / 'route.json', route)
    atomic_json(out / 'catalog.json', catalog)
    mapping_file = baseline / 'mapping.json'
    mapping = read_json(mapping_file)
    atomic_json(out / 'mapping.json', mapping)
    mode = {
        'mode': 'pending-probability-search', 'version': 1,
        'cells': 10, 'target': 10240,
        'route': str(out / 'route.json'), 'catalog': str(out / 'catalog.json'),
        'mapping': str(out / 'mapping.json'),
        'traditionalRun': str(baseline),
        'traditionalRouteSha256': fingerprint(baseline / 'route.json'),
        'traditionalCatalogSha256': fingerprint(baseline / 'catalog.json'),
        'dynamicSourceRun': str(dynamic),
        'dynamicRouteSha256': fingerprint(dynamic / 'route.json'),
        'dynamicCatalogSha256': fingerprint(dynamic / 'catalog.json'),
        'searchDefinitions': definitions,
        'searchTargets': sorted({p['target'] for p in definitions}),
        'searchScope': dynamic_config.get('searchScope',
                         ('all five-cell route leaves and buffer rescues plus six-cell single definitions'
                          if all_five and six_singles and buffer_search else
                          'all routed five-cell single, match, and extend plus six-cell single definitions'
                          if all_five and six_singles else
                          'routed six-cell single definitions only' if six_singles else
                          'five-cell route leaves and buffer rescues'
                          if all_five and buffer_search else
                          'all routed five-cell single, match, and extend definitions; six-cell singles stay traditional'
                          if all_five else
                          'five-cell single definitions only; remaining definitions stay traditional')),
        'bufferRescueMapping': mapping,
        'pairedValidation': str(evidence_dir),
        'pairedResults': {'games': result['attempts'], 'successes': result['successes'],
                          'originalEngineCheck': engine},
        'traditionalFilesModified': False,
    }
    atomic_json(out / 'mode.json', mode)
    return mode


def validate(out: Path, seed_limit: int) -> None:
    out = out.resolve()
    mode = read_json(out / 'mode.json')
    command = [sys.executable, '-m', 'automation.validate_buffer_rescue',
               '--out', str(out / f'validation-{seed_limit}'),
               '--policy-dir', str(Path(mode['traditionalRun']) / 'policies'),
               '--mapping', str(out / 'mapping.json'),
               '--route-file', str(out / 'route.json'),
               '--catalog-file', str(out / 'catalog.json'),
               '--baseline-run', mode['traditionalRun'],
               '--seed-limit', str(seed_limit)]
    subprocess.run(command, cwd=ROOT, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Select the isolated pending-probability 10-cell 10240 route')
    parser.add_argument('command', choices=['prepare', 'validate'])
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--dynamic-run', type=Path, default=DEFAULT_DYNAMIC)
    parser.add_argument('--baseline-run', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--validation-dir', type=Path, default=None,
                        help='paired 100-game validation directory (defaults to <dynamic-run>/validation-100)')
    parser.add_argument('--seed-limit', type=int, default=100)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.out, args.dynamic_run, args.baseline_run, args.validation_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not 1 <= args.seed_limit <= 100:
            parser.error('--seed-limit must be in 1..100')
        validate(args.out, args.seed_limit)


if __name__ == '__main__':
    main()
