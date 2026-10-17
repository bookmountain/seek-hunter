from pathlib import Path

import pytest

from seekhunter.config import get_env

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _dev_mode(monkeypatch):
    """Tests use short, predictable write tokens; opt in to dev mode so create_app doesn't reject them."""
    monkeypatch.setenv("SEEKHUNTER_DEV", "1")
    get_env.cache_clear()
    yield
    get_env.cache_clear()
