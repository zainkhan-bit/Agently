"""Which provider this server uses. Chosen by configuration only, never by a request."""

from typing import Annotated

from fastapi import Depends

from app.core.config import get_settings
from app.modules.providers.contract import Provider
from app.modules.providers.mock import MockProvider


def get_provider() -> Provider | None:
    settings = get_settings()
    if settings.model_provider == "mock":
        return MockProvider(settings.mock_provider_scenario)
    return None


CurrentProvider = Annotated[Provider | None, Depends(get_provider)]
