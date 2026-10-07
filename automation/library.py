from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import struct
from collections import OrderedDict
from copy import deepcopy
from contextlib import contextmanager
import time

from .common import atomic_json, fingerprint, event
from .statistics import evaluate_file

ROOT = Path(__file__).resolve().parent.parent
NATIVE_DIR = ROOT / ('desktop/native' if (ROOT/'desktop/native').exists() else 'native')
NATIVE = NATIVE_DIR / 'tallnum_automation_clean.exe'
MODEL = ROOT / 'tallnum_reachable.cpp'
SHARED_CLEAN_LIBRARY = Path(os.environ.get('TALLNUM_SHARED_LIBRARY', str(ROOT/'automation/runs/shared-clean')))


def current_rule():
    # Adding a configurable bound preserves the corrected EDGE semantics.
    return 'edge-recheck-v1'


def compatible_rule(rule):
    return rule in (current_rule(), '91de4bf6f03efea924c3e277971227881760244572ef74d162d3df6098dcb06d')


def table_rule(table):
    meta=Path(str(table)+'.rules.json')
    if not meta.exists():
        return None
    data=json.loads(meta.read_text(encoding='utf-8'))
    if data.get('tableSha256') != fingerprint(table):
        raise ValueError(f'Transition table changed since rule certification: {table}')
    model=Path(str(table)+'.model.json')
    if (model.exists() or data.get('modelSha256')) and (not model.exists() or data.get('modelSha256')!=fingerprint(model)):
        raise ValueError(f'Model bound changed since table certification: {table}')
    rule=data.get('ruleSha256')
    return current_rule() if compatible_rule(rule) else rule


def run_checked(args, **kwargs):
    p = subprocess.run(list(map(str, args)), capture_output=True, text=True, encoding='utf-8', errors='replace', **kwargs)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-4000:])
    return p.stdout


def table_header(path):
    with open(path, 'rb') as f:
        if f.read(8) != b'TALLTRN4':
            raise ValueError('Not v4')
        version, cells, target, states, span, above, count = struct.unpack('<IIIQIII', f.read(32))
        bases = list(struct.unpack('<' + 'I'*count, f.read(count*4)))
    meta=Path(str(path)+'.model.json')
    model=json.loads(meta.read_text(encoding='utf-8')) if meta.exists() else {}
    maximum=model.get('maxValue',target)
    clean=model.get('successNoExtraCombos',False)
    guard=model.get('matchEdgeGuard',False)
    single_guard=model.get('singleEdgeGuard',False)
    tidy=model.get('singleTidyExit',False)
    if not isinstance(single_guard,bool) or not isinstance(tidy,bool):
        raise ValueError('Invalid six-cell single model condition')
    if (single_guard or tidy) and (cells!=6 or span!=1 or not clean):
        raise ValueError('Six-cell single rules require a clean single table')
    if not isinstance(guard,bool):
        raise ValueError('Invalid matchEdgeGuard model condition')
    if not isinstance(clean,bool):
        raise ValueError('Invalid successNoExtraCombos model condition')
    if not isinstance(maximum,int) or not target <= maximum <= 65535:
        raise ValueError('Invalid maximum intermediate value')
    return dict(version=version, cells=cells, target=target, states=states, maxValue=maximum,
                maxGoalCells=span, above=above, bases=bases, successNoExtraCombos=clean, matchEdgeGuard=guard,
                singleEdgeGuard=single_guard,singleTidyExit=tidy)


def discover(root=ROOT):
    """Read known top-level artifacts and completed aggressive runs only."""
    result = []
    for table in sorted(Path(root).glob('v4_5_*.bin')):
        try:
            h = table_header(table)
        except (ValueError, struct.error):
            continue
        stem = table.with_suffix('')
        candidates = [Path(str(stem)+suffix) for suffix in ('.policy.bin', '.policy2.bin', '.values.bin')]
        for source in candidates:
            if source.exists():
                result.append({'table': str(table), 'source': str(source), **h})
    for table in sorted((Path(root)/'aggressive-version/runs').glob('*/table.bin')):
        h = table_header(table)
        for source in sorted(table.parent.glob('07_petsc_actual.policy.bin')):
            result.append({'table': str(table), 'source': str(source), **h})
    shared=SHARED_CLEAN_LIBRARY/'catalog.json'
    if shared.exists():
        catalog=json.loads(shared.read_text(encoding='utf-8'))
        for item in catalog.get('policies',[]):
            try:h=table_header(item['table'])
            except (OSError,ValueError,KeyError,struct.error):continue
            if h['successNoExtraCombos']:
                result.append({'table':item['table'],'source':item['source'],**h})
    return result


