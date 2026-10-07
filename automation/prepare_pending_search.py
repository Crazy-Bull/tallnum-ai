"""Build compact completion-probability caches for live action-search experiments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'automation/runs/binary10240/min24'
SOURCE_RUN = RUNS / 'buffer-rescue-all-007'
OUT = RUNS / 'pending-search-single-001'
NATIVE = ROOT / 'automation/pending_value_experiment.exe'
NATIVE_ALL_FIVE = ROOT / 'automation/pending_value_all5.exe'
NATIVE_ALL_CELLS = ROOT / 'automation/pending_value_allcells.exe'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--source-run', type=Path, default=SOURCE_RUN)
    parser.add_argument('--all-five-cell-exits', action='store_true',
                        help='include routed five-cell single, match, and extend definitions')
    parser.add_argument('--six-cell-singles', action='store_true',
                        help='also include routed six-cell single definitions (large streaming builds)')
    parser.add_argument('--buffer-rescue-search', action='store_true',
                        help='also include the six five-cell buffer definitions referenced by match rescue')
    parser.add_argument('--native',type=Path,help='override pending-state executable for a new model format')
    args = parser.parse_args()
    out = args.out.resolve()
    source = args.source_run.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / 'pending').mkdir(exist_ok=True)
    (out / 'inputs').mkdir(exist_ok=True)
    route = json.loads((source / 'route.json').read_text(encoding='utf-8'))
    catalog = json.loads((source / 'catalog.json').read_text(encoding='utf-8'))
    exits = {'single', 'match', 'extend'} if args.all_five_cell_exits else {'single'}
    def in_scope(step):
        return (step.get('kind') == 'leaf' and
                ((step.get('policyCells') == 5 and step.get('exit') in exits) or
                 (args.six_cell_singles and step.get('policyCells') == 6 and step.get('exit') == 'single')))
    leaves = {s['policy']: s for s in route['steps'] if in_scope(s)}
    selected = {}
    catalog_by_id = {p['id']: p for p in catalog['policies']}
    for ident, step in leaves.items():
        item = catalog_by_id.get(ident)
        if not item:
            raise RuntimeError(f'Route definition missing from catalog: {ident}')
        if (item.get('target') != step['target'] or item.get('exit') != step['exit']
                or item.get('cells') != step.get('policyCells') or item.get('successNoExtraCombos') is not True
                or not item.get('petsc', {}).get('verified')):
            raise RuntimeError(f'Route policy is not a certified clean five-cell definition: {ident}')
        selected[ident] = item
    buffer_ids = {ident for ids in route.get('bufferRescuePolicies', {}).values() for ident in ids}
    if args.buffer_rescue_search:
        for ident in buffer_ids:
            item = catalog_by_id.get(ident)
            if not item:
                raise RuntimeError(f'Buffer rescue definition missing from catalog: {ident}')
            if (item.get('exit') != 'buffer' or item.get('cells') != 5
                    or item.get('successNoExtraCombos') is not True
                    or item.get('maxGoalCells', 5) > 4
                    or not item.get('petsc', {}).get('verified')):
                raise RuntimeError(f'Buffer rescue is not a certified clean five-cell definition: {ident}')
            selected[ident] = item
    if not selected:
        raise RuntimeError('No matching five-cell definitions found in route')
    exe = (NATIVE_ALL_CELLS if args.six_cell_singles else
           NATIVE_ALL_FIVE if args.all_five_cell_exits or args.buffer_rescue_search else NATIVE)
    if args.native:exe=args.native.resolve()
    if not exe.exists():
        raise FileNotFoundError(f'Pending-search runtime is unavailable: {exe}')
    for ident, item in selected.items():
        existing = item.get('pendingValue')
        existing_meta = Path(item.get('pendingValueMeta', '')) if item.get('pendingValueMeta') else None
        if (existing and item.get('pendingNative') and existing_meta and existing_meta.exists()
                and Path(existing).exists() and fingerprint(existing)==item.get('pendingValueSha256')):
            print(json.dumps({'policy':ident,'target':item['target'],'exit':item['exit'],
                              'cells':item['cells'],'pendingBytes':Path(existing).stat().st_size,
                              'reused':True,'pendingValue':str(existing)},ensure_ascii=False),flush=True)
            continue
        target, exit_kind = int(item['target']), item['exit']
        table = Path(item['table'])
        cells = int(item['cells'])
        if cells == 6:
            values = Path(item['dataDirectory']) / 'vi.values.bin'
        else:
            policy_source = Path(item['source'])
            values = policy_source.parent / '01_values.bin'
        if not values.exists():
            raise FileNotFoundError(f'Baseline probability values missing for target {target}: {values}')
        value_name = f'{ident}-baseline-values.bin' if args.all_five_cell_exits or args.six_cell_singles or args.buffer_rescue_search else f'{target}-baseline-values.bin'
        normalized_values = out / 'inputs' / value_name
        if not normalized_values.exists():
            with values.open('rb') as src:
                magic = src.read(8)
                with normalized_values.open('wb') as dst:
                    if magic == b'TALLVAL4':
                        dst.write(magic); dst.write(src.read())
                    elif magic == b'TALLAVA1':
                        dst.write(b'TALLVAL4')
                        src.read(8)  # discard aggression; remaining header/payload is TALLVAL4 layout
                        dst.write(src.read())
                    else:
                        raise ValueError(f'Unsupported value file tag {magic!r}')
        name = (f"{cells}-{target}-{exit_kind}-pending-probabilities.bin" if args.all_five_cell_exits or args.six_cell_singles or args.buffer_rescue_search
                else f'{target}-pending-probabilities.bin')
        pending = out / 'pending' / name
        proc = subprocess.run([str(exe), 'build', str(table), str(normalized_values), str(pending)],
                              capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f'pending cache build for {target}: {(proc.stderr or proc.stdout)[-3000:]}')
        item['pendingValue'] = str(pending)
        item['pendingNative'] = str(exe)
        item['pendingValueSha256'] = fingerprint(pending)
        meta = pending.with_suffix('.json')
        item['pendingValueMeta'] = str(meta)
        meta_fields = {'pendingSha256': item['pendingValueSha256'],
                       'tableSha256': item['hashes']['table'],
                       'policySha256': item['policySha256'], 'target': target,
                       'exit': exit_kind, 'successNoExtraCombos': True,
                       'matchEdgeGuard': bool(item.get('matchEdgeGuard', False)),
                       'sourceValuesSha256': fingerprint(normalized_values),
                       'sourceValues': str(normalized_values),
                       'search': 'enumerate legal free moves and three next-drop modes; maximize pending-state completion probability',
                       'probabilitySemantics': 'VI value averaged over one unseen next preview; not whole-game probability'}
        if args.all_five_cell_exits or args.six_cell_singles or args.buffer_rescue_search:
            meta_fields.update(format='TNPEND02', maxValue=item.get('maxValue', target),
                               maxGoalCells=item['maxGoalCells'], cells=cells)
            if item.get('singleEdgeGuard') or item.get('singleTidyExit'):
                meta_fields.update(format='TNPEND03',singleEdgeGuard=bool(item.get('singleEdgeGuard')),
                                   singleTidyExit=bool(item.get('singleTidyExit')))
        else:
            meta_fields.update(format='TNPEND01')
        atomic_json(meta, meta_fields)
        print(json.dumps({'policy': ident, 'target': target, 'exit': exit_kind,
                          'states': json.loads(proc.stdout)['pendingStates'],
                          'pendingBytes': pending.stat().st_size,
                          'cells': cells, 'sourceValues': str(values)}, ensure_ascii=False), flush=True)
    atomic_json(out / 'route.json', route)
    atomic_json(out / 'catalog.json', catalog)
    atomic_json(out / 'configuration.json', {
        'sourceRun': str(source), 'definitions': [
            {'id': ident, 'target': int(item['target']), 'exit': item['exit'],
            'cells': item['cells'], 'maxGoalCells': item['maxGoalCells'],
             'matchEdgeGuard': bool(item.get('matchEdgeGuard', False))}
            for ident, item in sorted(selected.items())],
        'targets': sorted({int(item['target']) for item in selected.values()}),
        'allFiveCellExits': args.all_five_cell_exits,
        'sixCellSingles': args.six_cell_singles,
        'bufferRescueSearch': args.buffer_rescue_search,
        'searchScope': ('all five-cell route leaves and buffer rescues plus six-cell single definitions'
                        if args.all_five_cell_exits and args.six_cell_singles and args.buffer_rescue_search else
                        'all routed five-cell single, match, and extend plus six-cell single definitions'
                        if args.all_five_cell_exits and args.six_cell_singles else
                        'routed six-cell single definitions only' if args.six_cell_singles else
                        'five-cell route leaves and buffer rescues' if args.all_five_cell_exits and args.buffer_rescue_search else
                        'all routed five-cell single, match, and extend definitions' if args.all_five_cell_exits else
                        'five-cell single definitions only'),
        'route': str(out / 'route.json'),
        'catalog': str(out / 'catalog.json'), 'dynamicSearch': True,
        'cachedQuantity': 'one completion probability per pending-drop state',
        'runtimeCandidates': ['EDGE', 'up', 'down', 'drop'],
        'previewVisibility': 2, 'forcedDraws': False,
        'sourceHashes': {'pending_value.cpp': fingerprint(ROOT / 'automation/pending_value.cpp'),
                         'library.py': fingerprint(ROOT / 'automation/library.py'),
                         'runtime.py': fingerprint(ROOT / 'automation/runtime.py'),
                         'route_runtime.py': fingerprint(ROOT / 'automation/route_runtime.py')}})


if __name__ == '__main__':
    main()
