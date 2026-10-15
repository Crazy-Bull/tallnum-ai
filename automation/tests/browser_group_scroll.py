"""100 real CDP inputs in a private headless Chrome fixture."""
from pathlib import Path
from playwright.sync_api import sync_playwright
from automation.browser import BrowserAdapter,group_scroll_delta
from automation.common import atomic_json
from automation import game
from automation.existing_browser import ExistingConnection

directory=Path('automation/runs/browser-group-scroll')
directory.mkdir(parents=True,exist_ok=True)
owner=sync_playwright().start()
context=owner.chromium.launch_persistent_context(str(directory/'fixture-profile'),channel='chrome',headless=True,
        viewport={'width':1280,'height':1000},args=['--remote-debugging-port=0','--enable-automation'])
page=context.pages[0]
page.on('dialog', lambda dialog: dialog.accept())
page.goto('https://pku2048.cn/tallnum',wait_until='networkidle')
page.locator('#tallnum-set').select_option('standard')
page.locator('#tallnum-limit').select_option('7')
port,path=(directory/'fixture-profile/DevToolsActivePort').read_text().splitlines()[:2]
endpoint=f'ws://127.0.0.1:{port}{path}'
# Verify this endpoint belongs to the exact headless fixture profile before
# allowing any reset/input. It can never fall back to the user's Chrome port.
verified=ExistingConnection(endpoint)
try:
    arguments=verified.call('Browser.getBrowserCommandLine')['arguments']
    expected='--user-data-dir='+str((directory/'fixture-profile').resolve())
    assert expected in arguments, 'Endpoint is not the owned fixture profile'
    assert any(a.startswith('--headless') for a in arguments), 'Endpoint is not headless'
    assert '--remote-debugging-port=0' in arguments, 'Endpoint is not the fixture debug listener'
    print({'fixtureIsolationVerified':True,'headless':True},flush=True)
finally:
    verified.close()
# Initialize the owned fixture through Playwright, which services its own
# confirmation dialog. The tested CDP path handles all gameplay and settlement
# restarts below; those buttons do not open confirmation dialogs.
page.locator('#tallnum-new').click()
adapter=BrowserAdapter(directory,cdp_endpoint=endpoint)
page.clock.install()
adapter.fast_animations=True
adapter.page.clock=page.clock
groups=0
visible_groups=0
scrolls=[]
evaluate=adapter.page.evaluate
def observe_evaluate(expression,*args):
    if 'window.scrollBy' in expression: scrolls.append(args[0])
    return evaluate(expression,*args)
adapter.page.evaluate=observe_evaluate
try:
    before=adapter.read()
    assert before['actions']==0 and before['drops']==0
    for step in range(100):
        if before['gameOver']: before=adapter.restart_game()
        if step%10==0:
            page.set_viewport_size({'width':1100,'height':850} if step%20 else {'width':1280,'height':1000})
        options=[{'kind':'drop'},{'kind':'up'},{'kind':'down'},{'kind':'edge'}]
        options.extend({'kind':'group','indices':[i,i+1]} for i in range(len(before['tower'])-1))
        for offset in range(len(options)):
            action=options[(step*7+offset)%len(options)]
            try: predicted=game.predict(before,action); break
            except ValueError: continue
        count=len(scrolls)
        if action['kind']=='group':
            boxes=[adapter.page.locator(f'#tallnum-tower > [data-tallnum-index="{i}"]').bounding_box() for i in action['indices']]
            height=adapter.page.evaluate('window.innerHeight')
            visible=group_scroll_delta(boxes,height)==0
            groups+=1
            visible_groups+=int(visible)
        after=adapter.perform(action,before)
        if action['kind']=='group' and visible: assert len(scrolls)==count,'Visible selection was unnecessarily scrolled'
        assert game.signature(after)==game.signature(predicted),(before,action,after)
        assert after['actions']==predicted['actions'] and after['drops']==predicted['drops']
        before=after
    result={'passed':True,'actionsChecked':100,'groups':groups,'visibleGroupsWithoutScroll':visible_groups,'requiredScrolls':scrolls}
    atomic_json(directory/'result.json',result)
    print(result,flush=True)
except Exception:
    page.screenshot(path=str(directory/'incident.png'))
    print(adapter.read(),flush=True)
    raise
finally:
    adapter.close()
    context.close()
    owner.stop()