def load_catalog(directory, certified_only=False, clean_only=False, include_shared=False):
    file = Path(directory)/'catalog.json'
    catalog=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {'version': 1, 'policies': []}
    if include_shared and Path(directory).resolve()!=SHARED_CLEAN_LIBRARY.resolve():
        shared_file=SHARED_CLEAN_LIBRARY/'catalog.json'
        if shared_file.exists():
            shared=json.loads(shared_file.read_text(encoding='utf-8'))
            items={p['id']:p for p in catalog['policies']}
            for item in shared.get('policies',[]):
                if item.get('successNoExtraCombos') is True:
                    items.setdefault(item['id'],item)
            catalog['policies']=list(items.values())
    catalog['policies']=[p for p in catalog['policies'] if compatible_rule(p.get('ruleSha256'))]
    if clean_only:
        catalog['policies']=[p for p in catalog['policies'] if p.get('successNoExtraCombos') is True
                             and p.get('exitSemantics')=='success-board-clean-v3']
    if certified_only:
        catalog['policies']=[p for p in catalog['policies'] if p.get('petsc',{}).get('verified')
                             and p.get('exitSemantics') in ('success-board-v2','success-board-clean-v3')
                             and p.get('petsc',{}).get('exitEvaluationRounds',0)>=2]
    return catalog


@contextmanager
def catalog_lock(directory):
    import msvcrt
    path=Path(directory)/'catalog.lock'
    with path.open('a+b') as file:
        if file.tell()==0:
            file.write(b'0'); file.flush()
        while True:
            file.seek(0)
            try:
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
                break
            except OSError:
                time.sleep(.05)
        try:
            yield
        finally:
            file.seek(0)
            msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)


def store_policy(directory,item):
    with catalog_lock(directory):
        catalog=load_catalog(directory)
        catalog['policies']=[p for p in catalog['policies'] if p['id']!=item['id']]+[item]
        atomic_json(Path(directory)/'catalog.json',catalog)


def native_exit(kind):
    # Buffer permits an adjacent Group exactly as the existing native match
    # exporter does; Python verifies the anchor and explicit EDGE transition.
    return 'match' if kind=='buffer' else kind


def register(directory, table, source, exit_kind, native=NATIVE, *, variant_aggressiveness=None):
    directory = Path(directory).resolve()
    table, source = Path(table).resolve(), Path(source).resolve()
    h = table_header(table)
    if h['cells'] != 5:
        raise ValueError('Only five-cell policies may be registered')
    if h['matchEdgeGuard'] and exit_kind!='match':
        raise ValueError('Match EDGE guard is only valid for match exits')
    if exit_kind=='buffer' and h['maxGoalCells']>4:
        raise ValueError('Buffer goals must occupy at most four cells')
    rule=table_rule(table)
    if rule != current_rule():
        raise ValueError('Transition table uses an old or uncertified EDGE rule; regenerate it with the current generator')
    hashes = {k: fingerprint(v) for k, v in [('table', table), ('source', source), ('native', native)]}
    identifier = f"{h['target']}-{exit_kind}-{hashes['source'][:12]}-{hashes['table'][:12]}-{hashes['native'][:8]}"
    if h['maxValue']!=h['target']:
        identifier+=f"-max{h['maxValue']}"
    if variant_aggressiveness is not None:
        identifier+='-variant'+format(float(variant_aggressiveness), '.12g').replace('.', 'p')
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / (identifier+'.json')
    if manifest.exists():
        item = json.loads(manifest.read_text(encoding='utf-8'))
        # A cached manifest is usable only while its exported policy exists.
        if not Path(item['policy']).exists() or fingerprint(item['policy']) != item['policySha256']:
            raise ValueError('Cached policy missing or changed')
    else:
        prefix = directory / identifier
        event('exporting', target=h['target'], exit=exit_kind)
        output = run_checked([native, table, source, native_exit(exit_kind), 'export', prefix])
        metadata = json.loads(next(line for line in reversed(output.splitlines()) if line.startswith('{')))
        if metadata.get('matchEdgeGuard',False)!=h['matchEdgeGuard']:
            raise ValueError('Native exporter does not support the match EDGE guard')
        if metadata.get('successNoExtraCombos',False)!=h['successNoExtraCombos']:
            raise ValueError('Native exporter does not support the table victory condition')
        graph = Path(str(prefix)+'.graph.bin')
        event('statistics', target=h['target'], exit=exit_kind, states=metadata['reachableStates'])
        stats = evaluate_file(graph)
        item = {'id': identifier, 'target': h['target'], 'exit': exit_kind, 'table': str(table),
                'ruleSha256': rule, 'maxValue': h['maxValue'],
                'source': str(source), 'policy': str(prefix)+'.policy.bin', 'hashes': hashes,
                'policySha256': fingerprint(str(prefix)+'.policy.bin'),
                'statistics': stats, **{k:v for k,v in metadata.items() if k not in ('target','exit')}}
        atomic_json(manifest, item)
    if item.get('successNoExtraCombos',False)!=h['successNoExtraCombos']:
        raise ValueError('Cached policy victory condition differs from its table')
    item.update(bases=h['bases'], cells=h['cells'], maxGoalCells=h['maxGoalCells'],
                successNoExtraCombos=h['successNoExtraCombos'],matchEdgeGuard=h['matchEdgeGuard'])
    if variant_aggressiveness is not None:
        item['variantAggressiveness']=float(variant_aggressiveness)
    else:
        item.pop('variantAggressiveness', None)
    item['source']=str(source)
    atomic_json(manifest, item)
    store_policy(directory,item)
    return item


