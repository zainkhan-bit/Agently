"""Import every model module so ``Base.metadata`` is complete (used by Alembic and tests)."""

from app.core.database import Base
from app.modules.agents.models import Agent, AgentVersion
from app.modules.conversations.models import Conversation, StoredMessage
from app.modules.identity.models import AuthThrottleEvent, User, UserSession
from app.modules.providers.tables import ProviderSpend
from app.modules.workspaces.models import Membership, Workspace

__all__ = [
    "Agent",
    "AgentVersion",
    "AuthThrottleEvent",
    "Base",
    "Conversation",
    "Membership",
    "ProviderSpend",
    "StoredMessage",
    "User",
    "UserSession",
    "Workspace",
]
