"""Smoke test for cookidoo-api."""

from collections.abc import AsyncGenerator
import json
import os

from aiohttp import ClientSession
from dotenv import load_dotenv
import pytest

from cookidoo_api.cookidoo import Cookidoo
from cookidoo_api.helpers import get_localization_options
from cookidoo_api.types import (
    CookidooAuthResponse,
    CookidooConfig,
    CookidooLocalizationConfig,
)

load_dotenv()


def save_token(token: CookidooAuthResponse) -> None:
    """Save the token locally."""
    with open(".token", "w", encoding="utf-8") as file:
        file.write(json.dumps(token.__dict__))


def load_token() -> CookidooAuthResponse:
    """Load the token locally."""
    # Open and read the file
    with open(".token", encoding="utf-8") as file:
        token = file.read()
        return CookidooAuthResponse(**json.loads(token))


@pytest.fixture(name="auth_data")
async def auth_data() -> CookidooAuthResponse:
    """Load the token."""

    return load_token()


@pytest.fixture(name="session")
async def aiohttp_client_session() -> AsyncGenerator[ClientSession]:
    """Create  a client session."""
    async with ClientSession() as session:
        yield session


@pytest.fixture(name="cookidoo_no_auth")
async def cookidoo_api_client_no_auth(session: ClientSession) -> Cookidoo:
    """Create Cookidoo instance."""

    cookidoo = Cookidoo(
        session,
        cfg=await _cookidoo_config_from_env(),
    )
    return cookidoo


@pytest.fixture(name="cookidoo")
async def cookidoo_authenticated_api_client(
    session: ClientSession, auth_data: CookidooAuthResponse
) -> Cookidoo:
    """Create authenticated Cookidoo instance."""

    cookidoo = Cookidoo(
        session,
        cfg=await _cookidoo_config_from_env(),
    )

    # Restore auth data from saved token
    cookidoo.auth_data = auth_data

    return cookidoo


async def _cookidoo_config_from_env() -> CookidooConfig:
    country = os.environ.get("COUNTRY", "ar")
    language = os.environ.get("LANGUAGE")
    localizations = await get_localization_options(country=country, language=language)
    if not localizations:
        msg = f"No Cookidoo localization found for country={country!r}, language={language!r}"
        raise ValueError(msg)

    return CookidooConfig(
        email=_email_from_env(country),
        password=os.environ["PASSWORD"],
        localization=_localization_from_env(localizations[0]),
    )


def _email_from_env(country: str) -> str:
    return os.environ.get(f"EMAIL_{country.upper()}") or os.environ["EMAIL"]


def _localization_from_env(
    default_localization: CookidooLocalizationConfig,
) -> CookidooLocalizationConfig:
    return CookidooLocalizationConfig(
        country_code=os.environ.get("COUNTRY", default_localization.country_code),
        language=os.environ.get("LANGUAGE", default_localization.language),
        url=os.environ.get("COOKIDOO_URL", default_localization.url),
    )
