"""Stream one replay at a time from large validation reports."""
import json
import gzip
from pathlib import Path
import sys
import ijson
from ijson.common import ObjectBuilder


def emit(path):
    mode=None
    builder=None
    depth=0
    with (gzip.open(path,'rb') if str(path).endswith('.gz') else Path(path).open('rb')) as source:
        for prefix,event,value in ijson.parse(source,use_float=True):
            if prefix=='reports.item' and event=='start_map':mode=None
            if prefix=='reports.item.mode' and event=='string':mode=value
            if builder is None:
                if prefix!='reports.item.replays.item' or event!='start_map':continue
                builder=ObjectBuilder();depth=0
            builder.event(event,value)
            if event in ('start_map','start_array'):depth+=1
            elif event in ('end_map','end_array'):depth-=1
            if depth==0:
                print(json.dumps({'mode':mode,'replay':builder.value},separators=(',',':')),flush=True)
                builder=None
    if builder is not None:raise ValueError('Truncated replay')


def attach(path,result):
    path=Path(path)
    summary=json.loads(result)
    if str(path).endswith('.gz'):
        # Compressed reports remain immutable; retain the check as a sidecar.
        sidecar=Path(str(path)+'.engine-check.json')
        if sidecar.exists() and json.loads(sidecar.read_text())!=summary:
            raise ValueError('Existing original engine check differs')
        sidecar.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        return
    with path.open('rb') as source:
        old=next(ijson.items(source,'originalEngineCheck',use_float=True),None)
    if old is not None:
        if old!=summary:raise ValueError('Existing original engine check differs')
    else:
        # Preserve the original large report and add only a small root field.
        with path.open('r+b') as dest:
            dest.seek(0,2);size=dest.tell()
            dest.seek(max(0,size-4096));tail=dest.read()
            end=tail.rstrip()
            if not end.endswith(b'}'):raise ValueError('Report has no closing root object')
            pos=size-len(tail)+len(end)-1
            dest.seek(pos)
            dest.write(b',\n  "originalEngineCheck":'+json.dumps(summary).encode()+b'\n}\n')
            dest.truncate()
    Path(str(path)+'.engine-check.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__':
    if sys.argv[1]=='--attach':attach(sys.argv[2],sys.argv[3])
    else:emit(sys.argv[1])
