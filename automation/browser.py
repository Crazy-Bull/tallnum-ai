from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import game
from .common import atomic_json, event
from .runtime import Executor, VirtualBoundaryExecutor, RouteFailure, IncompatibleState

SETTLEMENT_SECONDS = 10


# The page's state is a closure. Read its versioned IndexedDB document through
# the site's own read-only store module, and return only public observations.
READ_STATE = '''async () => {
 const {readLocalDocument} = await import('/game/save-store.js');
 const limit = document.querySelector('#tallnum-limit').value;
 const saved = await readLocalDocument('tallnum:standard:' + limit);
 if (!saved?.value) return null;
 const s = saved.value;
 return {tower:s.tower,queue:s.queue.slice(0,2),numberSet:s.numberSet,
   towerLimit:s.towerLimit,poolVersion:s.poolVersion,actions:s.actions,
   drops:s.drops,gameOver:s.gameOver,revision:saved.revision};
}'''


class InputInterrupted(IncompatibleState):
    """An input may be lost during focus/geometry changes; reconcile first."""


class GestureNotReady(InputInterrupted):
    """A cancelled drag that did not submit a game action."""


class ObservationPending(InputInterrupted):
    """Animation/save/input acknowledgement is delayed; preserve and reconcile."""


def reconcile(before, after):
    if after['actions'] == before['actions'] + 1:
        return 'accepted'
    if {k:v for k,v in before.items() if k!='revision'} == {k:v for k,v in after.items() if k!='revision'}:
        return 'unchanged'
    raise InputInterrupted('盘面已变化，无法安全重发操作；请停止后重新开始')


