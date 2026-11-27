"""scripts/run_tests.py and .gstack/pregate.json, used by gstack's /verify."""

import importlib.util
import json
from types import SimpleNamespace

import pytest

from tests.conftest import BACKEND_DIR

ROOT = BACKEND_DIR.parent


@pytest.fixture
def script(monkeypatch):
    spec = importlib.util.spec_from_file_location("run_tests", ROOT / "scripts" / "run_tests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.calls = []
    module.codes = {}

    def run(command, check, cwd):
        module.calls.append((cwd.name, command))
        return SimpleNamespace(returncode=module.codes.get(cwd.name, 0))

    monkeypatch.setattr(module.subprocess, "run", run)
    return module


def test_each_suite_runs_from_its_own_folder(script) -> None:
    assert script.main(["backend/tests/test_health.py", "frontend/src/lib/x.test.ts"]) == 0
    (backend, pytest_command), (frontend, vitest_command) = script.calls
    assert (backend, frontend) == ("backend", "frontend")
    assert ".venv" in pytest_command[0]
    assert pytest_command[1:3] == ["-m", "pytest"]
    assert pytest_command[3].replace("\\", "/") == "tests/test_health.py"
    assert vitest_command[1:] == ["vitest", "run", "src/lib/x.test.ts"]


@pytest.mark.parametrize("failing", ["backend", "frontend"])
def test_one_failing_suite_fails_the_run_without_hiding_the_other(script, failing) -> None:
    script.codes = {failing: 3}
    assert script.main(["backend/tests/test_health.py", "frontend/src/lib/x.test.ts"]) == 3
    assert len(script.calls) == 2


def test_backend_files_run_in_batches_one_after_another(script) -> None:
    files = [f"backend/tests/test_{n}.py" for n in range(script.BATCH * 2 + 1)]
    script.codes = {"backend": 0}
    assert script.main(files) == 0
    sizes = [len(command) - 3 for _, command in script.calls]
    assert sizes == [script.BATCH, script.BATCH, 1]
    ran = [file.replace("\\", "/") for _, command in script.calls for file in command[3:]]
    assert ran == [file.removeprefix("backend/") for file in files]


@pytest.mark.parametrize("files", [[], ["other/test_x.py"], ["backend/tests/test_a.py", "x.py"]])
def test_unknown_files_are_refused(script, files) -> None:
    assert script.main(files) == 2
    assert script.calls == []


def test_missing_venv_is_an_error_not_a_skip(script, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(script, "VENV", tmp_path)
    assert script.main(["backend/tests/test_health.py"]) == 2
    assert script.calls == []


def test_verify_mapping_lists_every_test_file() -> None:
    mapping = json.loads((ROOT / ".gstack" / "pregate.json").read_text())["dependencies"]
    found = {
        path.relative_to(ROOT).as_posix()
        for folder, pattern in (("backend/tests", "test_*.py"), ("frontend/src", "**/*.test.ts*"))
        for path in (ROOT / folder).glob(pattern)
    }
    listed = {test for tests in mapping.values() for test in tests}
    assert listed == found
