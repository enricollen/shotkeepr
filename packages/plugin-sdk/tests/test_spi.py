from shotkeepr.plugin_sdk import SPI_VERSION


def test_spi_version_is_semver_like() -> None:
    major, minor = SPI_VERSION.split(".")
    assert major.isdigit()
    assert minor.isdigit()
