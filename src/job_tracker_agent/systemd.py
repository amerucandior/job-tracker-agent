"""Systemd user service/timer generation and desktop notifications.

Adheres to docs/adr/0004-periodic-execution-via-systemd-user-timer.md.
"""

import logging
import os
from pathlib import Path
import shutil
import subprocess

logger = logging.getLogger(__name__)


def send_desktop_notification(title: str, message: str, urgency: str = "normal") -> bool:
    """Send a native Linux desktop notification using notify-send."""
    notify_send = shutil.which("notify-send")
    if not notify_send:
        logger.debug("notify-send binary not found on system. Skipping notification.")
        return False

    try:
        subprocess.run(
            [
                notify_send,
                "--app-name=Job Tracker",
                f"--urgency={urgency}",
                "--icon=mail-unread",
                title,
                message,
            ],
            check=False,
            timeout=5,
        )
        return True
    except Exception as e:
        logger.debug(f"Failed to send desktop notification: {e}")
        return False


def get_systemd_user_dir() -> Path:
    """Return user systemd directory (~/.config/systemd/user)."""
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    return systemd_dir


def generate_service_units(
    working_dir: Path,
    interval_minutes: int = 30,
) -> tuple[Path, Path]:
    """Generate and write job-tracker.service and job-tracker.timer units."""
    systemd_dir = get_systemd_user_dir()
    venv_python = working_dir / ".venv" / "bin" / "job-tracker"
    if not venv_python.exists():
        venv_python = Path(shutil.which("job-tracker") or "/usr/bin/job-tracker")

    service_content = f"""[Unit]
Description=Job Tracker Agent periodic email synchronization
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={working_dir.resolve()}
ExecStart={venv_python.resolve()} sync
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""

    timer_content = f"""[Unit]
Description=Job Tracker Agent sync timer
Requires=job-tracker.service

[Timer]
OnBootSec=3m
OnUnitActiveSec={interval_minutes}m
Persistent=true

[Install]
WantedBy=timers.target
"""

    service_file = systemd_dir / "job-tracker.service"
    timer_file = systemd_dir / "job-tracker.timer"

    service_file.write_text(service_content, encoding="utf-8")
    timer_file.write_text(timer_content, encoding="utf-8")

    return service_file, timer_file


def run_systemctl_user(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a systemctl --user command."""
    return subprocess.run(
        ["systemctl", "--user"] + command,
        capture_output=True,
        text=True,
        check=False,
    )
