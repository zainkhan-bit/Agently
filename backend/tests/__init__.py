"""Runs before anything imports app.main, which creates the app."""

import os

from app.core.config import get_settings

# An unset ENVIRONMENT means production, which would stop the suite without a backend/.env.
if get_settings().environment == "production":
    os.environ["ENVIRONMENT"] = "development"
    get_settings.cache_clear()
