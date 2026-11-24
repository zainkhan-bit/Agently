"""Only one test run at a time may use the throwaway databases."""

import subprocess
import sys

import pytest

from tests import db_utils
from tests.conftest import BACKEND_DIR


def run_pytest(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *arguments],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.db
def test_a_second_run_stops_before_touching_the_database(test_engine) -> None:
    """This run holds the lock, so a run started now must refuse."""
    second = run_pytest("tests/test_db_session.py")
    assert second.returncode == pytest.ExitCode.USAGE_ERROR
    assert "another test run is using agently_test" in second.stdout + second.stderr
    assert "passed" not in second.stdout and "failed" not in second.stdout
    with test_engine.connect() as connection:  # still there
        assert connection.engine.url.database == db_utils.TEST_DATABASE_NAME


@pytest.mark.db
def test_tests_without_a_database_may_run_meanwhile() -> None:
    assert run_pytest("tests/test_db_guard.py").returncode == 0


@pytest.mark.db
def test_the_lock_is_free_again_after_the_run_that_held_it(database_url, monkeypatch) -> None:
    monkeypatch.setattr(db_utils, "RUN_LOCK_KEY", db_utils.RUN_LOCK_KEY + 1)
    first = db_utils.lock_test_run(database_url)
    assert first is not None
    assert db_utils.lock_test_run(database_url) is None
    db_utils.unlock_test_run(first)
    again = db_utils.lock_test_run(database_url)
    assert again is not None
    db_utils.unlock_test_run(again)
