"""Import every model module so ``Base.metadata`` is complete (used by Alembic and tests)."""

from app.core.database import Base
from app.modules.identity.models import User, UserSession
from app.modules.workspaces.models import Membership, Workspace

__all__ = ["Base", "Membership", "User", "UserSession", "Workspace"]
