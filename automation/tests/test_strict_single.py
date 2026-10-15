import unittest
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from automation.runtime import Executor
from automation.six_template_finish import validate_configuration

class StrictSingleTests(unittest.TestCase):
    @unittest.skipUnless(Path('automation/runs/no80-dynamic/boundary-pending.exe').exists(),'Build explicit boundary worker first')
    def test_explicit_head_cache_roundtrip_and_invalid_head_rejection(self):
        native=Path('automation/runs/no80-dynamic/boundary-pending.exe').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'boundary.bin'
            payload=b'TNPEND04'+struct.pack('<10I',5,6,48,1,1,1,0,1,1,1)
            payload+=struct.pack('<I',4)+struct.pack('<4I',1,3,5,15)+struct.pack('<QQQdQ',6,1,0,1.,0)
            cache.write_bytes(payload)
            env=os.environ.copy()
            env['PATH']=str(Path('.tools/msys64/ucrt64/bin').resolve())+os.pathsep+env.get('PATH','')
            reply=subprocess.run([str(native),'query',str(cache)],input='0 2 2 4 6 1 0 8 1 0\n',
                                 text=True,capture_output=True,env=env)
            self.assertEqual(reply.returncode,0,reply.stderr)
            self.assertTrue(json.loads(reply.stdout.splitlines()[1])['success'])
            invalid=bytearray(payload);struct.pack_into('<I',invalid,8+9*4,0)
            cache.write_bytes(invalid)
            reply=subprocess.run([str(native),'query',str(cache)],text=True,capture_output=True,env=env)
            self.assertNotEqual(reply.returncode,0)
            self.assertIn('invalid explicit single boundary head',reply.stderr)

    @unittest.skipUnless(Path('automation/runs/no80-dynamic/tidy-five-pending.exe').exists(),'Build tidy five-cell worker first')
    def test_five_cell_tidy_cache_preserves_explicit_rule_flags(self):
        native=Path('automation/runs/no80-dynamic/tidy-five-pending.exe').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'five.bin'
            payload=b'TNPEND03'+struct.pack('<10I',5,6,48,1,1,1,0,0,1,4)
            payload+=struct.pack('<4I',1,3,5,15)+struct.pack('<QQQdQ',6,1,0,1.,0)
            cache.write_bytes(payload)
            env=os.environ.copy()
            env['PATH']=str(Path('.tools/msys64/ucrt64/bin').resolve())+os.pathsep+env.get('PATH','')
            reply=subprocess.run([str(native),'query',str(cache)],input='0 2 2 4 6 1 0 8 1 0\n',
                                 text=True,capture_output=True,env=env)
            self.assertEqual(reply.returncode,0,reply.stderr)
            outputs=[json.loads(line) for line in reply.stdout.splitlines()]
            self.assertEqual(outputs[0]['status'],'ready')
            self.assertTrue(outputs[1]['success'])

    @unittest.skipUnless(Path('automation/runs/six-strict-single-001/bin/pending.exe').exists(),'Build strict pending worker first')
    def test_strict_cache_roundtrip_restores_success_condition(self):
        native=Path('automation/runs/six-strict-single-001/bin/pending.exe').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'strict.bin'
            payload=b'TNPEND03'+struct.pack('<10I',6,32,48,1,1,1,0,1,1,4)
            payload+=struct.pack('<4I',1,3,5,15)+struct.pack('<QQQdQ',6,1,0,1.,1)
            payload+=struct.pack('<IBHBBHBB',2,0,32,1,0,8,1,0)
            cache.write_bytes(payload)
            env=os.environ.copy()
            env['PATH']=str(Path('.tools/msys64/ucrt64/bin').resolve())+os.pathsep+env.get('PATH','')
            reply=subprocess.run([str(native),'query',str(cache)],input='0 2 2 4 32 1 0 8 1 0\n',
                text=True,capture_output=True,env=env)
            self.assertEqual(reply.returncode,0,reply.stderr)
            outputs=[json.loads(line) for line in reply.stdout.splitlines()]
            self.assertEqual(outputs[0]['status'],'ready')
            self.assertTrue(outputs[1]['success'])

    def test_residual_limit_applies_above_and_below_goal(self):
        executor=Executor.__new__(Executor)
        executor.policies={'six':{'singleTidyExit':True},'legacy':{}}
        leaf={'policy':'six'}
        tile=lambda n:{'value':n,'physicalCount':1,'kind':'tile'}
        self.assertTrue(executor._tidy_single_exit(leaf,[]))
        self.assertTrue(executor._tidy_single_exit(leaf,[tile(8)]))
        self.assertFalse(executor._tidy_single_exit(leaf,[tile(10)]))
        self.assertFalse(executor._tidy_single_exit(leaf,[tile(2),tile(4)]))
        self.assertFalse(executor._tidy_single_exit(leaf,[{'value':6,'physicalCount':2,'kind':'group'}]))
        self.assertTrue(executor._tidy_single_exit({'policy':'legacy'},[tile(10),tile(4)]))

    @unittest.skipUnless(Path('automation/runs/no80-dynamic/tidy-match-pending.exe').exists(),'Build tidy match worker first')
    def test_exact_match_cache_restores_boundary_value_and_group_goal(self):
        native=Path('automation/runs/no80-dynamic/tidy-match-pending.exe').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'match.bin'
            payload=b'TNPEND05'+struct.pack('<13I',5,32,48,5,1,1,1,0,1,3,32,0,4)
            payload+=struct.pack('<4I',1,3,5,15)+struct.pack('<QQQdQ',6,1,0,1.,0)
            cache.write_bytes(payload)
            env=os.environ.copy()
            env['PATH']=str(Path('.tools/msys64/ucrt64/bin').resolve())+os.pathsep+env.get('PATH','')
            reply=subprocess.run([str(native),'query',str(cache)],input='0 2 2 4 32 2 1 8 1 0\n',
                                 text=True,capture_output=True,env=env)
            self.assertEqual(reply.returncode,0,reply.stderr)
            outputs=[json.loads(line) for line in reply.stdout.splitlines()]
            self.assertTrue(outputs[1]['success'])

    @unittest.skipUnless(Path('automation/runs/no80-dynamic/physical-extend-pending.exe').exists(),'Build physical extension worker first')
    def test_physical_extension_cache_restores_connection_rule(self):
        native=Path('automation/runs/no80-dynamic/physical-extend-pending.exe').resolve()
        with tempfile.TemporaryDirectory() as tmp:
            cache=Path(tmp)/'extend.bin'
            payload=b'TNPEND06'+struct.pack('<14I',5,64,64,4,1,1,1,0,1,3,32,0,1,4)
            payload+=struct.pack('<4I',1,3,5,15)+struct.pack('<QQQdQ',6,1,0,1.,0)
            cache.write_bytes(payload)
            env=os.environ.copy()
            env['PATH']=str(Path('.tools/msys64/ucrt64/bin').resolve())+os.pathsep+env.get('PATH','')
            reply=subprocess.run([str(native),'query',str(cache)],input='0 2 2 4 64 1 0 8 1 0\n',
                                 text=True,capture_output=True,env=env)
            self.assertEqual(reply.returncode,0,reply.stderr)
            self.assertTrue(json.loads(reply.stdout.splitlines()[1])['success'])

    def test_old_table_cannot_certify_strict_rules(self):
        config=dict(cells=6,target=32,exit='single',maxGoalCells=1,maxValue=48,
            bases=[1,3,5,15],successSide='above',successNoExtraCombos=True,
            singleEdgeGuard=True,singleTidyExit=True)
        header={**config,'above':1}
        validate_configuration(config,header)
        for field in ('singleEdgeGuard','singleTidyExit'):
            with self.assertRaisesRegex(ValueError,field):
                validate_configuration(config,{**header,field:False})

if __name__=='__main__':unittest.main()
