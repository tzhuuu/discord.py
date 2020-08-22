from unittest.mock import MagicMock, call

import pytest

from ..sliding_window import SlidingWindow


class CallbackHelper:
    def callback(self):
        pass


@pytest.fixture
def helper():
    cb = CallbackHelper()

    return cb


@pytest.fixture
def cb(helper: CallbackHelper):
    cb.callback = MagicMock()
    return cb.callback


def test_basic_window(helper: CallbackHelper, cb):
    sw = SlidingWindow(2, 10, cb)

    sw.add_data(0, 'a')
    cb.assert_called_with('a')

    sw.add_data(1, 'b')
    cb.assert_called_with('b')

    sw.add_data(2, 'c')
    cb.assert_called_with('c')

    sw.add_data(0, 'd')
    cb.assert_called_with('d')


def test_basic_buffer(helper: CallbackHelper, cb):
    sw = SlidingWindow(3, 10, cb)

    sw.add_data(1, 'b')
    sw.add_data(2, 'c')
    cb.assert_not_called()
    sw.add_data(0, 'a')
    cb.assert_has_calls([call('a'), call('b'), call('c')])


def test_window_start_offset(helper: CallbackHelper, cb):
    sw = SlidingWindow(3, 10, cb)

    sw.add_data(1, 'a')
    cb.assert_not_called()

    sw.add_data(3, 'b')
    cb.assert_has_calls([call('a'), call('b')])


def test_wrap_sequence_offset(helper: CallbackHelper, cb):
    sw = SlidingWindow(2, 3, cb)

    sw.add_data(0, 'a')
    cb.assert_called_with('a')
    sw.add_data(1, 'b')
    cb.assert_called_with('b')
    sw.add_data(2, 'c')
    cb.assert_called_with('c')
    sw.add_data(0, 'd')
    cb.assert_called_with('d')


def test_wrap_sequence_mod(helper: CallbackHelper, cb):
    sw = SlidingWindow(2, 3, cb)
    sw.add_data(0, 'a')
    cb.assert_called_with('a')
    sw.add_data(1, 'b')
    cb.assert_called_with('b')
    sw.add_data(2, 'c')
    cb.assert_called_with('c')
    sw.add_data(3, 'd')
    cb.assert_called_with('d')
    sw.add_data(4, 'e')
    cb.assert_called_with('e')


def test_buffer_wrap_sequence_offset(helper: CallbackHelper, cb):
    sw = SlidingWindow(3, 3, cb)
    sw.add_data(0, 'a')
    cb.assert_called_with('a')
    sw.add_data(1, 'b')
    cb.assert_called_with('b')
    sw.add_data(2, 'c')
    cb.assert_called_with('c')

    cb.reset_mock()
    sw.add_data(4, 'e')
    cb.assert_not_called()
    sw.add_data(3, 'd')
    cb.assert_has_calls([call('d'), call('e')])

# def test_sequence_jump(helper: CallbackHelper, cb):
#     sw = SlidingWindow(3, 10, cb)
#     sw.add()
