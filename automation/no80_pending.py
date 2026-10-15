"""Add live preview search to newly used low-order definitions.

New caches use optimal iid completion values; no PETSc certificate is invented.
Their full-game behavior remains subject to the paired real-engine validation.
"""
import json
import argparse
from pathlib import Path
import shutil
import subprocess

from .common import atomic_json, fingerprint
from .no80_route import ROOT, OUT
from .library import table_header


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=OUT/'catalog.json')
    parser.add_argument('--output',type=Path,default=OUT/'catalog-dynamic.json')
    parser.add_argument('--refresh',action='store_true',help='Rebuild local pending files from saved values')
    args=parser.parse_args()
    catalog=json.loads(args.catalog.read_text())
    directory=OUT/'new-pending'
    directory.mkdir(exist_ok=True)
    for item in catalog['policies']:
        if item.get('pendingValue'):continue
        ident=item['id']
        pending=directory/(ident+'.bin')
        meta=pending.with_suffix('.json')
        values=directory/(ident+'.values.bin')
        table=directory/'scratch-table.bin'
        log=directory/(ident+'.vi.log')
        if args.refresh or not (pending.exists() and meta.exists()):
            source=Path(item['source']).parent/'01_values.bin'
            original=Path(item['source'])
            if not source.exists() and original.exists():
                with original.open('rb') as probe:magic=probe.read(8)
                if magic in (b'TALLAVA1',b'TALLVAL4'):source=original
            if source.exists():
                with source.open('rb') as src,values.open('wb') as dst:
                    magic=src.read(8)
                    if magic==b'TALLAVA1':src.read(8)
                    elif magic!=b'TALLVAL4':raise ValueError('Unknown values format')
                    dst.write(b'TALLVAL4');shutil.copyfileobj(src,dst)
                provenance={'method':'saved fixed policy values','source':str(source)}
            else:
                shutil.copyfile(item['table'],table)
                with log.open('w') as dest:
                    proc=subprocess.run([str(ROOT/'tallnum_vi.exe'),str(table),'1000','1e-10',str(values)],stdout=dest,stderr=subprocess.STDOUT)
                if proc.returncode:raise RuntimeError('VI failed: '+str(log))
                result=json.loads(Path(str(table)+'.result.json').read_text())
                provenance={'method':'optimal iid-six VI','result':result}
            native=ROOT/'automation/pending_value_allcells.exe'
            proc=subprocess.run([str(native),'build',str(item['table']),str(values),str(pending)],capture_output=True,text=True)
            if proc.returncode:raise RuntimeError(proc.stderr+proc.stdout)
            header=table_header(item['table'])
            metadata={'format':'TNPEND02','pendingSha256':fingerprint(pending),
                      'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                      'target':item['target'],'exit':item['exit'],'cells':item.get('cells',5),
                      'successNoExtraCombos':header['successNoExtraCombos'],
                      'matchEdgeGuard':header['matchEdgeGuard'],
                      'maxValue':item['maxValue'],'maxGoalCells':item['maxGoalCells'],
                      'sourceValuesSha256':fingerprint(values),'valueProvenance':provenance,
                      'probabilitySemantics':'local completion model; empirical full-game validation required'}
            atomic_json(meta,metadata)
            for path in (values,table,Path(str(table)+'.result.json'),Path(str(table)+'.initial.csv')):
                path.unlink(missing_ok=True)
        metadata=json.loads(meta.read_text())
        item.update(pendingValue=str(pending),pendingValueMeta=str(meta),
                    pendingValueSha256=metadata['pendingSha256'],
                    pendingNative=str(ROOT/'automation/pending_value_allcells.exe'))
        atomic_json(args.output,catalog)
        print(json.dumps({'policy':ident,'target':item['target'],'exit':item['exit'],
                          'pendingBytes':pending.stat().st_size}),flush=True)


if __name__=='__main__':main()
