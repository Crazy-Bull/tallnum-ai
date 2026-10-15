"""Opt-in visible Chrome regression for native resize, scroll and button focus."""
from pathlib import Path
from automation.browser import BrowserAdapter
from automation import game
from automation.common import atomic_json

directory=Path('automation/runs/browser-window-regression')
adapter=BrowserAdapter(directory,headless=False,fast_animations=True,isolated=True)
try:
    before=adapter.new_game()
    initial_group={'kind':'group','indices':[0,1]}
    initial_prediction=game.predict(before,initial_group)
    initial_after=adapter.perform(initial_group,before)
    assert game.signature(initial_after)==game.signature(initial_prediction)
    cdp=adapter.context.new_cdp_session(adapter.page)
    window=cdp.send('Browser.getWindowForTarget')['windowId']
    cdp.send('Browser.setWindowBounds',{'windowId':window,'bounds':{'windowState':'normal'}})
    before=adapter.new_game()
    sizes=[]
    for step in range(40):
        if before['gameOver']: before=adapter.new_game()
        width,height=((950,850) if step%2 else (1250,1050))
        cdp.send('Browser.setWindowBounds',{'windowId':window,'bounds':{'width':width,'height':height}})
        adapter.page.wait_for_timeout(150)
        size=adapter.page.evaluate('({width:innerWidth,height:innerHeight})')
        sizes.append(size)
        assert size['width']<=width and size['height']<height,size
        adapter.page.locator('#tallnum-new').focus()
        adapter.page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
        options=[{'kind':'drop'},{'kind':'up'},{'kind':'down'},{'kind':'edge'}]
        options.extend({'kind':'group','indices':[i,i+1]} for i in range(len(before['tower'])-1))
        for offset in range(len(options)):
            action=options[(step*7+offset)%len(options)]
            try: predicted=game.predict(before,action); break
            except ValueError: continue
        after=adapter.perform(action,before)
        assert game.signature(after)==game.signature(predicted),(before,action,after)
        assert after['actions']==predicted['actions'] and after['drops']==predicted['drops']
        before=after
        print(f'Checked resize/focus/scroll input {step+1}',flush=True)
    assert sizes[0]!=sizes[1]
    adapter.page.screenshot(path=str(directory/'success.png'))
    atomic_json(directory/'result.json',{'passed':True,'actionsChecked':40,'viewportSamples':sizes[:2]})
finally:
    adapter.close()
