"""Prepare and PETSc-certify one same-head buffer for every route match."""
from __future__ import annotations

import json
from pathlib import Path

from . import library, certify
from .common import atomic_json, link_or_copy


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'automation/runs/binary10240/min24/buffer-rescue-all-007'
POLICIES = OUT / 'policies'
MAPPING = {'32': [30], '40': [48], '48': [40],
           '60': [64], '64': [60], '80': [84]}
REQUIREMENTS = [
    {'target': 48, 'maxGoalCells': 4, 'exit': 'buffer', 'maxValue': 48},
    {'target': 40, 'maxGoalCells': 1, 'exit': 'buffer', 'maxValue': 80},
    {'target': 64, 'maxGoalCells': 4, 'exit': 'buffer', 'maxValue': 64},
    {'target': 60, 'maxGoalCells': 1, 'exit': 'buffer', 'maxValue': 60},
    {'target': 84, 'maxGoalCells': 4, 'exit': 'buffer', 'maxValue': 84},
]


def main():
    POLICIES.mkdir(parents=True, exist_ok=True)
    (OUT / 'mapping.json').write_text(json.dumps(MAPPING, indent=2), encoding='utf-8')
    source = ROOT / 'automation/runs/binary10240/min24/buffer-rescue-005/policies/catalog.json'
    buffer30 = next(p for p in json.loads(source.read_text(encoding='utf-8'))['policies']
                    if p['target'] == 30 and p['exit'] == 'buffer'
                    and p.get('petsc', {}).get('verified'))
    library.store_policy(POLICIES, buffer30)
    # Keep prior certified work; stale imported candidates are re-evaluated
    # one target at a time below to avoid repeating full PETSc runs.
    catalog = library.load_catalog(POLICIES)
    catalog['policies'] = [p for p in catalog['policies']
                           if p.get('petsc', {}).get('verified')]
    atomic_json(POLICIES / 'catalog.json', catalog)
    for req in REQUIREMENTS:
        print('Preparing buffer', req['target'], flush=True)
        library.prepare_missing(POLICIES, [req], rounds=1500)
        # discover() may import several source variants for one transition
        # table. Certifying all of them repeats a large PETSc solve; retain
        # the strongest baseline and every variant already certified.
        catalog = library.load_catalog(POLICIES)
        candidates = [p for p in catalog['policies']
                      if p['target'] == req['target'] and p['exit'] == 'buffer'
                      and p['maxGoalCells'] == req['maxGoalCells']]
        best_source = max(candidates, key=lambda p: (bool(p.get('petsc', {}).get('verified')),
                                                     p['statistics']['p']))
        with open(best_source['source'], 'rb') as source_file:
            is_values = source_file.read(8) == b'TALLVAL4'
        if not is_values and not best_source.get('petsc', {}).get('verified'):
            # Shared entries can point at a PETSc output policy, which cannot
            # seed the baseline certifier. Re-solve that same table first.
            work = POLICIES / 'baseline-values' / str(req['target'])
            work.mkdir(parents=True, exist_ok=True)
            values = work / 'values.bin'
            local_table = work / 'table.bin'
            if not local_table.exists():
                link_or_copy(best_source['table'], local_table)
            for suffix in ('.rules.json', '.model.json'):
                sidecar = Path(str(best_source['table']) + suffix)
                local_sidecar = Path(str(local_table) + suffix)
                if sidecar.exists() and not local_sidecar.exists():
                    link_or_copy(sidecar, local_sidecar)
            if not values.exists():
                library.run_checked([library.NATIVE_DIR / 'tallnum_vi_legacy.exe',
                                     'table.bin', 1500, '1e-10', 'values.bin'], cwd=work)
            library.register(POLICIES, work / 'table.bin', values, 'buffer')
            catalog = library.load_catalog(POLICIES)
            candidates = [p for p in catalog['policies']
                          if p['target'] == req['target'] and p['exit'] == 'buffer'
                          and p['maxGoalCells'] == req['maxGoalCells']]
            best_source = next(p for p in candidates
                               if Path(p['source']).resolve() == values.resolve())
        best = next((p for p in candidates if p['id'] == best_source['id']), best_source)
        catalog['policies'] = [p for p in catalog['policies']
                               if p not in candidates or p['id'] == best['id']
                               or p.get('petsc', {}).get('verified')]
        atomic_json(POLICIES / 'catalog.json', catalog)
        certify.certify_baselines(POLICIES, restart=20)
        complete = [p for p in library.load_catalog(POLICIES, certified_only=True,
                                                     clean_only=True)['policies']
                    if p['target'] == req['target'] and p['exit'] == 'buffer'
                    and p['maxGoalCells'] == req['maxGoalCells']]
        if not complete:
            raise RuntimeError(f'Buffer {req["target"]} was not certified')
        print('Certified buffer', req['target'], flush=True)


if __name__ == '__main__':
    main()
