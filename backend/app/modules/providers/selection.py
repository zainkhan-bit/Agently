"""Which provider this server uses. Chosen by configuration only, never by a request."""

from typing import Annotated, Literal

from fastapi import Depends

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.providers.contract import Provider
from app.modules.providers.gemini import GeminiProvider
from app.modules.providers.mock import MockProvider
from app.modules.providers.models import GEMINI_MODELS
from app.modules.providers.spending import MeteredProvider

# Who receives what people type. The frontend has the wording.
Disclosure = Literal["none", "gemini_free", "gemini_paid"]


def get_provider() -> Provider | None:
    settings = get_settings()
    if settings.model_provider == "mock":
        return MockProvider(settings.mock_provider_scenario)
    if settings.model_provider == "gemini":
        key = settings.check_gemini()
        spec = GEMINI_MODELS[settings.gemini_model]
        return MeteredProvider(GeminiProvider(key, spec), spec, get_session_factory())
    return None


def current_disclosure() -> Disclosure:
    settings = get_settings()
    if settings.model_provider != "gemini":
        return "none"
    return "gemini_paid" if settings.gemini_tier == "paid" else "gemini_free"


CurrentProvider = Annotated[Provider | None, Depends(get_provider)]
