from quantgres.cli import main
from quantgres.runtime import DatabaseRuntimeInfo, ExtensionStatus


def test_doctor_prints_configuration(capsys):
    exit_code = main(["doctor"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Quantgres" in output
    assert "Environment: local" in output
    assert "Database URL: postgresql://quantgres:***@localhost:55432/quantgres" in output


def test_db_info_prints_runtime_metadata(monkeypatch, capsys):
    info = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(
            ExtensionStatus(name="pg_trgm", version="1.6"),
            ExtensionStatus(name="vector", version="0.8.3"),
        ),
    )
    monkeypatch.setattr("quantgres.cli.load_runtime_info", lambda: info)

    exit_code = main(["db-info"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "PostgreSQL 18.4" in output
    assert "server_version_num: 180004" in output
    assert "- pg_trgm: 1.6" in output
    assert "- vector: 0.8.3" in output


def test_db_info_fails_when_required_extension_is_missing(monkeypatch, capsys):
    info = DatabaseRuntimeInfo(
        server_version="PostgreSQL 18.4 on test",
        server_version_num=180004,
        database_name="quantgres",
        user_name="quantgres",
        extensions=(ExtensionStatus(name="vector", version="0.8.3"),),
    )
    monkeypatch.setattr("quantgres.cli.load_runtime_info", lambda: info)

    exit_code = main(["db-info"])

    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Missing required extensions: pg_trgm" in output
