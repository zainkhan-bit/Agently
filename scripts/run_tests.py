"""Run the given test files with the right tool, from the right folder, on any OS.

Used by gstack's /verify (.gstack/pregate.json), which otherwise calls ``python3``: on Windows that
is usually the Microsoft Store alias. Any Python can start this script; the backend tests run in
backend/.venv, and from backend/ so that backend/.env is found (otherwise every database test
would be skipped).

    python scripts/run_tests.py backend/tests/test_health.py frontend/src/lib/x.test.ts

Backend files run in batches of BATCH, one pytest process after another: the whole suite in one
process needs more memory than the development machine has free.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / "backend" / ".venv"
BATCH = 6


def main(files: list[str]) -> int:
    paths = [Path(file) for file in files]
    backend = [str(path.relative_to("backend")) for path in paths if path.parts[0] == "backend"]
    frontend = [path.relative_to("frontend") for path in paths if path.parts[0] == "frontend"]
    if not files or len(backend) + len(frontend) != len(files):
        print("Give one or more test files under backend/ or frontend/.", file=sys.stderr)
        return 2

    commands = []
    if backend:
        candidates = (VENV / "Scripts" / "python.exe", VENV / "bin" / "python")
        python = next((path for path in candidates if path.exists()), None)
        if python is None:
            print("backend/.venv is missing: see README, Backend.", file=sys.stderr)
            return 2
        for start in range(0, len(backend), BATCH):
            batch = backend[start : start + BATCH]
            commands.append(("backend", [str(python), "-m", "pytest", *batch]))
    if frontend:
        npx = shutil.which("npx")
        if npx is None:
            print("npx is not on PATH: install Node.js.", file=sys.stderr)
            return 2
        tests = [path.as_posix() for path in frontend]
        commands.append(("frontend", [npx, "vitest", "run", *tests]))

    # Run every suite even if one fails, and fail if any did.
    codes = [
        subprocess.run(command, check=False, cwd=ROOT / folder).returncode  # noqa: S603 - no shell
        for folder, command in commands
    ]
    return next((code for code in codes if code), 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
