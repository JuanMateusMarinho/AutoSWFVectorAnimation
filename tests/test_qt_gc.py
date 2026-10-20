# tests/test_qt_gc.py
import gc
import threading
import weakref

from PySide6.QtCore import QObject


def test_qt_objects_in_cycles_are_destroyed_on_the_gui_thread(qapp):
    from autoswf.qt_gc import GuiThreadCollector
    collector = GuiThreadCollector()
    collector.start()
    try:
        seen = []
        obj = QObject()
        obj.me = obj                                            # a cycle: only the cycle collector frees it
        weakref.finalize(obj, lambda: seen.append(threading.get_ident()))
        del obj

        def allocate():                                         # enough to start several collections on this thread
            keep = [[] for _ in range(100_000)]
            return len(keep)
        worker = threading.Thread(target=allocate)
        worker.start()
        worker.join()
        assert seen == []
        collector.collect()
        assert seen == [threading.get_ident()]
    finally:
        collector.stop()


def test_the_test_session_collects_cycles_on_the_gui_thread():
    assert not gc.isenabled()                                   # conftest: as in the app, never on a worker thread
