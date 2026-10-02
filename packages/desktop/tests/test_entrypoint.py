import argparse
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QApplication

from shotkeepr.desktop import __main__ as entrypoint
from shotkeepr.desktop.__main__ import local_url, main
from shotkeepr.desktop.runtime import CoreRuntime


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert "shotkeepr 0.1.0" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8080",
        "http://example.com",
        "http://127.0.0.1:0",
        "http://127.0.0.1:99999",
        "http://user@127.0.0.1",
        "http://127.0.0.1/api",
        "http://127.0.0.1?token=secret",
        "http://127.0.0.1#fragment",
    ],
)
def test_non_local_or_invalid_origins_rejected(url: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        local_url(url)


def test_local_origin() -> None:
    assert local_url("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"


def test_endpoint_requires_token_file() -> None:
    with pytest.raises(SystemExit) as result:
        main(["--core-url", "http://127.0.0.1:8080"])
    assert result.value.code == 2


@pytest.mark.parametrize("contents", ["", "not a token", "\u00e8"])
def test_invalid_token_file(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "token"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(SystemExit) as result:
        main(["--core-url", "http://127.0.0.1:8321", "--token-file", str(path)])
    assert result.value.code == 2


def test_missing_token_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as result:
        main(["--core-url", "http://127.0.0.1:8321", "--token-file", str(tmp_path / "missing")])
    assert result.value.code == 2


def test_desktop_entrypoint_stops_owned_core(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtimes: list[CoreRuntime] = []

    def runtime(parent: QApplication) -> CoreRuntime:
        result = CoreRuntime(parent, data_dir=tmp_path)
        runtimes.append(result)
        return result

    monkeypatch.setattr(entrypoint, "CoreRuntime", runtime)
    QTimer.singleShot(500, qt_app.quit)
    assert main([]) == 0
    assert runtimes[0]._process.state() == QProcess.ProcessState.NotRunning
    assert runtimes[0]._directory is None


def test_external_endpoint_does_not_start_core(
    qt_app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[bool] = []
    endpoints: list[tuple[str, str]] = []
    monkeypatch.setattr(CoreRuntime, "start", lambda self: starts.append(True))
    monkeypatch.setattr(
        entrypoint.CoreConnection,
        "connect_to",
        lambda self, url, token: endpoints.append((url, token)),
    )
    path = tmp_path / "token"
    path.write_text("external-test-token", encoding="utf-8")
    QTimer.singleShot(100, qt_app.quit)
    assert main(["--core-url", "http://127.0.0.1:8321", "--token-file", str(path)]) == 0
    assert starts == []
    assert endpoints == [("http://127.0.0.1:8321", "external-test-token")]
