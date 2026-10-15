"""Packaged UI/IPC smoke test with an isolated user profile and hidden window."""
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[2]
output=root/'automation/runs/desktop-smoke'
output.mkdir(parents=True,exist_ok=True)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
exe=root/'desktop/release-0.3.0/win-unpacked/Tallnum 计算器.exe'
process=subprocess.Popen([str(exe),f'--remote-debugging-port={port}',
    f'--user-data-dir={output / "profile"}','--smoke-test'],stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    with sync_playwright() as pw:
        browser=None
        for _ in range(80):
            try:
                browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}',timeout=1000)
                break
            except Exception:
                time.sleep(.25)
        if browser is None:
            raise RuntimeError('Could not attach to isolated Electron')
        page=browser.contexts[0].pages[0]
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        bound=page.get_by_text('最大出现数字',exact=False)
        bound.wait_for()
        job=page.evaluate('''async directory => await window.tallnum.create({
            name: 'maximum-value-smoke', directory,
            rules: {cells: 3,target: 16,maxValue: 32,aggressiveness: .05,maxGoalCells: 1,bases: [1,3,5,15],successSide: 'above'},
            repeats: 1, stages: [{kind: 'vi',rounds: 20,tolerance: 1e-9}]
        })''',str(output/'bound-job'))
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            jobs=page.evaluate('window.tallnum.list()')
            calculated=next(item for item in jobs if item['id']==job['id'])
            if calculated['status'] in ('completed','failed','paused'):
                break
            time.sleep(.5)
        assert calculated['status']=='completed',calculated
        assert calculated['spec']['rules']['maxValue']==32
        assert calculated['results'][-1]['stopReason']=='固定策略实际成功率复核'
        assert sum(r['kind']=='petsc' for r in calculated['results'])>=2
        model=json.loads((output/'bound-job'/job['id']/'transitions.bin.model.json').read_text())
        assert model['maxValue']==32
        certified=json.loads((output/'bound-job'/job['id']/'transitions.bin.rules.json').read_text())
        assert certified['ruleSha256']=='edge-recheck-v1' and certified['modelSha256']
        page.get_by_role('button',name=re.compile('自动玩')).click()
        page.get_by_role('heading',name='五格定式组合 · 目标 768').wait_for()
        page.get_by_role('textbox').fill(str(output/'data'))
        page.get_by_role('button',name='检查拆解与缺失定式').click()
        page.get_by_text('六格 384',exact=True).wait_for(timeout=30000)
        status=page.evaluate('window.tallnum.automationStatus()')
        assert status['plan']['target']==768 and status['plan']['triples']['384']=={'a':128,'b':128}
        assert not status['error'],status['error']
        assert not errors,errors
        # Windows does not necessarily composite a never-shown Electron
        # window. Assert its rendered layout rather than waiting for a bitmap.
        assert page.evaluate('document.querySelector("main").clientWidth > 600')
        (output/'result.json').write_text(json.dumps({'passed':True,'errors':errors,'missing':len(status['plan']['missing'])}),encoding='utf-8')
        print('Packaged hidden UI, preload IPC, Python backend and 768 plan: passed')
        browser.close()
finally:
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
