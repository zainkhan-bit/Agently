"""DEVELOPMENT ONLY: delete the throwaway accounts made by docs/manual-checks.

Run from backend/. The browser checks run this themselves; ``--all`` clears up after interrupted
runs.

    .venv\\Scripts\\python -m scripts.delete_check_accounts browser-check-1@example.com
    .venv\\Scripts\\python -m scripts.delete_check_accounts --all

Only ``browser-check-*@example.com`` accounts and the workspaces nobody else belongs to. Deletes
nothing unless ENVIRONMENT=development and the database is on this machine.
"""

import re
import sys

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.models import Membership, User, Workspace
from scripts.seed_dev import is_local_database

CHECK_EMAIL = re.compile(r"browser-check-[a-z0-9-]+@example\.com")


def delete_accounts(session: Session, emails: list[str] | None) -> int:
    """Delete these check accounts (None = all of them). Returns how many were deleted."""
    found = session.execute(select(User.id, User.email).where(User.email.like("browser-check-%")))
    users = {
        user_id
        for user_id, email in found
        if CHECK_EMAIL.fullmatch(email) and (emails is None or email in emails)
    }
    workspaces = select(Membership.workspace_id).where(Membership.user_id.in_(users))
    # Before the users: deleting those also deletes their memberships.
    shared = session.scalar(
        select(Membership.id)
        .where(Membership.workspace_id.in_(workspaces), Membership.user_id.not_in(users))
        .limit(1)
    )
    if shared is not None:
        raise ValueError("a workspace also has members who are not being deleted")
    session.execute(
        delete(Workspace).where(Workspace.id.in_(workspaces)),
        execution_options={"synchronize_session": False},
    )
    session.execute(
        delete(User).where(User.id.in_(users)),
        execution_options={"synchronize_session": False},
    )
    session.commit()
    return len(users)


def main(args: list[str]) -> int:
    emails = None if args == ["--all"] else args
    if not args or any(not CHECK_EMAIL.fullmatch(email) for email in emails or []):
        print("Give browser-check-*@example.com emails, or --all.", file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.environment != "development":
        print("Refusing to delete: ENVIRONMENT is not development.", file=sys.stderr)
        return 1
    url = settings.database_url
    if url is None or not is_local_database(url.get_secret_value()):
        print("Refusing to delete: DATABASE_URL must point to a local database.", file=sys.stderr)
        return 1
    with get_session_factory()() as session:
        try:
            count = delete_accounts(session, emails)
        except ValueError as error:
            print(f"Nothing deleted: {error}.", file=sys.stderr)
            return 1
    print(f"Deleted {count} browser-check account(s).")
    return 0 if emails is None or count == len(set(emails)) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
