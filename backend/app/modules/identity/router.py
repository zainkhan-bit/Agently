"""Authentication endpoints under /api/auth."""

from fastapi import APIRouter, Response, status

from app.modules.identity import service, sessions
from app.modules.identity.dependencies import CurrentUser, Db, Info, SessionToken
from app.modules.identity.models import User
from app.modules.identity.schemas import LoginRequest, PublicUser, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])

# Every route that works without a session. Any other route must depend on get_current_user;
# tests/test_route_inventory.py enforces this. Logout is public so that a browser with an
# expired session can still clear its cookie.
PUBLIC_ROUTES = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/health/ready"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        # Interactive docs: not registered in production.
        ("GET", "/api/docs"),
        ("GET", "/api/openapi.json"),
        ("GET", "/docs/oauth2-redirect"),
    }
)


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=PublicUser)
def register(body: RegisterRequest, response: Response, db: Db, info: Info) -> User:
    user, token = service.register(db, body.email, body.password.get_secret_value(), info)
    sessions.set_cookie(response, token)
    return user


@router.post("/login", response_model=PublicUser)
def login(body: LoginRequest, response: Response, db: Db, info: Info) -> User:
    user, token = service.login(db, body.email, body.password.get_secret_value(), info)
    sessions.set_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, db: Db, token: SessionToken, info: Info) -> None:
    service.logout(db, token, info)
    sessions.clear_cookie(response)


@router.get("/me", response_model=PublicUser)
def me(user: CurrentUser) -> User:
    return user
