from quantgres.config import DEFAULT_DATABASE_URL, load_settings, mask_database_url


def test_load_settings_uses_defaults(monkeypatch):
    monkeypatch.delenv("QUANTGRES_ENV", raising=False)
    monkeypatch.delenv("QUANTGRES_DATABASE_URL", raising=False)

    settings = load_settings()

    assert settings.app_env == "local"
    assert settings.database_url == DEFAULT_DATABASE_URL


def test_load_settings_uses_environment(monkeypatch):
    monkeypatch.setenv("QUANTGRES_ENV", "test")
    monkeypatch.setenv("QUANTGRES_DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

    settings = load_settings()

    assert settings.app_env == "test"
    assert settings.database_url == "postgresql://user:pass@localhost:5432/db"


def test_mask_database_url_hides_password():
    masked = mask_database_url("postgresql://user:secret@localhost:5432/db")

    assert masked == "postgresql://user:***@localhost:5432/db"


def test_mask_database_url_without_password_is_unchanged():
    database_url = "postgresql://localhost:5432/db"

    assert mask_database_url(database_url) == database_url
