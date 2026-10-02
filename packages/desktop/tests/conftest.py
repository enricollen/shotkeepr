import os
from collections.abc import Callable

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    app.setStyle("Fusion")
    return app


@pytest.fixture
def wait_until(qt_app: QApplication) -> Callable[[Callable[[], bool]], None]:
    def wait(predicate: Callable[[], bool]) -> None:
        for _ in range(500):
            qt_app.processEvents()
            if predicate():
                return
            QTest.qWait(20)
        pytest.fail("Qt operation did not complete within 10 seconds")

    return wait
