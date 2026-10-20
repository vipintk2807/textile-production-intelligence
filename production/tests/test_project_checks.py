"""Configuration, migration and security-setting checks."""

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection


def test_django_system_check_passes(db):
    call_command("check")


@pytest.mark.django_db
def test_migrations_match_models():
    # Exits with status 1 (SystemExit) if models and migrations disagree.
    call_command("makemigrations", "--check", "--dry-run")


def test_timezone_settings_are_aware_and_configured():
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE


def test_csrf_and_clickjacking_middleware_enabled():
    assert "django.middleware.csrf.CsrfViewMiddleware" in settings.MIDDLEWARE
    assert "django.middleware.clickjacking.XFrameOptionsMiddleware" in settings.MIDDLEWARE


def test_no_external_asset_urls_in_base_template():
    from pathlib import Path

    html = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html


def test_tests_use_an_isolated_database(db):
    assert connection.settings_dict["NAME"] != str(settings.BASE_DIR / "db.sqlite3")
