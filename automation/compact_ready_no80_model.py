"""Compress completed owned pending-only tables without changing logical hashes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from .common import atomic_json,fingerprint
from .no80_route import OUT


def compact(name):
    root=(OUT/'min24-models').resolve()
    directory=(root/name).resolve()
    if not directory.is_relative_to(root):raise ValueError('Outside owned model directory')
    policy=json.loads((directory/'policy.json').read_text())
    if not policy.get('pendingValue') or not policy.get('disableStaticFallback'):
        raise ValueError('Model requires raw tables at runtime')
    results=[]
    for filename in ('table.bin','values.bin'):
        source=directory/filename
        if not source.exists():continue
        destination=Path(str(source)+'.gz');temporary=Path(str(destination)+'.'+uuid.uuid4().hex+'.tmp')
        expected=fingerprint(source)
        with source.open('rb') as inp,gzip.open(temporary,'wb',compresslevel=1) as out:
            shutil.copyfileobj(inp,out,1024*1024)
        digest=hashlib.sha256()
        with gzip.open(temporary,'rb') as inp:
            for chunk in iter(lambda:inp.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=expected:raise ValueError('Compression changed artifact content')
        temporary.replace(destination)
        results.append({'file':filename,'sha256':expected,'originalBytes':source.stat().st_size,
                        'compressedBytes':destination.stat().st_size})
        source.unlink();print(json.dumps(results[-1]),flush=True)
    if results:atomic_json(directory/'compressed-artifacts.json',results)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('name');compact(parser.parse_args().name)
