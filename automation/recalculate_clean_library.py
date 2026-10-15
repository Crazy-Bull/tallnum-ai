"""Recalculate standard five-cell templates under the clean-exit rule.

Old transition tables are supplied as migration sources; generated tables,
policies, fixed-policy graphs and PETSc certificates go to a new workspace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .aggressive import RISK, calculate
from .certify import certify_baselines
from .common import atomic_json
from .library import load_catalog, prepare_missing, table_header


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=1500)
    parser.add_argument('--sources',type=Path,nargs='+',required=True,
                        help='one or more existing catalogs used as migration sources')
    args=parser.parse_args()
    workspace=args.workspace.resolve();workspace.mkdir(parents=True,exist_ok=True)
    prior=[]; requirements={}
    for source_dir in args.sources:
        for item in load_catalog(source_dir)['policies']:
            try:
                header=table_header(item['table'])
            except (OSError,ValueError,KeyError):
                continue
            if header['cells']!=5 or header['target']<24 or header['maxValue']<48:
                continue
            prior.append(item)
            req={'key':f"5:{header['target']}:{item['exit']}", 'cells':5,
                 'target':header['target'],'exit':item['exit'],
                 'maxValue':max(48,header['maxValue']),
                 'maxGoalCells':header['maxGoalCells'],'bases':header['bases'],
                 'aggressiveness':[0] if header['target']<48 else list(map(float,RISK))}
            key=(req['target'],req['exit'],req['maxValue'],req['maxGoalCells'],tuple(req['bases']))
            requirements[key]=req
    catalog_path=workspace/'catalog.json'
    existing=load_catalog(workspace)
    by_id={p['id']:p for p in existing['policies']}
    for item in prior:by_id.setdefault(item['id'],item)
    atomic_json(catalog_path,{'version':1,'policies':list(by_id.values())})
    atomic_json(workspace/'recalculation.json',{
        'successNoExtraCombos':True,'minimumTarget':24,'minimumMaximumValue':48,
        'sourceCatalogs':[str(p.resolve()) for p in args.sources],
        'reusedLegacyPolicyReferences':len(prior),'uniqueBaseTemplates':len(requirements),
        'completed':[],'failed':[]})
    report=json.loads((workspace/'recalculation.json').read_text())
    for key,req in sorted(requirements.items()):
        label=':'.join(map(str,key[:4]))
        try:
            prepare_missing(workspace,[req],args.rounds)
            certify_baselines(workspace)
            if req['target']>=48:
                calculate(workspace,req['target'],RISK,(req['exit'],),args.rounds,requirement=req)
            report['completed'].append({'template':label,'requirement':req})
        except Exception as exc:
            report['failed'].append({'template':label,'requirement':req,'error':repr(exc)})
            atomic_json(workspace/'recalculation.json',report)
            print(json.dumps({'failed':label,'error':repr(exc)},ensure_ascii=False),flush=True)
            continue
        atomic_json(workspace/'recalculation.json',report)
        print(json.dumps({'completed':label,'cleanExit':True},ensure_ascii=False),flush=True)
    report['complete']=not report['failed']
    atomic_json(workspace/'recalculation.json',report)


if __name__=='__main__':main()
