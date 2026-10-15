import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.browser import BrowserAdapter, existing_endpoint, select_existing_page
from automation.runtime import IncompatibleState
from automation.existing_browser import ExistingConnection, ExistingPage, Keyboard, Mouse


class ExistingTabTests(unittest.TestCase):
    def test_focus_emulation_stays_on_game_session_without_activating_tab(self):
        connection=MagicMock()
        page=ExistingPage(connection,{'targetId':'game','url':'https://pku2048.cn/tallnum'},'game-session')
        page.set_focus_emulation(True)
        page.set_focus_emulation(False)
        self.assertEqual(connection.call.call_args_list, [
            unittest.mock.call('Emulation.setFocusEmulationEnabled',{'enabled':True},'game-session'),
            unittest.mock.call('Emulation.setFocusEmulationEnabled',{'enabled':False},'game-session')])

    def test_connection_attaches_only_game_targets(self):
        socket=MagicMock()
        targets=[{'targetId':'game','type':'page','url':'https://pku2048.cn/tallnum'},
                 {'targetId':'other','type':'page','url':'https://example.com'},
                 {'targetId':'worker','type':'service_worker','url':'https://pku2048.cn/tallnum'}]
        import json
        socket.recv.side_effect=[json.dumps({'id':1,'result':{'targetInfos':targets}}),
                                 json.dumps({'id':2,'result':{'sessionId':'session'}})]
        with patch('websocket.create_connection',return_value=socket):
            connection=ExistingConnection('ws://localhost/test')
            calls=[json.loads(x.args[0]) for x in socket.send.call_args_list]
            self.assertEqual([x['method'] for x in calls],['Target.getTargets','Target.attachToTarget'])
            self.assertEqual(calls[1]['params'],{'targetId':'game','flatten':True})
            connection.close()
            socket.close.assert_called_once()

    def test_keyboard_and_drag_use_real_input_events(self):
        page=MagicMock()
        Keyboard(page).press('Enter')
        self.assertEqual([c.args[1]['type'] for c in page.call.call_args_list],['keyDown','keyUp'])
        page.reset_mock()
        mouse=Mouse(page)
        mouse.move(100,200); mouse.down(); mouse.move(100,300,steps=2); mouse.up()
        events=[c.args[1] for c in page.call.call_args_list]
        self.assertEqual([e['type'] for e in events],['mouseMoved','mousePressed','mouseMoved','mouseMoved','mouseReleased'])
        self.assertEqual(events[2]['buttons'],1)
        self.assertEqual(events[-1]['buttons'],0)

    def page(self, url='https://pku2048.cn/tallnum', focused=False):
        page=MagicMock()
        page.url=url
        page.evaluate.return_value=focused
        locators={key:MagicMock() for key in ['#tallnum-set','#tallnum-limit']}
        locators['#tallnum-set'].input_value.return_value='standard'
        locators['#tallnum-limit'].input_value.return_value='7'
        page.locator.side_effect=lambda key:locators.setdefault(key,MagicMock())
        return page

    def test_connection_preserves_tab_and_detaches_without_closing_it(self):
        page=self.page()
        context=MagicMock(pages=[page])
        page.context=context
        pw=MagicMock()
        connection=MagicMock(contexts=[context])
        with tempfile.TemporaryDirectory() as tmp, patch('playwright.sync_api.sync_playwright') as start, patch('automation.browser.event'), patch('automation.existing_browser.ExistingConnection',return_value=connection):
            start.return_value.start.return_value=pw
            adapter=BrowserAdapter(tmp,cdp_endpoint='ws://127.0.0.1:1234/devtools/browser/test')
            self.assertIs(adapter.page,page)
            pw.chromium.launch_persistent_context.assert_not_called()
            context.new_page.assert_not_called()
            page.goto.assert_not_called()
            page.locator('#tallnum-limit').select_option.assert_not_called()
            page.set_viewport_size.assert_not_called()
            page.set_focus_emulation.assert_called_once_with(True)
            adapter.close()
            self.assertEqual(page.set_focus_emulation.call_args.args,(False,))
            context.close.assert_not_called()
            pw.chromium.connect_over_cdp.return_value.close.assert_not_called()
            connection.close.assert_called_once()
            start.assert_not_called()

    def test_missing_tab_does_not_create_one(self):
        context=MagicMock(pages=[self.page('https://example.com/tallnum')])
        with self.assertRaises(IncompatibleState): select_existing_page([context])
        context.new_page.assert_not_called()

    def test_ambiguous_tabs_require_focus(self):
        a,b=self.page(),self.page()
        context=MagicMock(pages=[a,b])
        with self.assertRaises(IncompatibleState): select_existing_page([context])
        b.evaluate.return_value=True
        self.assertIs(select_existing_page([context]),b)

    def test_missing_debug_endpoint_never_falls_back_to_launch(self):
        pw=MagicMock()
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'LOCALAPPDATA':tmp}), patch('playwright.sync_api.sync_playwright') as start:
            start.return_value.start.return_value=pw
            with self.assertRaises(IncompatibleState): BrowserAdapter(tmp)
            pw.chromium.launch_persistent_context.assert_not_called()
            pw.chromium.connect_over_cdp.assert_not_called()
            start.assert_not_called()

    def test_discovery_uses_websocket_without_http_version_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ',{'LOCALAPPDATA':tmp}):
            path=Path(tmp)/'Google/Chrome/User Data/DevToolsActivePort'
            path.parent.mkdir(parents=True)
            path.write_text('1234\n/devtools/browser/test\n')
            self.assertEqual(existing_endpoint(),'ws://127.0.0.1:1234/devtools/browser/test')
            path.write_text('1234\n/unexpected\n')
            with self.assertRaises(IncompatibleState): existing_endpoint()

    def test_wrong_game_configuration_is_preserved(self):
        page=self.page()
        page.locator('#tallnum-limit').input_value.return_value='5'
        context=MagicMock(pages=[page])
        pw=MagicMock()
        connection=MagicMock(contexts=[context])
        with tempfile.TemporaryDirectory() as tmp, patch('playwright.sync_api.sync_playwright') as start, patch('automation.existing_browser.ExistingConnection',return_value=connection):
            start.return_value.start.return_value=pw
            with self.assertRaises(IncompatibleState): BrowserAdapter(tmp,cdp_endpoint='ws://127.0.0.1:1234/test')
            page.locator('#tallnum-limit').select_option.assert_not_called()
            context.close.assert_not_called()
            start.assert_not_called()