class BrowserAdapter:
    def __init__(self, directory, headless=False, fast_animations=False, fixture_seed=None, browser='chrome', cdp_endpoint=None, isolated=False, tower_limit=7):
        self.pw = None
        self.directory = Path(directory)
        self.fast_animations=fast_animations
        self.fixture_seed=fixture_seed
        self.directory.mkdir(parents=True, exist_ok=True)
        if browser not in ('chrome','msedge'):
            raise ValueError('Supported browsers: chrome, msedge')
        self.attached = cdp_endpoint is not None or not (headless or isolated)
        if self.attached:
            try:
                if fast_animations or fixture_seed is not None:
                    raise ValueError('Existing tabs cannot use animation or RNG fixtures')
                endpoint = cdp_endpoint or existing_endpoint(browser)
                from .existing_browser import ExistingConnection
                self.connection = ExistingConnection(endpoint)
                self.page = select_existing_page(self.connection.contexts)
                self.context = self.page.context
                if (self.page.locator('#tallnum-set').input_value() == 'standard'
                        and self.page.locator('#tallnum-limit').input_value() != str(tower_limit)
                        and self.page.locator('#tallnum-drops').inner_text() == '0'
                        and self.page.locator('#tallnum-tower > [data-tallnum-index]').evaluate_all(
                            'els => els.sort((a,b)=>Number(a.dataset.tallnumIndex)-Number(b.dataset.tallnumIndex)).map(e => Number(e.querySelector("strong").textContent))') == [2,4]):
                    # Only change an untouched fresh game's limit in this tab.
                    self.page.locator('#tallnum-limit').select_option(str(tower_limit))
                if (self.page.locator('#tallnum-set').input_value() != 'standard'
                        or self.page.locator('#tallnum-limit').input_value() != str(tower_limit)):
                    raise IncompatibleState(f'当前游戏页须为标准数字集、{tower_limit} 格；请在该标签页中选择后重新连接')
                # Keep this target active for animation scheduling without
                # activating its tab or moving the user's window focus.
                self.page.set_focus_emulation(True)
                event('browser-attached',url=self.page.url)
                return
            except Exception:
                if hasattr(self,'connection'): self.connection.close()
                raise
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        profile='browser-profile' if browser=='msedge' else 'browser-profile-chrome'
        self.context = self.pw.chromium.launch_persistent_context(
            str(self.directory/profile), channel=browser, headless=headless,
            **({'viewport':{'width':1280,'height':1000}} if headless else
               {'no_viewport':True,'args':['--start-maximized']}))
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto('https://pku2048.cn/tallnum', wait_until='networkidle')
        self.page.locator('#tallnum-set').select_option('standard')
        self.page.locator('#tallnum-limit').select_option(str(tower_limit))
        self.page.locator('#tallnum-stage:not(.input-locked)').wait_for()
        if fast_animations or fixture_seed is not None:
            self.page.clock.install()

    def read(self):
        deadline = time.monotonic()+20
        last = None
        while time.monotonic()<deadline:
            if self.page.locator('#tallnum-stage.input-locked').count():
                self.page.wait_for_timeout(100)
                continue
            if self.page.locator('#tallnum-save-state').inner_text() == '存档失败':
                raise IncompatibleState('Browser save failed')
            obs = self.page.evaluate(READ_STATE)
            drops = self.page.locator('#tallnum-drops').inner_text().replace(',','')
            visible = self.page.locator('#tallnum-tower > [data-tallnum-index]').evaluate_all(
                "els => els.map(e => ({index:Number(e.dataset.tallnumIndex), value:Number(e.querySelector('strong').textContent)})).sort((a,b)=>a.index-b.index).map(e=>e.value)")
            valid = obs and str(obs['drops'])==drops and visible==[t['value'] for t in obs['tower']]
            # A save revision is bookkeeping, not a game action. Compare
            # the actual state so an unrelated save cannot prevent settling.
            settled = {k:v for k,v in obs.items() if k!='revision'} if valid else None
            if valid and settled==last:
                return obs
            last = settled
            self.page.wait_for_timeout(10 if self.fast_animations else 100)
        raise ObservationPending('Animation or persisted observation is still pending')

    def new_game(self, finished=False):
        if self.fixture_seed is not None:
            # Deterministic integration fixtures only. Production play never
            # supplies this value and never reads or modifies the game's RNG.
            self.page.clock.set_fixed_time(datetime.fromtimestamp(self.fixture_seed/1000,tz=timezone.utc))
        if finished:
            self.page.get_by_role('button',name='再来一局',exact=True).click()
        else:
            self.page.locator('#tallnum-new').click()
        self.page.wait_for_timeout(100)
        obs = self.read()
        if obs['actions'] or obs['drops'] or [t['value'] for t in obs['tower']]!=[2,4]:
            raise IncompatibleState('New game was not acknowledged')
        return obs

    def restart_game(self):
        return self.new_game(finished=True)

    def perform(self, action, before):
        kind=action['kind']
        if kind in ('drop','up','down','edge'):
            # A focused preview/button can consume Enter and arrow keys too.
            # Blur only DOM focus; never alter the game's state.
            self.page.evaluate('() => document.activeElement?.blur()')
            self.page.keyboard.press({'drop':'Enter','up':'ArrowUp','down':'ArrowDown','edge':'e'}[kind])
        else:
            for attempt in range(6):
                try:
                    self._drag_group(action['indices'])
                    break
                except GestureNotReady:
                    observed=self.read()
                    if reconcile(before,observed)=='accepted':
                        return observed
                    if attempt == 5:
                        raise
                    self.page.wait_for_timeout(150*(attempt+1))
        # Do not resend on timeout: reread once and reconcile the action count.
        if self.fast_animations:
            self.page.clock.fast_forward(15000)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            after=self.read()
            if after['actions']==before['actions']+1:
                return after
            if after['actions']!=before['actions']:
                raise InputInterrupted('Unexpected action count')
            self.page.wait_for_timeout(100)
        raise ObservationPending('网页尚未确认操作，等待稳定盘面后自动核对')

    def _drag_group(self,indices):
        boxes=[self.page.locator(f'#tallnum-tower > [data-tallnum-index="{i}"]').bounding_box() for i in indices]
        if not all(boxes):
            raise InputInterrupted('Missing group elements')
        # Keep the viewport still when the range is already visible.
        # Otherwise scroll only enough to fit the range with a small margin.
        height=self.page.evaluate('window.innerHeight')
        delta=group_scroll_delta(boxes,height)
        if delta:
            self.page.evaluate('(delta) => window.scrollBy({top:delta,behavior:"instant"})',delta)
            self.page.wait_for_timeout(100)
            boxes=[self.page.locator(f'#tallnum-tower > [data-tallnum-index="{i}"]').bounding_box() for i in indices]
        if not all(boxes):
            raise InputInterrupted('Missing group elements after scrolling')
        height=self.page.evaluate('window.innerHeight')
        if any(b['y']<0 or b['y']+b['height']>height for b in boxes):
            raise InputInterrupted('窗口高度不足以显示合成范围；请放大窗口后继续')
        x=boxes[0]['x']+boxes[0]['width']/2
        start_y=boxes[0]['y']+boxes[0]['height']/2
        self.page.mouse.move(x,start_y)
        # Hover/scroll layout can move the tile after the initial measurement.
        # Refresh before pressing, while no game input has been submitted.
        self.page.wait_for_timeout(50)
        first=self.page.locator(f'#tallnum-tower > [data-tallnum-index="{indices[0]}"]').bounding_box()
        if first is None:
            raise GestureNotReady('合并起点暂时不可见，已保留操作')
        x=first['x']+first['width']/2
        start_y=first['y']+first['height']/2
        self.page.mouse.move(x,start_y)
        hit=self.page.evaluate("([x,y]) => Number(document.elementFromPoint(x,y)?.closest('[data-tallnum-index]')?.dataset.tallnumIndex ?? -1)",[x,start_y])
        if hit!=indices[0]:
            raise GestureNotReady('合并起点未命中预期方块，已保留操作')
        self.page.mouse.down()
        submitted=False
        try:
            self.page.wait_for_timeout(50)
            for index in indices[1:]:
                box=self.page.locator(f'#tallnum-tower > [data-tallnum-index="{index}"]').bounding_box()
                if box is None:
                    raise GestureNotReady('拖动期间方块位置变化，已取消合并')
                self.page.mouse.move(x,box['y']+box['height']/2,steps=8)
                self.page.wait_for_timeout(50)
            last=self.page.locator(f'#tallnum-tower > [data-tallnum-index="{indices[-1]}"]').bounding_box()
            if last is None:
                raise GestureNotReady('拖动期间方块位置变化，已取消合并')
            self.page.mouse.move(x-100,last['y']+last['height']/2,steps=8)
            self.page.wait_for_timeout(50)
            selected=self.page.locator('#tallnum-tower > .gesture-selected[data-tallnum-index]').evaluate_all(
                'els => els.map(e=>Number(e.dataset.tallnumIndex)).sort((a,b)=>a-b)')
            if selected!=indices or not self.page.locator('#tallnum-stage.group-ready').count():
                raise GestureNotReady('合并选区未就绪，已取消拖动并保留操作')
            submitted=True
        finally:
            if not submitted:
                # Returning to the press point cancels both group and
                # rotation gestures before release; it cannot commit them.
                self.page.mouse.move(x,start_y)
            self.page.mouse.up()

    def close(self):
        # Closing an attached context/browser would close the user's tabs.
        if not self.attached:
            self.context.close()
        else:
            try:
                self.page.set_focus_emulation(False)
            finally:
                self.connection.close()
        if self.pw is not None:
            self.pw.stop()


