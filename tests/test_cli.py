from quantgres.cli import main


def test_doctor_prints_configuration(capsys):
    exit_code = main(["doctor"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Quantgres" in output
    assert "Environment: local" in output
    assert "Database URL: postgresql://quantgres:***@localhost:5432/quantgres" in output
