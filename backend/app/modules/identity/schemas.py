"""Request and response shapes for authentication."""

import re
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, SecretStr
from pydantic_core import PydanticCustomError

from app.modules.identity import passwords

# No email is ever sent, so this is a syntax check only. Printable ASCII keeps Python's and
# PostgreSQL's case folding identical, which the throttle keys rely on.
_EMAIL = re.compile(r"[!-?A-~]+@[!-?A-~]+\.[!-?A-~]+")


def _check_email(value: str) -> str:
    value = value.strip()
    if len(value) > 320 or not _EMAIL.fullmatch(value):
        raise PydanticCustomError("email_invalid", "Enter a valid email address.")
    return value


def _check_length(value: SecretStr, minimum: int) -> SecretStr:
    password = value.get_secret_value()
    if any(0xD800 <= ord(char) <= 0xDFFF for char in password):  # cannot be hashed as UTF-8
        raise PydanticCustomError("password_invalid", "Password contains invalid characters.")
    if not minimum <= len(password) <= passwords.MAX_LENGTH:
        raise PydanticCustomError(
            "password_length",
            f"Password must be {passwords.MIN_LENGTH} to {passwords.MAX_LENGTH} characters.",
        )
    return value


def _check_new_password(value: SecretStr) -> SecretStr:
    return _check_length(value, passwords.MIN_LENGTH)


def _check_login_password(value: SecretStr) -> SecretStr:
    # Only the maximum, which bounds hashing cost. A short password simply does not match.
    return _check_length(value, 0)


Email = Annotated[str, AfterValidator(_check_email)]


class RegisterRequest(BaseModel):
    email: Email
    password: Annotated[SecretStr, AfterValidator(_check_new_password)]


class LoginRequest(BaseModel):
    email: Email
    password: Annotated[SecretStr, AfterValidator(_check_login_password)]


class PublicUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime
