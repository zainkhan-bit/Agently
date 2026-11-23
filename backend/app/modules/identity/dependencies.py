"""Request dependencies for authentication."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.client_ip import get_client_ip
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AuthenticationError
from app.modules.identity import sessions
from app.modules.identity.events import RequestInfo
from app.modules.identity.models import User


def get_session_token(request: Request) -> str | None:
    return request.cookies.get(get_settings().session_cookie_name)


def get_request_info(request: Request) -> RequestInfo:
    return RequestInfo(ip=get_client_ip(request), request_id=request.state.request_id)


Db = Annotated[Session, Depends(get_db)]
SessionToken = Annotated[str | None, Depends(get_session_token)]
Info = Annotated[RequestInfo, Depends(get_request_info)]


def get_current_user(db: Db, token: SessionToken) -> User:
    """The signed-in user, or 401. Every private route must depend on this."""
    active = sessions.find_active_session(db, token)
    if active is None:
        raise AuthenticationError()
    return active.user


CurrentUser = Annotated[User, Depends(get_current_user)]