def prepare_missing(directory, missing, rounds=5000, native=NATIVE):
    """Generate only required five-cell parameters in isolated directories."""
    assets = discover()
    generator = NATIVE_DIR/'tallnum_reachable_clean.exe'
    if not generator.exists():
        raise FileNotFoundError('Build the clean-exit generator with automation/build.ps1 first')
    vi = NATIVE_DIR/'tallnum_vi_legacy.exe'
    for requirement in missing:
        target, span, kind = requirement['target'], requirement['maxGoalCells'], requirement['exit']
        maximum=max(48,requirement.get('maxValue', target))
        if target<24:
            raise ValueError('Template targets must be at least 24')
        guard=bool(requirement.get('matchEdgeGuard',False))
        if guard and kind!='match':
            raise ValueError('Match EDGE guard is only valid for match exits')
        bases=requirement.get('bases', [1,3,5,15])
        matches = [a for a in assets if a['target'] == target and a['maxGoalCells'] == span
                   and a['maxValue']==maximum and a['above'] and a['bases'] == bases
                   and a['successNoExtraCombos'] and a['matchEdgeGuard']==guard
                   and table_rule(a['table']) == current_rule()]
        if matches:
            # Import fixed policies first, and retain distinct existing variants.
            for match in matches:
                register(directory, match['table'], match['source'], kind, native)
            continue
        legacy_tables=[]
        for prior in load_catalog(directory).get('policies',[]):
            try:
                prior_table=Path(prior['table'])
                prior_header=table_header(prior_table)
                if (prior_header['cells']==5 and prior_header['target']==target
                        and prior_header['maxGoalCells']==span and prior_header['maxValue']==maximum
                        and prior_header['above'] and prior_header['bases']==bases
                        and not prior_header['successNoExtraCombos']
                        and table_rule(prior_table)==current_rule()):
                    legacy_tables.append(prior_table)
            except (OSError,ValueError,KeyError,struct.error):
                continue
        # The generator reopens the old success frontier and expands it under
        # the stricter predicate, preserving all unaffected transition rows.
        reuse_table=legacy_tables[0] if legacy_tables and not guard else None
        suffix = '' if bases == [1,3,5,15] else '-bases'+__import__('hashlib').sha256(','.join(map(str,bases)).encode()).hexdigest()[:12]
        if guard:
            suffix+='-match-edge-guard'
        work = Path(directory).resolve()/'generated'/current_rule()/f'5-{target}-{span}-max{maximum}{suffix}-cleanexit'
        work.mkdir(parents=True, exist_ok=True)
        table, values = work/'table.bin', work/'values.bin'
        if not table.exists():
            event('generating', target=target, maxGoalCells=span)
            basis_arg = 'all' if generator.name=='tallnum_reachable_routes.exe' and bases==list(range(1,maximum+1,2)) else ','.join(map(str,bases))
            args=[generator, '--cells', '5', '--target', target, '--max-value', maximum, '--max-goal-cells', span,
                         '--bases', basis_arg, '--success-side', 'above', '--success-no-extra-combos', '1',
                         '--output', 'table.bin', '--match-edge-guard', int(guard)]
            if reuse_table is not None:
                args.extend(['--reuse-table',reuse_table])
            run_checked(args, cwd=work)
            if reuse_table is not None:
                model_path=Path(str(table)+'.model.json')
                model_data=json.loads(model_path.read_text(encoding='utf-8'))
                model_data['reusedLegacyTableSha256']=fingerprint(reuse_table)
                atomic_json(model_path,model_data)
            atomic_json(Path(str(table)+'.rules.json'),{'ruleSha256':current_rule(),
                        'sourceSha256':fingerprint(MODEL),
                        'modelSha256':fingerprint(str(table)+'.model.json'),
                        'tableSha256':fingerprint(table)})
        if table_rule(table) != current_rule():
            raise ValueError('Generated table lacks current EDGE rule certification')
        if not table_header(table)['successNoExtraCombos']:
            raise ValueError('Regenerate the table with no extra combination blocks at success')
        if not values.exists():
            event('solving', target=target, maxGoalCells=span, rounds=rounds)
            run_checked([vi, 'table.bin', rounds, '1e-10', 'values.bin'], cwd=work)
        register(directory, table, values, kind, native)


