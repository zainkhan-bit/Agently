"""Runs before anything imports app.main, which creates the app."""

import os

from app.core.config import get_settings

# Never a real provider or key in tests, whatever backend/.env holds. The environment wins over it,
# and child processes inherit it. Must come before the first get_settings().
os.environ["MODEL_PROVIDER"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["GEMINI_MODEL"] = "gemini-3.5-flash-lite"
os.environ["GEMINI_TIER"] = "free"

# An unset ENVIRONMENT means production, which would stop the suite without a backend/.env.
if get_settings().environment == "production":
    os.environ["ENVIRONMENT"] = "development"
    get_settings.cache_clear()
