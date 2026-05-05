#!/usr/bin/env python3
"""Run a live Cookidoo smoke test with best-effort cleanup."""

import argparse
import asyncio
from collections.abc import Sequence
from datetime import date
import os

import aiohttp
from dotenv import load_dotenv

from cookidoo_api import Cookidoo
from cookidoo_api.helpers import get_localization_options
from cookidoo_api.types import CookidooConfig, CookidooLocalizationConfig

DEFAULT_COUNTRY = "ar"
DEFAULT_LANGUAGE = "en"
DEFAULT_RECIPES = ["r59322", "r907015"]
DEFAULT_MANAGED_COLLECTION = "col500401"
DEFAULT_ADDITIONAL_ITEMS = ["OPENCLAW_TEST_FLOUR", "OPENCLAW_TEST_SALT"]


async def main() -> None:
    """Run live smoke checks."""
    load_dotenv()
    args = _parse_args()
    localization = await _localization_from_args(args)

    async with aiohttp.ClientSession() as session:
        cookidoo = Cookidoo(
            session,
            cfg=CookidooConfig(
                email=_email_from_env(args.country),
                password=os.environ["PASSWORD"],
                localization=localization,
            ),
        )
        await _run_smoke(cookidoo, args.recipes, args.managed_collection)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a live Cookidoo smoke test and remove created test data.",
    )
    parser.add_argument("--country", default=os.environ.get("COUNTRY", DEFAULT_COUNTRY))
    parser.add_argument(
        "--language",
        default=os.environ.get("LANGUAGE", DEFAULT_LANGUAGE),
        help="Cookidoo localization language. Use an empty string to accept any language.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("COOKIDOO_URL"),
        help="Override Cookidoo localization URL.",
    )
    parser.add_argument(
        "--recipe",
        action="append",
        dest="recipes",
        default=None,
        help="Recipe ID to use. Can be passed more than once.",
    )
    parser.add_argument(
        "--managed-collection",
        default=os.environ.get("MANAGED_COLLECTION", DEFAULT_MANAGED_COLLECTION),
    )
    return parser.parse_args()


async def _localization_from_args(args: argparse.Namespace) -> CookidooLocalizationConfig:
    language = args.language or None
    localizations = await get_localization_options(
        country=args.country,
        language=language,
    )
    if not localizations:
        msg = (
            "No Cookidoo localization found for "
            f"country={args.country!r}, language={language!r}"
        )
        raise ValueError(msg)

    localization = localizations[0]
    return CookidooLocalizationConfig(
        country_code=args.country,
        language=args.language or localization.language,
        url=args.url or localization.url,
    )


def _email_from_env(country: str) -> str:
    return os.environ.get(f"EMAIL_{country.upper()}") or os.environ["EMAIL"]


async def _run_smoke(
    cookidoo: Cookidoo,
    recipes: Sequence[str] | None,
    managed_collection: str,
) -> None:
    recipe_ids = list(recipes or DEFAULT_RECIPES)
    created_collection_id: str | None = None
    added_additional_ids: list[str] = []
    added_ingredients = False
    added_calendar = False
    added_managed = False

    try:
        await cookidoo.login()
        await cookidoo.refresh_token()
        subscription = await cookidoo.get_active_subscription()
        print("auth=ok")
        print(f"subscription_active={subscription.active if subscription else False}")

        recipe_details = await cookidoo.get_recipe_details(recipe_ids[0])
        print(f"recipe_details=ok:{recipe_details.id}")

        await cookidoo.clear_shopping_list()
        print("shopping_list_clear_start=ok")

        collection = await cookidoo.add_custom_collection("OPENCLAW_TEST_COLLECTION")
        created_collection_id = collection.id
        await cookidoo.add_recipes_to_custom_collection(
            created_collection_id,
            [recipe_ids[0]],
        )
        await cookidoo.remove_recipe_from_custom_collection(
            created_collection_id,
            recipe_ids[0],
        )
        print(f"custom_collection=ok:{created_collection_id}")

        managed = await cookidoo.add_managed_collection(managed_collection)
        added_managed = True
        print(f"managed_collection_add=ok:{managed.id}")

        await cookidoo.add_recipes_to_calendar(date.today(), recipe_ids)
        added_calendar = True
        print("calendar_add=ok")

        ingredients = await cookidoo.add_ingredient_items_for_recipes(recipe_ids)
        added_ingredients = True
        print(f"ingredients_add=ok:{len(ingredients)}")

        additional_items = await cookidoo.add_additional_items(DEFAULT_ADDITIONAL_ITEMS)
        added_additional_ids = [item.id for item in additional_items]
        print(f"additional_items_add=ok:{len(added_additional_ids)}")
    finally:
        cleanup_errors = await _cleanup(
            cookidoo=cookidoo,
            recipe_ids=recipe_ids,
            managed_collection=managed_collection,
            created_collection_id=created_collection_id,
            added_additional_ids=added_additional_ids,
            added_ingredients=added_ingredients,
            added_calendar=added_calendar,
            added_managed=added_managed,
        )
        if cleanup_errors:
            print("cleanup_errors=" + " | ".join(cleanup_errors))
            raise SystemExit(2)


async def _cleanup(
    cookidoo: Cookidoo,
    recipe_ids: Sequence[str],
    managed_collection: str,
    created_collection_id: str | None,
    added_additional_ids: Sequence[str],
    added_ingredients: bool,
    added_calendar: bool,
    added_managed: bool,
) -> list[str]:
    cleanup_errors: list[str] = []

    if added_additional_ids:
        await _attempt(
            "cleanup_additional_items",
            cleanup_errors,
            cookidoo.remove_additional_items(list(added_additional_ids)),
        )
    if added_ingredients:
        await _attempt(
            "cleanup_ingredients",
            cleanup_errors,
            cookidoo.remove_ingredient_items_for_recipes(list(recipe_ids)),
        )
    if added_calendar:
        for recipe_id in recipe_ids:
            await _attempt(
                f"cleanup_calendar_{recipe_id}",
                cleanup_errors,
                cookidoo.remove_recipe_from_calendar(date.today(), recipe_id),
            )
    if added_managed:
        await _attempt(
            "cleanup_managed_collection",
            cleanup_errors,
            cookidoo.remove_managed_collection(managed_collection),
        )
    if created_collection_id:
        await _attempt(
            "cleanup_custom_collection",
            cleanup_errors,
            cookidoo.remove_custom_collection(created_collection_id),
        )

    await _attempt(
        "cleanup_shopping_list_clear",
        cleanup_errors,
        cookidoo.clear_shopping_list(),
    )
    return cleanup_errors


async def _attempt(
    label: str,
    cleanup_errors: list[str],
    awaitable: object,
) -> None:
    try:
        await awaitable  # type: ignore[misc]
    except Exception as exc:
        cleanup_errors.append(f"{label}:{type(exc).__name__}:{exc}")
    else:
        print(f"{label}=ok")


if __name__ == "__main__":
    asyncio.run(main())
