"""Hidden Electron UI -> IPC -> probability-route search -> certified result."""
import re
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'automation/.deps'))
from playwright.sync_api import sync_playwright

out=ROOT/'automation/runs/desktop-peak13-smoke'
out.mkdir(parents=True,exist_ok=True)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
log=(out/'electron.log').open('w',encoding='utf-8')
packaged=os.environ.get('PEAK13_PACKAGED')=='1'
launch=[str(ROOT/'desktop/release/win-unpacked/Tallnum 计算器.exe')] if packaged else [str(ROOT/'desktop/node_modules/electron/dist/electron.exe'),str(ROOT/'desktop')]
process=subprocess.Popen([*launch,
    '--disable-gpu','--in-process-gpu',f'--remote-debugging-port={port}',
    f'--user-data-dir={out/"profile"}','--smoke-test'],
    stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    with sync_playwright() as pw:
        browser=None
        for _ in range(80):
            if process.poll() is not None:raise RuntimeError('Electron exited; inspect electron.log')
            try:
                browser=pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}',timeout=1000)
                break
            except Exception:time.sleep(.25)
        if browser is None:raise RuntimeError('Electron did not start; inspect electron.log')
        page=browser.contexts[0].pages[0]
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.get_by_role('button',name='概率表路线规划').click()
        page.get_by_role('heading',name='概率表路线规划').wait_for()
        page.get_by_role('button',name='生成路线').click()
        page.get_by_text('路线已生成；与 100 局概率表实测版本一致').wait_for(timeout=90000)
        status=page.evaluate('window.tallnum.peak13Status()')
        assert not status['busy'] and not status['error'],status
        assert status['report']['five64Calls']==13
        assert len(status['report']['rescueFive64Policies'])==1
        assert status['validation']['successes']==89
        assert status['validation']['maximumSuccessfulFive64Calls']==14
        assert status['validation']['originalEngineVerified']
        assert page.get_by_text('89 / 100').count()==1
        assert page.locator('.planner-steps li').count()==13
        page.get_by_role('button',name='全部步骤').click()
        assert page.locator('.planner-steps li').count()>13
        page.get_by_label('概率路线塔容量').fill('6')
        page.get_by_label('概率路线目标').fill('80')
        page.get_by_role('button',name='生成路线').click()
        page.get_by_text('已生成概率表定式候选路线；尚未进行整局随机验证').wait_for(timeout=90000)
        generic=page.evaluate('window.tallnum.peak13Status()')
        assert generic['route']['target']==80 and generic['route']['cells']==6
        assert generic['report']['leafCounts']=={'5:40:single':2}
        assert generic['validation'] is None
        page.get_by_role('button',name='自选定式').click()
        for box in page.locator('.template-options input[type=checkbox]').all():box.uncheck()
        page.locator('.template-options label').filter(has_text='5:40:single').get_by_role('checkbox').check()
        page.get_by_role('button',name='生成路线').click()
        page.get_by_text('已生成概率表定式候选路线；尚未进行整局随机验证').wait_for(timeout=90000)
        selected=page.evaluate('window.tallnum.peak13Status()')
        assert selected['report']['scope']['allowedFiveCellTemplates']==['5:40:single']
        assert selected['report']['leafCounts']=={'5:40:single':2}
        page.locator('.template-options label').filter(has_text='5:40:single').get_by_role('checkbox').uncheck()
        page.locator('.template-options label').filter(has_text='6:40:single').get_by_role('checkbox').check()
        page.get_by_label('概率路线目标').fill('40')
        page.get_by_role('button',name='生成路线').click()
        page.get_by_text('已生成概率表定式候选路线；尚未进行整局随机验证').wait_for(timeout=90000)
        six=page.evaluate('window.tallnum.peak13Status()')
        assert six['report']['leafCounts']=={'6:40:single':1}
        assert six['route']['steps'][0]['policyCells']==6
        page.locator('.template-options label').filter(has_text='6:40:single').get_by_role('checkbox').uncheck()
        page.get_by_label('添加定式').fill('7:96:single')
        page.get_by_role('button',name='添加定式').click()
        page.get_by_label('概率路线塔容量').fill('7')
        page.get_by_label('概率路线目标').fill('96')
        page.get_by_role('button',name='生成路线').click()
        page.get_by_role('heading',name='结构路线（待补概率表）').wait_for(timeout=90000)
        seven=page.evaluate('window.tallnum.peak13Status()')
        assert seven['report']['missingProbabilityTables']==['7:96:single']
        assert seven['route']['steps'][0]['policyCells']==7
        page.get_by_label('添加定式').fill('5:80:single')
        page.get_by_role('button',name='添加定式').click()
        page.get_by_label('概率路线塔容量').fill('5')
        page.get_by_label('概率路线目标').fill('80')
        page.get_by_role('button',name='生成路线').click()
        page.get_by_role('heading',name='结构路线（待补概率表）').wait_for(timeout=90000)
        high_five=page.evaluate('window.tallnum.peak13Status()')
        assert high_five['report']['missingProbabilityTables']==['5:80:single']
        assert high_five['route']['steps'][0]['template']=='5:80:single'
        page.get_by_role('button',name='默认：全部已有定式').click()
        page.get_by_label('概率路线塔容量').fill('10')
        page.get_by_label('概率路线目标').fill('12360')
        page.get_by_role('button',name='生成路线').click()
        page.get_by_text('在允许的最高五格 64 定式下，10 格普通单块上界为 10368；目标至少需要五格定式上限 77').first.wait_for(timeout=90000)
        bound=page.evaluate('window.tallnum.peak13Status()')
        assert bound['route'] is None and bound['report']['status']=='requires-higher-template-ceiling'
        assert not errors,errors
        print('Electron generic probability planner and certified 10240 route: passed')
        browser.close()
finally:
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    log.close()
