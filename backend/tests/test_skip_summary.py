"""Without a database, DB tests skip loudly instead of looking like passes."""

import os
import re
import subprocess
import sys

from tests.conftest import BACKEND_DIR


def test_db_tests_skip_with_loud_summary_when_database_url_unset() -> None:
    # An empty value overrides any DATABASE_URL in backend/.env.
    env = {**os.environ, "DATABASE_URL": ""}
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "tests/test_schema_constraints.py",
            "tests/test_db_guard.py",
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"(\d+) database tests SKIPPED: DATABASE_URL not set", result.stdout)
    assert match, result.stdout
    assert int(match.group(1)) > 0
