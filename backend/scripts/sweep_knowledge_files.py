"""Remove knowledge files that have no record (left behind by a crash or a failed delete).

Only files older than an hour, so that uploads in progress are never touched.

    backend> .venv\Scripts\python -m scripts.sweep_knowledge_files
"""

import sys

from app.core.database import get_session_factory
from app.modules.knowledge import storage


def main() -> int:
    with get_session_factory()() as session:
        removed = storage.sweep(session)
    print(f"removed {removed} file(s) without a record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