def group_scroll_delta(boxes,height):
    top=min(b['y'] for b in boxes)
    bottom=max(b['y']+b['height'] for b in boxes)
    if bottom-top>height:
        raise InputInterrupted('窗口高度不足以显示合成范围；请放大窗口后继续')
    if top>=0 and bottom<=height:
        return 0
    margin=min(24,max(0,(height-(bottom-top))/2))
    return top-margin if top<0 else bottom-height+margin


def existing_endpoint(browser='chrome'):
    vendor = ('Google','Chrome') if browser == 'chrome' else ('Microsoft','Edge')
    path = Path(os.environ.get('LOCALAPPDATA','')) / vendor[0] / vendor[1] / 'User Data' / 'DevToolsActivePort'
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
        port = int(lines[0])
        ws_path = lines[1].strip()
        if not 1 <= port <= 65535 or not ws_path.startswith('/devtools/browser/'):
            raise ValueError('Invalid debugging endpoint')
        return f'ws://127.0.0.1:{port}{ws_path}'
    except (OSError, ValueError, IndexError) as error:
        raise IncompatibleState('无法连接现有 Chrome：请在 chrome://inspect/#remote-debugging 启用远程调试，连接时允许 Chrome 提示。不会另开游戏标签页。') from error


def select_existing_page(contexts):
    matches = []
    for context in contexts:
        for page in context.pages:
            url = urlsplit(page.url)
            if url.scheme == 'https' and url.hostname == 'pku2048.cn' and url.path.rstrip('/') == '/tallnum':
                matches.append(page)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        focused = [p for p in matches if p.evaluate('() => document.hasFocus()')]
        if len(focused) == 1:
            return focused[0]
        raise IncompatibleState('存在多个游戏标签页，请将要游玩的标签页置于前台后重新连接')
    raise IncompatibleState('现有 Chrome 中没有 https://pku2048.cn/tallnum 游戏标签页；请打开游戏后重新连接')


