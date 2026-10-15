"""Compare cache bytes against the old six-cell bridge on a format fixture."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from automation.no80_route import ROOT,OUT


class StreamCacheTests(unittest.TestCase):
    def test_stream_reader_preserves_old_query_cache_bytes(self):
        old=ROOT/'desktop/native/tallnum_automation_six_clean.exe'
        fast=OUT/'min24-cache-builder.exe'
        if not old.exists() or not fast.exists():self.skipTest('Native bridges not built')
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);table=directory/'table.bin';policy=directory/'policy.bin'
            header=struct.pack('<IIIQIII',4,6,24,144,1,1,4)+struct.pack('<IIII',1,3,5,15)
            rows=[];actions=[];signature=14695981039346656037
            def mix(value):
                nonlocal signature
                for byte in struct.pack('<Q',value):
                    signature=((signature^byte)*1099511628211)&((1<<64)-1)
            for board in range(4):
                for q1 in range(6):
                    for q2 in range(6):
                        code=board+(q1<<54)+(q2<<57);flag=1 if board==0 else 2 if board==3 else 0
                        posts=([q2<<54] if board==1 else [1+(q2<<54),q2<<54] if board==2 else [])
                        for value in (code,flag,len(posts),*posts):mix(value)
                        rows.append(struct.pack('<QBI',code,flag,len(posts))
                                    +b''.join(struct.pack('<Q',p) for p in posts))
                        actions.append(0xFFFFFFFF if board==0 else 0xFFFFFFFE if board==3 else board-1)
            boards=struct.pack('<Q',4)+b''.join(struct.pack('<IBHBB',1,0,v,1,0) for v in (24,12,8,16))
            table.write_bytes(b'TALLTRN4'+header+b''.join(rows)+boards)
            Path(str(table)+'.model.json').write_text(json.dumps({'maxValue':48,'successNoExtraCombos':True}))
            policy.write_bytes(b'TALLPOL4'+header+struct.pack('<Q',signature)
                               +struct.pack('<'+'I'*len(actions),*actions))
            env=os.environ.copy();env['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+env.get('PATH','')
            # The preserved opening bridge predates strict/guard cache formats.
            # New strict templates use their separate pending-value workers.
            for variant in ('clean','aggressive'):
                metadata={'maxValue':48,'successNoExtraCombos':True,
                          'singleEdgeGuard':variant=='strict','singleTidyExit':variant=='strict',
                          'matchEdgeGuard':variant=='match-guard'}
                Path(str(table)+'.model.json').write_text(json.dumps(metadata))
                prefix=b'TALLAPO1'+struct.pack('<d',.01) if variant=='aggressive' else b'TALLPOL4'
                policy.write_bytes(prefix+header+struct.pack('<Q',signature)
                                   +struct.pack('<'+'I'*len(actions),*actions))
                kind='match' if variant=='match-guard' else 'single'
                for binary,name in ((old,'old'),(fast,'fast')):
                    result=subprocess.run([str(binary),str(table),str(policy),kind,'cache',str(directory/(name+'.bin'))],
                                          capture_output=True,text=True,env=env)
                    self.assertEqual(result.returncode,0,variant+': '+result.stderr)
                self.assertEqual((directory/'old.bin').read_bytes(),(directory/'fast.bin').read_bytes(),variant)
