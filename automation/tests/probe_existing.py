"""Read-only CDP connection diagnosis; no browser/page mutation."""
import asyncio
import json
import websockets
import os
import re
import subprocess
import sys
from automation.browser import existing_endpoint

async def probe():
    async with websockets.connect(existing_endpoint()) as ws:
        async def call(i,method,params=None,session=None):
            message={'id':i,'method':method,'params':params or {}}
            if session: message['sessionId']=session
            await ws.send(json.dumps(message))
            print('sent',method,flush=True)
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),10))
                print({'id':r.get('id'),'method':r.get('method'),'error':r.get('error'),
                       'resultKeys':list(r.get('result',{}))},flush=True)
                if r.get('id')==i: return r['result']
        await call(1,'Browser.getVersion')
        targets=(await call(2,'Target.getTargets'))['targetInfos']
        games=[t for t in targets if t['type']=='page' and t['url'].split('?')[0].rstrip('/')=='https://pku2048.cn/tallnum']
        print('gamePages',len(games),flush=True)
        if len(games)==1:
            session=(await call(3,'Target.attachToTarget',{'targetId':games[0]['targetId'],'flatten':True}))['sessionId']
            value=await call(4,'Runtime.evaluate',{'expression':'({drops:document.querySelector("#tallnum-drops")?.textContent, focused:document.hasFocus()})','returnByValue':True},session)
            print(value,flush=True)

if __name__=='__main__':
    if '--playwright' in sys.argv:
        code='from playwright.sync_api import sync_playwright; from automation.browser import existing_endpoint; p=sync_playwright().start(); b=p.chromium.connect_over_cdp(existing_endpoint(),no_defaults=True,timeout=20000); print("CONNECTED",flush=True); p.stop()'
        child=subprocess.Popen([sys.executable,'-u','-c',code],env=dict(os.environ,DEBUG='pw:protocol'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        pending={}
        for line in child.stdout:
            method=re.search(r'"method":"([^"]+)"',line)
            ident=re.search(r'"id":(\d+)',line)
            if 'pw:protocol' in line:
                if ident and 'SEND' in line: pending[ident.group(1)]=method.group(1) if method else None
                elif ident and 'RECV' in line: pending.pop(ident.group(1),None)
            elif 'CONNECTED' in line: print('CONNECTED',flush=True)
        print('exit',child.wait(),'pending',pending,flush=True)
    else: asyncio.run(probe())
