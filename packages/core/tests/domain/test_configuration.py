import pytest

from shotkeepr.core.domain.configuration import (
    AppSettings,
    Edition,
    InvalidConfigurationError,
    LlmProviderConfig,
    LogLevel,
    Theme,
)


def test_defaults_are_private_and_open() -> None:
    s = AppSettings()
    assert s.theme is Theme.DARK
    assert s.catalog_enabled is False
    assert s.edition is Edition.OPEN
    assert s.allows_non_commercial_plugins
    assert s.llm is None


def test_commercial_edition_blocks_non_commercial_plugins() -> None:
    assert not AppSettings(edition=Edition.COMMERCIAL).allows_non_commercial_plugins


def test_roundtrip_dict() -> None:
    s = AppSettings(
        theme=Theme.LIGHT,
        log_level=LogLevel.DEBUG,
        llm=LlmProviderConfig("ollama", "llama3", endpoint="http://localhost:11434"),
        extra={"volume_map": {"/photos": "C:/Foto"}},
    )
    assert AppSettings.from_dict(s.to_dict()) == s


@pytest.mark.parametrize(
    "data",
    [{"theme": "PINK"}, {"edition": "X"}, {"llm": {"provider": "", "model": "m"}}],
)
def test_invalid_dict_rejected(data: dict[str, object]) -> None:
    with pytest.raises(InvalidConfigurationError):
        AppSettings.from_dict(data)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"endpoint": "ftp://x"},
        {"endpoint": "not a url"},
        {"credential_ref": "Bad Ref!"},
        {"timeout_s": 0.5},
    ],
)
def test_invalid_llm_config(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidConfigurationError):
        LlmProviderConfig("openai", "gpt-4o-mini", **kwargs)  # type: ignore[arg-type]


def test_litellm_model_name() -> None:
    assert LlmProviderConfig("anthropic", "claude-x").litellm_model == "anthropic/claude-x"