class PolicyWorker:
    def __init__(self, item, native=NATIVE, _reuse_validated_identity=False):
        self._fallback=None
        self._fallback_item=None
        native=Path(item.get('nativeBridge',native))
        interface=native_exit(item.get('nativeExitOverride',item['exit']))
        self.responses=OrderedDict()
        if not _reuse_validated_identity:
            if table_rule(item['table'])!=current_rule():
                raise ValueError('Uncertified model or altered bound')
            if item.get('maxValue',item['target'])!=table_header(item['table'])['maxValue']:
                raise ValueError('Policy maximum value does not match its transition table')
            if fingerprint(item['policy']) != item['policySha256'] or fingerprint(item['table']) != item['hashes']['table']:
                raise ValueError('Policy/table fingerprint mismatch')
        pending=item.get('pendingValue')
        self.item_pending=bool(pending)
        for field in ('singleEdgeGuard','singleTidyExit'):
            if item.get(field,False)!=table_header(item['table']).get(field,False):
                raise ValueError('Policy/table single rule mismatch: '+field)
        if pending is not None:
            # If a live state falls outside the saved W frontier, preserve the
            # old fixed-policy executor as a local fallback. The two workers
            # share the exact certified policy/table; this only affects the
            # opt-in search mode.
            self._fallback_item=dict(item) if item.get('cells',5)==5 else None
            if self._fallback_item is not None:
                for key in ('pendingValue','pendingValueSha256','pendingValueMeta','pendingNative'):
                    self._fallback_item.pop(key,None)
            self._fallback_native=native
            self._fallback=None
            if item.get('cells',5) not in (5,6) or item.get('exit') not in ('single','match','extend','buffer'):
                raise ValueError('Pending-value search supports five-cell route/buffer exits and six-cell single exits')
            if fingerprint(pending)!=item['pendingValueSha256']:
                raise ValueError('Pending-value fingerprint mismatch')
            if not item.get('pendingNative'):
                raise ValueError('Pending-value worker executable is missing')
            meta_path=item.get('pendingValueMeta')
            if not meta_path or not Path(meta_path).exists():
                raise ValueError('Pending-value metadata is missing')
            pending_meta=json.loads(Path(meta_path).read_text(encoding='utf-8'))
            header=table_header(item['table'])
            fmt=pending_meta.get('format')
            if fmt=='TNPEND01':
                if item.get('cells',5)!=5 or item.get('exit')!='single' or header['matchEdgeGuard']:
                    raise ValueError('Legacy pending values support only unguarded five-cell single definitions')
                expected={'format':'TNPEND01','pendingSha256':item['pendingValueSha256'],
                          'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                          'target':item['target'],'exit':item['exit'],
                          'successNoExtraCombos':header['successNoExtraCombos'],
                          'matchEdgeGuard':False}
            elif fmt in ('TNPEND02','TNPEND03'):
                if header['cells']==6 and item.get('exit')!='single':
                    raise ValueError('Six-cell pending-value search supports single exits only')
                if item.get('exit')=='buffer' and (header['cells']!=5 or header['maxGoalCells']>4):
                    raise ValueError('Buffer pending-value search requires a five-cell buffer model with maxGoalCells <= 4')
                expected={'format':fmt,'pendingSha256':item['pendingValueSha256'],
                          'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                          'target':item['target'],'exit':item['exit'],
                          'successNoExtraCombos':header['successNoExtraCombos'],
                          'matchEdgeGuard':header['matchEdgeGuard'],
                          'maxValue':header['maxValue'],'maxGoalCells':header['maxGoalCells'],
                          'cells':header['cells']}
                if fmt=='TNPEND03':
                    expected.update(singleEdgeGuard=header.get('singleEdgeGuard',False),
                                    singleTidyExit=header.get('singleTidyExit',False))
                elif header.get('singleEdgeGuard') or header.get('singleTidyExit'):
                    raise ValueError('Strict single rules require TNPEND03')
            else:
                raise ValueError(f'Unsupported pending-value format: {fmt}')
            if any(pending_meta.get(k)!=v for k,v in expected.items()):
                raise ValueError('Pending-value metadata does not match its table/policy rules')
            command=[str(item['pendingNative']), 'query', str(pending)]
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8',
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            ready=self._response()
            if ready.get('status')!='ready':
                self.close()
                raise RuntimeError(f'Pending-value worker did not initialize: {ready}')
            return
        cache=Path(item['policy']).with_suffix('.query.bin')
        meta=cache.with_suffix('.json')
        header=table_header(item['table'])
        if item.get('successNoExtraCombos',False)!=header['successNoExtraCombos']:
            raise ValueError('Policy victory condition does not match its table')
        expected={'policy':item['policySha256'],'table':item['hashes']['table'],
                  'format':('TNQUERY5' if header.get('singleEdgeGuard') or header.get('singleTidyExit') else
                            'TNQUERY4' if header['matchEdgeGuard'] else ('TNQUERY3' if header['successNoExtraCombos'] else 'TNQUERY2')),
                  'maxValue':header['maxValue']}
        if header.get('singleEdgeGuard') or header.get('singleTidyExit'):
            expected.update(singleEdgeGuard=header['singleEdgeGuard'],singleTidyExit=header['singleTidyExit'])
        if header['successNoExtraCombos']:
            expected['successNoExtraCombos']=True
        if header['matchEdgeGuard']!=item.get('matchEdgeGuard',False):
            raise ValueError('Policy match EDGE guard differs from its table')
        if header['matchEdgeGuard']:
            if item['exit']!='match':
                raise ValueError('Match EDGE guard requires match exit')
            expected['matchEdgeGuard']=True
        valid=False
        if meta.exists() and cache.exists():
            identity=json.loads(meta.read_text(encoding='utf-8'))
            valid=all(identity.get(k)==v for k,v in expected.items()) and identity.get('sha256')==fingerprint(cache)
        if not valid:
            temporary=cache.with_suffix('.tmp')
            event('query-cache',target=item['target'],exit=item['exit'])
            run_checked([native,item['table'],item['policy'],interface,'cache',temporary])
            os.replace(temporary,cache)
            atomic_json(meta,{**expected,'sha256':fingerprint(cache)})
        self.process = subprocess.Popen([str(native), 'query', str(cache), interface],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready=self._response()
        if ready.get('status')!='ready':
            self.close()
            raise RuntimeError(f'Policy worker did not initialize: {ready}')

    def _response(self):
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError(self.process.stderr.read()[-4000:] or 'Policy worker exited')
            if line.startswith('{'):
                return json.loads(line)

    def query(self, board, fpos, queue):
        fields = [fpos, len(board), *queue]
        for t in board:
            fields.extend((t['value'], t['physicalCount'], int(t['kind'] == 'group')))
        key=tuple(fields)
        if key in self.responses:
            self.responses.move_to_end(key)
            return deepcopy(self.responses[key])
        self.process.stdin.write(' '.join(map(str, fields))+'\n')
        self.process.stdin.flush()
        result=self._response()
        search_error=result.get('error') if self.item_pending else None
        # A five-cell native cache miss can surface as either an explicit
        # domain miss or a query error. The certified five-cell fixed policy
        # is a conservative fallback. Six-cell static caches are too large to
        # duplicate here; their domain misses stay with route entry-bridging.
        out_of_model=(result.get('status') in ('out-of-model','error'))
        if out_of_model and self._fallback_item is not None:
            if self._fallback is None:
                # This item is an exact copy of the already-validated dynamic
                # worker identity with only pending-cache fields removed.
                self._fallback=PolicyWorker(self._fallback_item,self._fallback_native,
                                            _reuse_validated_identity=True)
            legacy=self._fallback.query(board,fpos,queue)
            legacy['searchFallback']='out-of-model'
            legacy['searchError']=search_error
            result=legacy
        self.responses[key]=deepcopy(result)
        if len(self.responses)>10000:
            self.responses.popitem(last=False)
        return result

    def close(self):
        fallback=getattr(self,'_fallback',None)
        if fallback is not None:
            fallback.close()
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()
