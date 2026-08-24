from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIGURE_SCRIPT = ROOT / "scripts" / "configure-auto-update.sh"


def _fake_crontab(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    state = tmp_path / "crontab-state"
    command = tmp_path / "crontab"
    command.write_text(
        """#!/bin/sh
set -eu
if [ "${1:-}" = "-l" ]; then
    [ -f "$FAKE_CRONTAB_STATE" ] || exit 1
    exec /bin/cat "$FAKE_CRONTAB_STATE"
fi
exec /bin/cp "$1" "$FAKE_CRONTAB_STATE"
""",
        encoding="utf-8",
    )
    command.chmod(0o755)
    environment = os.environ.copy()
    environment["FAKE_CRONTAB_STATE"] = str(state)
    environment["PATH"] = f"{tmp_path}:/usr/local/bin:/usr/bin:/bin"
    return state, environment


def _configure(environment: dict[str, str], enabled: bool) -> subprocess.CompletedProcess[str]:
    environment["PINENDAR_AUTO_UPDATE"] = "true" if enabled else "false"
    return subprocess.run(
        [str(CONFIGURE_SCRIPT)],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )


def test_cron_entry_is_idempotent_and_preserves_other_jobs(tmp_path: Path) -> None:
    state, environment = _fake_crontab(tmp_path)
    existing_job = "15 3 * * * /opt/other-backup # unrelated\n"
    state.write_text(existing_job, encoding="utf-8")

    _configure(environment, enabled=True)
    _configure(environment, enabled=True)

    scheduled = state.read_text(encoding="utf-8")
    assert existing_job in scheduled
    assert scheduled.count("# Pinendar automatic update:") == 1
    assert " * * * * " in scheduled

    _configure(environment, enabled=False)

    assert state.read_text(encoding="utf-8") == existing_job


def test_enabled_check_does_not_modify_crontab(tmp_path: Path) -> None:
    state, environment = _fake_crontab(tmp_path)
    existing_job = "15 3 * * * /opt/other-backup\n"
    state.write_text(existing_job, encoding="utf-8")
    environment["PINENDAR_AUTO_UPDATE"] = "false"

    result = subprocess.run(
        [str(CONFIGURE_SCRIPT), "--is-enabled"],
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 1
    assert state.read_text(encoding="utf-8") == existing_job
