from pathlib import Path
from typer.testing import CliRunner
from job_tracker_agent.cli import app
from job_tracker_agent.systemd import generate_service_units

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "AI agent that ingests job application emails" in result.output
    assert "setup-notion" in result.output
    assert "sync" in result.output
    assert "auth" in result.output
    assert "service" in result.output


def test_cli_config():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "Job Tracker Configuration" in result.output
    assert "gemini" in result.output


def test_generate_service_units(tmp_path, monkeypatch):
    monkeypatch.setattr("job_tracker_agent.systemd.get_systemd_user_dir", lambda: tmp_path)
    service_file, timer_file = generate_service_units(tmp_path, interval_minutes=45)

    assert service_file.exists()
    assert timer_file.exists()

    service_text = service_file.read_text()
    timer_text = timer_file.read_text()

    assert "job-tracker sync" in service_text
    assert "OnUnitActiveSec=45m" in timer_text
