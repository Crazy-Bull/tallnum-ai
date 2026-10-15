"""Real hidden Electron UI -> preload -> Python planner integration test."""
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'automation/.deps'))
from playwright.sync_api import sync_playwright
out=ROOT/'automation/runs/desktop-integer-smoke';out.mkdir(parents=True,exist_ok=True)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
log=(out/'electron.log').open('w',encoding='utf-8')
process=subprocess.Popen([str(ROOT/'desktop/node_modules/electron/dist/electron.exe'),str(ROOT/'desktop'),
    '--disable-gpu','--in-process-gpu',f'--remote-debugging-port={port}',f'--user-data-dir={out/"profile"}','--smoke-test'],
    stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    with sync_playwright() as pw:
        browser=None
        for _ in range(80):
            if process.poll() is not None:raise RuntimeError('Electron exited; inspect electron.log')
            try:
                browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}',timeout=1000);break
            except Exception:time.sleep(.25)
        if browser is None:raise RuntimeError('Electron did not start; inspect electron.log')
        page=browser.contexts[0].pages[0];errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.get_by_role('button',name='结构路线规划').click()
        page.get_by_role('heading',name='大数路线规划').wait_for()
        page.get_by_label('目标数',exact=True).fill('54')
        page.get_by_label('塔容量',exact=True).select_option('7')
        page.get_by_label('保存目录',exact=True).fill(str(out/'nonstandard'))
        page.get_by_role('button',name='开始规划',exact=True).click()
        page.get_by_text('该最高阶的最少调用数已在模型内证明',exact=True).wait_for(timeout=90000)
        status=page.evaluate('window.tallnum.integerPlannerStatus()')
        assert not status['busy'] and not status['error'],status
        result=status['result']
        assert result['target']==54 and result['countProven'] and result['peakProven'],result
        assert result['lowerBound']==result['upperBound']==1
        assert all(s.get('policyCells',5)>=5 for s in result['steps'])
        assert page.locator('.planner-steps li').count()==1
        page.get_by_role('button',name='查看全部步骤',exact=True).click()
        assert page.locator('.planner-steps li').count()>1
        assert page.evaluate('document.querySelector("main").clientWidth > 500')
        page.get_by_label('塔容量',exact=True).select_option('10')
        page.get_by_label('目标数',exact=True).fill('10240')
        page.get_by_role('button',name='开始规划',exact=True).click()
        page.get_by_role('button',name='停止计算',exact=True).click()
        page.get_by_text('已停止计算，已完成的搜索缓存保留',exact=True).wait_for(timeout=15000)
        stopped=page.evaluate('window.tallnum.integerPlannerStatus()')
        assert not stopped['busy'] and stopped['result'] is None,stopped
        assert not errors,errors
        (out/'result.json').write_text(json.dumps({'passed':True,'target':54,'lowerBound':1,'upperBound':1,'peakProven':True,'stopPassed':True,'errors':errors}),encoding='utf-8')
        print('Electron UI, preload IPC, Python planning, lower-bound proof and step filters: passed')
        browser.close()
finally:
    try:page.evaluate('window.tallnum.integerPlannerStop()')
    except Exception:pass
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    log.close()
