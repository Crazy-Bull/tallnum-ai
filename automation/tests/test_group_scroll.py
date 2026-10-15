import unittest
from unittest.mock import MagicMock
from automation.browser import group_scroll_delta,InputInterrupted,GestureNotReady,BrowserAdapter


class GroupScrollTests(unittest.TestCase):
    def test_visible_range_keeps_viewport_still(self):
        self.assertEqual(group_scroll_delta([{'y':600,'height':100},{'y':480,'height':100}],800),0)
        self.assertEqual(group_scroll_delta([{'y':0,'height':100},{'y':700,'height':100}],800),0)

    def test_scrolls_only_as_far_as_needed(self):
        self.assertEqual(group_scroll_delta([{'y':-20,'height':100},{'y':100,'height':100}],800),-44)
        self.assertEqual(group_scroll_delta([{'y':700,'height':100},{'y':820,'height':100}],800),144)

    def test_impossible_range_pauses_before_drag(self):
        with self.assertRaises(InputInterrupted):
            group_scroll_delta([{'y':0,'height':100},{'y':800,'height':100}],800)

    def adapter(self,hit=0,selection=None):
        adapter=BrowserAdapter.__new__(BrowserAdapter)
        page=MagicMock()
        adapter.page=page
        adapter.fast_animations=False
        page.evaluate.side_effect=lambda expr,*args:hit if 'elementFromPoint' in expr else 900
        page.locator.return_value.bounding_box.return_value={'x':100,'y':300,'width':100,'height':50}
        page.locator.return_value.evaluate_all.return_value=selection or [0]
        page.locator.return_value.count.return_value=1
        return adapter

    def test_wrong_hit_never_presses_mouse(self):
        a=self.adapter(hit=3)
        with self.assertRaises(GestureNotReady): a._drag_group([0,1])
        a.page.mouse.down.assert_not_called()

    def test_incomplete_selection_returns_to_start_before_release(self):
        a=self.adapter()
        with self.assertRaises(GestureNotReady): a._drag_group([0,1])
        self.assertEqual(a.page.mouse.move.call_args.args,(150,325))
        a.page.mouse.up.assert_called_once()

    def test_cancelled_unchanged_drag_is_retried_once(self):
        a=self.adapter()
        a._drag_group=MagicMock(side_effect=[GestureNotReady('cancelled'),None])
        before={'actions':1,'drops':1}
        after={'actions':2,'drops':1}
        a.read=MagicMock(side_effect=[before,after])
        self.assertEqual(a.perform({'kind':'group','indices':[0,1]},before),after)
        self.assertEqual(a._drag_group.call_count,2)

    def test_accepted_action_is_not_retried(self):
        a=self.adapter()
        a._drag_group=MagicMock(side_effect=GestureNotReady('cancelled'))
        before={'actions':1,'drops':1}
        after={'actions':2,'drops':1}
        a.read=MagicMock(return_value=after)
        self.assertEqual(a.perform({'kind':'group','indices':[0,1]},before),after)
        self.assertEqual(a._drag_group.call_count,1)
