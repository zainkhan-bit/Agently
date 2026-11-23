"""DEVELOPMENT ONLY: create a demo user, workspace, and owner membership.

Run from backend/ after `alembic upgrade head`:

    .venv\\Scripts\\python -m scripts.seed_dev

Safe to run more than once (it only creates what is missing). Refuses to run when
ENVIRONMENT=production or when the database is not on this machine. The demo password is random
and printed once, when the user is created.
"""

import os
import secrets
import sys

from sqlalchemy import func, make_url, select
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models import Membership, User, Workspace
from app.modules.identity.passwords import hash_password

DEMO_EMAIL = "demo@agently.local"
DEMO_WORKSPACE = "Demo Workspace"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Anything else in the query string could redirect the connection (hostaddr, service, conninfo).
SAFE_QUERY_KEYS = frozenset({"host", "hostaddr", "sslmode", "connect_timeout"})
# libpq reads these from the environment and they can override the host in the URL.
REDIRECT_VARIABLES = ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE")


def is_local_database(url: str) -> bool:
    """True only when every host the driver could connect to is this machine."""
    try:
        parsed = make_url(url)
    except ArgumentError:
        return False
    if not SAFE_QUERY_KEYS.issuperset(parsed.query):
        return False
    if any(os.environ.get(name) for name in REDIRECT_VARIABLES):
        return False
    hosts = [parsed.host or ""]
    for key in ("host", "hostaddr"):  # query values override the host in the URL
        value = parsed.query.get(key, ())
        hosts += [value] if isinstance(value, str) else value
    return all(host.lower() in LOCAL_HOSTS for host in hosts)


def seed(session: Session) -> str | None:
    """Create the demo records if absent. Returns the new password, or None if they existed."""
    user = session.scalar(select(User).where(func.lower(User.email) == DEMO_EMAIL.lower()))
    if user is not None:
        return None
    password = secrets.token_urlsafe(18)
    user = User(email=DEMO_EMAIL, password_hash=hash_password(password))
    workspace = Workspace(name=DEMO_WORKSPACE)
    session.add_all([user, workspace])
    session.flush()
    session.add(Membership(user_id=user.id, workspace_id=workspace.id, role="owner"))
    session.commit()
    return password


def main() -> int:
    print("== Agently DEVELOPMENT seed data ==")
    if get_settings().is_production:
        print("Refusing to seed: ENVIRONMENT=production.", file=sys.stderr)
        return 1
    url = get_settings().database_url
    if url is None or not is_local_database(url.get_secret_value()):
        print("Refusing to seed: DATABASE_URL must point to a local database.", file=sys.stderr)
        return 1
    with get_session_factory()() as session:
        password = seed(session)
    if password:
        print(f"Created demo user {DEMO_EMAIL} and '{DEMO_WORKSPACE}'.")
        print(f"Password (shown once): {password}")
    else:
        print(f"Demo user {DEMO_EMAIL} already exists; nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
