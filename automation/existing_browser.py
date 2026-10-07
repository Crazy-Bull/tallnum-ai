"""Control only an existing game target; never initialize unrelated tabs."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error


class ExistingConnection:
    def __init__(self, endpoint):
        from websocket import create_connection
        self.socket=create_connection(endpoint,timeout=60,suppress_origin=True)
        self.sequence=0
        try:
            targets=self.call('Target.getTargets')['targetInfos']
            pages=[]
            for target in targets:
                url=urlsplit(target['url'])
                if target['type']=='page' and url.scheme=='https' and url.hostname=='pku2048.cn' and url.path.rstrip('/')=='/tallnum':
                    session=self.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True})['sessionId']
                    pages.append(ExistingPage(self,target,session))
            self.contexts=[ExistingContext(pages)]
        except Exception:
            self.close()
            raise

    def call(self, method, params=None, session=None):
        self.sequence+=1
        ident=self.sequence
        message={'id':ident,'method':method,'params':params or {}}
        if session: message['sessionId']=session
        try:
            self.socket.send(json.dumps(message))
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                response=json.loads(self.socket.recv())
                if response.get('id')!=ident: continue
                if 'error' in response: raise Error(f"{method}: {response['error'].get('message','CDP error')}")
                return response.get('result',{})
            raise Error(f'{method}: Chrome response timed out')
        except Error: raise
        except Exception as error: raise Error(f'{method}: {error}') from error

    def close(self):
        self.socket.close()


class ExistingContext:
    def __init__(self,pages):
        self.pages=pages
        for page in pages: page.context=self


class ExistingPage:
    def __init__(self,connection,target,session):
        self.connection=connection
        self.target_id=target['targetId']
        self.url=target['url']
        self.session=session
        self.keyboard=Keyboard(self)
        self.mouse=Mouse(self)

    def call(self,method,params=None):
        return self.connection.call(method,params,self.session)

    def evaluate(self, expression, *args):
        if args: source=f'({expression})({json.dumps(args[0],ensure_ascii=False)})'
        elif expression.strip().startswith(('()','async ()')): source=f'({expression})()'
        else: source=expression
        result=self.call('Runtime.evaluate',{'expression':source,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result:
            raise Error('Game-page evaluation failed: '+result['exceptionDetails'].get('text','unknown error'))
        return result['result'].get('value')

    def locator(self,selector): return Locator(self,f'document.querySelectorAll({json.dumps(selector)})')

    def get_by_role(self,role,name,exact=False):
        if role!='button' or not exact: raise ValueError('Only exact game button names are supported')
        return Locator(self,f'Array.from(document.querySelectorAll("button")).filter(e=>e.textContent.trim()==={json.dumps(name,ensure_ascii=False)} && e.getClientRects().length)')

    def wait_for_timeout(self,milliseconds): time.sleep(milliseconds/1000)

    def is_closed(self):
        try: return not any(t['targetId']==self.target_id for t in self.connection.call('Target.getTargets')['targetInfos'])
        except Error: return True

    def screenshot(self,path):
        data=self.call('Page.captureScreenshot',{'format':'png'})['data']
        Path(path).write_bytes(base64.b64decode(data))

    def bring_to_front(self): self.connection.call('Target.activateTarget',{'targetId':self.target_id})

    def set_focus_emulation(self,enabled):
        self.call('Emulation.setFocusEmulationEnabled',{'enabled':enabled})


class Locator:
    def __init__(self,page,elements): self.page,self.elements=page,elements
    def count(self): return self.page.evaluate(f'({self.elements}).length')
    def input_value(self): return self.page.evaluate(f'({self.elements})[0]?.value')
    def select_option(self,value):
        self.page.evaluate(f'(() => {{ const e=({self.elements})[0]; if(!e || !Array.from(e.options).some(o=>o.value==={json.dumps(value)})) throw Error("Missing game option"); e.value={json.dumps(value)}; e.dispatchEvent(new Event("input",{{bubbles:true}})); e.dispatchEvent(new Event("change",{{bubbles:true}})); }})()')
    def inner_text(self): return self.page.evaluate(f'({self.elements})[0]?.innerText')
    def evaluate_all(self,fn): return self.page.evaluate(f'({fn})(Array.from({self.elements}))')
    def bounding_box(self):
        return self.page.evaluate(f'(() => {{ const e=({self.elements})[0]; if(!e)return null; const r=e.getBoundingClientRect(); return {{x:r.x,y:r.y,width:r.width,height:r.height}}; }})()')
    def scroll_into_view_if_needed(self):
        self.page.evaluate(f'({self.elements})[0]?.scrollIntoView({{block:"nearest",behavior:"instant"}})')
    def click(self):
        # Header buttons can be covered by the site's fixed navigation when
        # nearest-edge scrolling places them at y=0. Center and hit-test them.
        self.page.evaluate(f'({self.elements})[0]?.scrollIntoView({{block:"center",behavior:"instant"}})')
        box=self.bounding_box()
        if not box or not box['width'] or not box['height']: raise Error('Game button is not visible')
        x,y=box['x']+box['width']/2,box['y']+box['height']/2
        hit=self.page.evaluate(f'([x,y]) => {{ const e=({self.elements})[0],hit=document.elementFromPoint(x,y);return Boolean(e && hit && (e===hit || e.contains(hit))); }}',[x,y])
        if not hit: raise Error('Game button is covered; no click was sent')
        self.page.mouse.move(x,y)
        self.page.mouse.down()
        self.page.mouse.up()


class Keyboard:
    def __init__(self,page): self.page=page
    def press(self,key):
        code={'Enter':13,'ArrowUp':38,'ArrowDown':40,'e':69}[key]
        text='e' if key=='e' else '\r' if key=='Enter' else ''
        args={'key':key,'code':{'Enter':'Enter','ArrowUp':'ArrowUp','ArrowDown':'ArrowDown','e':'KeyE'}[key],
              'windowsVirtualKeyCode':code,'nativeVirtualKeyCode':code}
        self.page.call('Input.dispatchKeyEvent',dict(args,type='keyDown',text=text))
        self.page.call('Input.dispatchKeyEvent',dict(args,type='keyUp'))


class Mouse:
    def __init__(self,page): self.page=page; self.x=0; self.y=0; self.pressed=False
    def move(self,x,y,steps=1):
        ox,oy=self.x,self.y
        for i in range(1,steps+1):
            self.x,self.y=ox+(x-ox)*i/steps,oy+(y-oy)*i/steps
            self.page.call('Input.dispatchMouseEvent',{'type':'mouseMoved','x':self.x,'y':self.y,'button':'left' if self.pressed else 'none','buttons':1 if self.pressed else 0})
    def down(self):
        self.page.call('Input.dispatchMouseEvent',{'type':'mousePressed','x':self.x,'y':self.y,'button':'left','buttons':1,'clickCount':1})
        self.pressed=True
    def up(self):
        self.page.call('Input.dispatchMouseEvent',{'type':'mouseReleased','x':self.x,'y':self.y,'button':'left','buttons':0,'clickCount':1})
        self.pressed=False
