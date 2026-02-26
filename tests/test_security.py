import pytest

from app.config import Settings
from app.services.scraper import ScrapeError, validate_scrape_url


def test_validate_scrape_url_allowlist_enforced() -> None:
    settings = Settings(
        api_keys="x",
        scrape_allowlist="example.com",
        database_url="sqlite:///./tmp.db",
    )

    with pytest.raises(ScrapeError):
        validate_scrape_url("https://not-allowed.com/vendors", settings)
