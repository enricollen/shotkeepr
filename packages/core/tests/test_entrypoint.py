import pytest

from shotkeepr.core import __main__ as entrypoint
from shotkeepr.core import __version__
from shotkeepr.core.__main__ import main


def test_main_returns_zero() -> None:
    assert main([]) == 0


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_serve_command_wires_dependencies_and_starts_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    data_dir = tmp_path / "data"  # type: ignore[operator]
    monkeypatch.setattr(entrypoint, "app_data_dir", lambda: data_dir)
    monkeypatch.setattr(entrypoint, "db_path", lambda: data_dir / "shotkeepr.db")
    monkeypatch.setattr(entrypoint, "log_dir", lambda: data_dir / "logs")
    monkeypatch.setattr(entrypoint, "runtime_dir", lambda: data_dir / "run")

    calls: dict[str, object] = {}

    def fake_run_server(service: object, runtime: object, *, port: int | None) -> None:
        calls["service"] = service
        calls["runtime"] = runtime
        calls["port"] = port

    monkeypatch.setattr(entrypoint, "run_server", fake_run_server)

    assert main(["serve", "--port", "12345"]) == 0
    assert calls["port"] == 12345
    assert calls["runtime"] == data_dir / "run"
    assert data_dir.exists()  # type: ignore[union-attr]
