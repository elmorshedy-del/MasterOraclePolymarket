"""Smoke tests for TagService discovery + COLUMN_TAGS contract."""

from __future__ import annotations

from src.analytics.tag_service import COLUMN_TAGS, TagService


def test_tag_service_discovers_tags():
    svc = TagService()
    names = {t.name for t in svc.tags}
    assert "entry_price_bucket" in names
    assert "day_of_week" in names
    assert "market_category" in names
    assert "news_regime" in names
    assert "counterparty_estimate" in names


def test_column_tags_subset_of_loaded_tags():
    svc = TagService()
    loaded = {t.name for t in svc.tags}
    # Every COLUMN_TAGS entry must correspond to a loaded plugin (otherwise
    # the persistence layer writes NULL forever for that column).
    missing = COLUMN_TAGS - loaded
    assert missing == set(), f"COLUMN_TAGS reference plugins that aren't loaded: {missing}"


def test_no_duplicate_tag_names():
    svc = TagService()
    names = [t.name for t in svc.tags]
    assert len(names) == len(set(names)), f"duplicate plugin names: {names}"