def play(route,catalog,directory,control,headless=False,browser='chrome',finish_current_game=False,cdp_endpoint=None,resume_current_game=False,restart_settled_game=False):
    from .controller_lock import controller_lease
    with controller_lease(browser):
        return _play(route,catalog,directory,control,headless,browser,finish_current_game,cdp_endpoint,resume_current_game,restart_settled_game)


def _play(route,catalog,directory,control,headless=False,browser='chrome',finish_current_game=False,cdp_endpoint=None,resume_current_game=False,restart_settled_game=False):
    directory=Path(directory)
    adapter=BrowserAdapter(directory,headless,fast_animations=headless,browser=browser,cdp_endpoint=cdp_endpoint,
                           tower_limit=route.get('cells',route.get('towerLimit',7)))
    def make_executor():
        if route.get('version')==2:
            from .execution import create_executor
            return create_executor(route,catalog)
        return Executor(route,catalog)
    def make_continuation(obs):
        if route.get('version')==2:
            from .execution import continuation_executor
            return continuation_executor(route,catalog,obs)
        return VirtualBoundaryExecutor(route,catalog,obs)
    executor=make_executor()
    total_drops=0
    attempts=1
    before=None
    log=(directory/'actions.jsonl').open('a',encoding='utf-8')
    last_token=None
    pending=None
    awaiting_restart=False
    restart_at=None
    round_record=None
    record_written=False
    round_success=False
    drops_to_target=None
    continuing=False
    round_id=uuid.uuid4().hex
    started_at=datetime.now(timezone.utc).isoformat()
    partial_start=finish_current_game
    try:
        from playwright.sync_api import Error as BrowserError
        before=adapter.read() if finish_current_game or getattr(adapter,'attached',False) else adapter.new_game()
        if restart_settled_game:
            if not before['gameOver']:raise IncompatibleState('Settlement handoff expected game-over board; board retained')
            before=adapter.restart_game()
            finish_current_game=False
            partial_start=False
        if resume_current_game and (before['actions'] or before['drops']):
            from .resume import restore_executor
            executor.close()
            executor=restore_executor(route,catalog,directory/'actions.jsonl',before)
            restored=getattr(executor,'restored_round',{})
            continuing=getattr(executor,'is_virtual',False) or restored.get('executionPhase')=='virtual'
            round_success=restored.get('roundSuccess',False)
            drops_to_target=restored.get('dropsToTarget')
            round_id=restored.get('roundId') or round_id
            total_drops=before['drops']
            partial_start=True
            event('resumed-current-game',stage=executor.stage,drops=before['drops'])
        elif getattr(adapter,'attached',False) and (before['actions'] or before['drops'] or before['gameOver']):
            finish_current_game=True
            partial_start=True
        if finish_current_game:
            total_drops=before['drops']
            has_target=any(t['kind']=='tile' and t['value']==route['target'] for t in before['tower'])
            target_at_bottom=bool(before['tower'] and before['tower'][0]['kind']=='tile'
                                 and before['tower'][0]['value']==route['target'])
            if not before['gameOver'] and (has_target if route.get('version')==2 else target_at_bottom):
                executor.close()
                executor=make_continuation(before)
                continuing=True
            else:
                executor.failure_reason='finish-current-game'
            event('finishing-current-game',totalDrops=total_drops)
        while True:
            config=json.loads(Path(control).read_text(encoding='utf-8')) if Path(control).exists() else {'mode':'paused'}
            mode=config.get('mode','paused')
            if mode=='stop':
                return
            token=config.get('token')
            if mode=='paused' or mode=='step' and token==last_token:
                time.sleep(.1)
                continue
            if mode not in ('run','step'):
                raise ValueError('Invalid controller mode')
            last_token=token
            action_stage=None
            try:
                observed=adapter.read()
                if not round_success and any(isinstance(t,dict) and t['kind']=='tile'
                                             and t['value']==route['target'] for t in observed['tower']):
                    round_success=True
                    drops_to_target=observed['drops']
                    event('target-reached',target=route['target'],attempts=attempts,drops=drops_to_target)
                if round_success and config.get('stopAfterTarget'):
                    atomic_json(directory/'checkpoint.json',{'routeVersion':route.get('version',1),
                        'routeId':route.get('id'),'phase':'target-reached','roundId':round_id,
                        'roundSuccess':True,'dropsToTarget':drops_to_target,
                        'observation':observed,'pendingAction':None})
                    atomic_json(control,{'mode':'stop','stopAfterTarget':True})
                    event('stopped-at-target',target=route['target'],attempts=attempts,totalDrops=total_drops)
                    return
                if awaiting_restart:
                    if time.monotonic()<restart_at:
                        time.sleep(.1)
                        continue
                    if not record_written:
                        with (directory/'rounds.jsonl').open('a',encoding='utf-8') as journal:
                            journal.write(json.dumps(round_record,ensure_ascii=False)+'\n')
                            journal.flush()
                            os.fsync(journal.fileno())
                        record_written=True
                        event('round-recorded',path=str(directory/'rounds.jsonl'),success=round_success,
                              drops=round_record['drops'])
                    if config.get('stopAfterRound'):
                        event('stopped-after-settlement',roundId=round_id,target=route['target'])
                        return
                    before=adapter.restart_game()
                    if continuing:
                        executor.close()
                        executor=make_executor()
                    else:
                        executor.reset()
                    pending=None
                    awaiting_restart=False
                    continuing=False
                    round_success=False
                    drops_to_target=None
                    round_record=None
                    record_written=False
                    round_id=uuid.uuid4().hex
                    started_at=datetime.now(timezone.utc).isoformat()
                    partial_start=False
                    attempts+=1
                    event('restart',attempts=attempts,totalDrops=total_drops)
                    continue
                if pending is not None:
                    before,action=pending
                    action_stage=executor.stage
                    after=observed if reconcile(before,observed)=='accepted' else adapter.perform(action,before)
                else:
                    before=observed
                    action=executor.next_action(before)
                    if action is None:
                        round_success=True
                        if drops_to_target is None:
                            drops_to_target=before['drops']
                        executor.close()
                        executor=make_continuation(before)
                        continuing=True
                        event('virtual-continuation',actualBottom=before['tower'][0],
                              virtualBottom=route['target']//2,target=route['target'])
                        action=executor.next_action(before)
                    if action is not None:
                        action_stage=executor.stage
                        pending=(before,action)
                        atomic_json(directory/'checkpoint.json',{'routeVersion':route.get('version',1),
                                    'routeId':route.get('id'),'phase':'virtual' if continuing else 'ordinary',
                                    'roundId':round_id,'roundSuccess':round_success,'dropsToTarget':drops_to_target,
                                    'observation':before,'pendingAction':action})
                        after=adapter.perform(action,before)
            except RouteFailure as error:
                if not before['gameOver']:
                    raise IncompatibleState('Failure reported before the real game ended') from error
                round_record={'roundId':round_id,'attempt':attempts,'target':route['target'],
                              'success':round_success,'drops':before['drops'],'dropsToTarget':drops_to_target,
                              'actions':before['actions'],'reason':str(error),'partialStart':partial_start,
                              'startedAt':started_at,'endedAt':datetime.now(timezone.utc).isoformat(),
                              'settlementSeconds':SETTLEMENT_SECONDS,'finalTower':before['tower']}
                log.write(json.dumps({'event':'round-ended',**round_record},ensure_ascii=False)+'\n');log.flush()
                atomic_json(directory/'game-over.json',{'record':round_record,'observation':before,
                            'totalDrops':total_drops})
                atomic_json(directory/'checkpoint.json',{'routeVersion':route.get('version',1),
                            'routeId':route.get('id'),'phase':'settlement','round':round_record,
                            'observation':before,'pendingAction':None})
                awaiting_restart=True
                restart_at=time.monotonic()+SETTLEMENT_SECONDS
                event('round-ended',success=round_success,drops=before['drops'],attempts=attempts,
                      settlementSeconds=SETTLEMENT_SECONDS)
                continue
            except ObservationPending as error:
                # A tab switch can delay timers after the input was accepted.
                # Keep pending intact: the next stable read reconciles it
                # before considering any resend, then validates the board.
                event('waiting-for-page',message=str(error),pendingAction=pending[1] if pending else None)
                time.sleep(.25)
                continue
            except (IncompatibleState,BrowserError) as error:
                if adapter.page.is_closed():
                    return
                atomic_json(control,{'mode':'paused','token':time.time_ns()})
                atomic_json(directory/'incident.json',{'status':'paused','error':str(error),
                            'observation':before,'pendingAction':pending[1] if pending else None,
                            'attempts':attempts,'totalDrops':total_drops,'routeId':route.get('id'),
                            'executionPhase':'virtual' if continuing else 'ordinary'})
                event('paused',message=str(error),attempts=attempts,totalDrops=total_drops)
                continue
            try:
                executor.accept(before,action,after)
            except IncompatibleState as error:
                atomic_json(control,{'mode':'paused','token':time.time_ns()})
                event('paused',message=str(error),attempts=attempts,totalDrops=total_drops)
                # Keep the pending pair so a mismatching manual move can never
                # cause a second input on resume.
                continue
            total_drops+=after['drops']-before['drops']
            log.write(json.dumps({'before':before,'action':action,'after':after,'attempt':attempts,'totalDrops':total_drops,
                                 'routeVersion':route.get('version',1),'routeId':route.get('id'),
                                 'executionPhase':'virtual' if continuing else 'ordinary',
                                 'roundId':round_id,'roundSuccess':round_success,'dropsToTarget':drops_to_target,
                                 'openingBoundaryVersion':2,'stageBefore':action_stage},ensure_ascii=False)+'\n');log.flush()
            pending=None
            atomic_json(directory/'checkpoint.json',{'routeVersion':route.get('version',1),
                        'routeId':route.get('id'),'phase':'virtual' if continuing else 'ordinary',
                        'roundId':round_id,'roundSuccess':round_success,'dropsToTarget':drops_to_target,
                        'observation':after,'pendingAction':None})
            event('action',stage=executor.stage,attempts=attempts,totalDrops=total_drops,action=action,
                  finishingFailure=getattr(executor,'failure_reason',None))
    except Exception as error:
        atomic_json(directory/'incident.json',{'error':str(error),'observation':before,'attempts':attempts,'totalDrops':total_drops})
        adapter.page.screenshot(path=str(directory/'incident.png'))
        raise
    finally:
        executor.close()
        adapter.close()
        log.close()
