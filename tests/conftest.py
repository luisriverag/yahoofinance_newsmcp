import pytest

from yahoofinance_newsmcp.config import reset_settings_cache


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Settings are cached with lru_cache; make each test see its own monkeypatched env."""

    reset_settings_cache()
    yield
    reset_settings_cache()