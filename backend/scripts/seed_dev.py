"""DEVELOPMENT ONLY: create a demo user, workspace, and owner membership.

Run from backend/ after `alembic upgrade head`:

    .venv\\Scripts\\python -m scripts.seed_dev

Safe to run more than once (it only creates what is missing). Refuses to run when
ENVIRONMENT=production. The demo password below is deliberately public: never reuse it.
"""

import sys

from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models import Membership, User, Workspace

DEMO_EMAIL = "demo@agently.local"
DEMO_PASSWORD = "agently-demo-password"  # noqa: S105 - public dev-only credential
DEMO_WORKSPACE = "Demo Workspace"


def seed(session: Session) -> bool:
    """Create the demo records if absent. Returns True if anything was created."""
    user = session.scalar(select(User).where(func.lower(User.email) == DEMO_EMAIL.lower()))
    if user is not None:
        return False
    user = User(email=DEMO_EMAIL, password_hash=PasswordHasher().hash(DEMO_PASSWORD))
    workspace = Workspace(name=DEMO_WORKSPACE)
    session.add_all([user, workspace])
    session.flush()
    session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    session.commit()
    return True


def main() -> int:
    print("== Agently DEVELOPMENT seed data ==")
    if get_settings().is_production:
        print("Refusing to seed: ENVIRONMENT=production.", file=sys.stderr)
        return 1
    with get_session_factory()() as session:
        created = seed(session)
    if created:
        print(f"Created demo user {DEMO_EMAIL} (password: {DEMO_PASSWORD}) and '{DEMO_WORKSPACE}'.")
    else:
        print(f"Demo user {DEMO_EMAIL} already exists; nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
