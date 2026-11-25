"""Which provider this server uses. Chosen by configuration only, never by a request."""

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.errors import ConflictError
from app.modules.providers.contract import Provider
from app.modules.providers.gemini import GeminiProvider
from app.modules.providers.mock import MockProvider
from app.modules.providers.models import GEMINI_MODELS
from app.modules.providers.spending import MeteredProvider

# Who receives what people type. The frontend has the wording.
Disclosure = Literal["none", "gemini_free", "gemini_paid"]


@lru_cache(maxsize=1)
def _gemini(key: str, model: str) -> Provider:
    """Once per process: every builder request asks for the provider."""
    spec = GEMINI_MODELS[model]
    return MeteredProvider(GeminiProvider(key, spec), spec, get_session_factory())


def get_provider() -> Provider | None:
    settings = get_settings()
    if settings.model_provider == "mock":
        return MockProvider(settings.mock_provider_scenario)
    if settings.model_provider == "gemini":
        return _gemini(settings.check_gemini(), settings.gemini_model)
    return None


def current_disclosure() -> Disclosure:
    settings = get_settings()
    if settings.model_provider != "gemini":
        return "none"
    return "gemini_paid" if settings.gemini_tier == "paid" else "gemini_free"


def current_model() -> str:
    settings = get_settings()
    return settings.gemini_model if settings.model_provider == "gemini" else "mock"


class DisclosureChangedError(ConflictError):
    code = "disclosure_changed"
    message = "Who receives what you type has changed. Nothing was sent. Read the notice first."


def check_disclosure(shown: str) -> None:
    """Nothing goes to anyone the person was not told about."""
    if shown != current_disclosure():
        raise DisclosureChangedError()


CurrentProvider = Annotated[Provider | None, Depends(get_provider)]
