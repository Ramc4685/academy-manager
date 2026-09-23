"""The anonymous public page can never carry private data (Lane B2).

Two passes, both required by the public tenant page brief (section 5,
"never on the public surface"):

1. **Static.** Every pydantic model the ``interfaces/public`` persona can
   serialise is walked recursively (nested models, lists, unions); a field
   whose name says email, phone, an internal id (academy, session, program,
   coach, student, parent, user), notes, capacity or enrolled counts fails
   the build. Every route in the package must declare a response model from
   the allow-listed set, so a new route cannot bypass the walk.
2. **Behavioural.** A seeded academy with private values planted everywhere
   (contact details, coach email, student and parent ids, notes, group
   links, an unpublished class, another academy's class) is fetched through
   the real route, and none of those values may appear in the raw response.
"""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import re
import types
import typing
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

import backend.v2.interfaces.public as public_pkg
from backend.v2.interfaces.public.dtos import PUBLIC_RESPONSE_MODELS
from backend.v2.tests.fixtures.public_page import RIVERSIDE_HOST, SECRETS, build_app, seed

#: Substrings no public field name may contain.
BANNED_FIELD_FRAGMENTS = (
    "email",
    "phone",
    "academy_id",
    "session_id",
    "program_id",
    "coach_id",
    "student",
    "parent",
    "user_id",
    "uid",
    "note",
    "capacity",
    "enrolled",
    "occupied",
    "whatsapp",
    "parking",
    "stripe",
    "internal",
    "policy",
    "status_reason",
    "plan",
)
#: The deliberately allowed public identifiers (opaque digests).
ALLOWED_FIELDS = {"public_id"}


def _models_in(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for arg in typing.get_args(annotation):
        found.extend(_models_in(arg))
    if isinstance(annotation, types.UnionType):
        for arg in annotation.__args__:
            found.extend(_models_in(arg))
    return found


def _walk(model: type[BaseModel], path: str, seen: set[type[BaseModel]]) -> list[str]:
    if model in seen:
        return []
    seen.add(model)
    fields: list[str] = []
    for name, info in model.model_fields.items():
        fields.append(f"{path}.{name}")
        for nested in _models_in(info.annotation):
            fields.extend(_walk(nested, f"{path}.{name}", seen))
    return fields


def _public_modules() -> list[types.ModuleType]:
    modules = [public_pkg]
    for info in pkgutil.walk_packages(public_pkg.__path__, public_pkg.__name__ + "."):
        modules.append(importlib.import_module(info.name))
    return modules


def _all_public_field_paths() -> list[str]:
    seen: set[type[BaseModel]] = set()
    paths: list[str] = []
    for model in PUBLIC_RESPONSE_MODELS:
        paths.extend(_walk(model, model.__name__, seen))
    return paths


def test_walk_actually_reaches_nested_class_fields() -> None:
    paths = _all_public_field_paths()
    assert "PublicAcademyPageDto.programs.classes.seats.band" in paths
    assert "PublicAcademyPageDto.academy.venue.address" in paths


def test_no_public_dto_field_names_private_data() -> None:
    offenders = []
    for path in _all_public_field_paths():
        leaf = path.rsplit(".", 1)[-1].lower()
        if leaf in ALLOWED_FIELDS:
            continue
        hits = [frag for frag in BANNED_FIELD_FRAGMENTS if frag in leaf]
        if hits or re.fullmatch(r"(.*_)?id", leaf):
            offenders.append(f"{path} ({', '.join(hits) or 'internal id'})")
    assert not offenders, "public page DTO carries private fields:\n" + "\n".join(offenders)


def test_every_pydantic_model_in_the_public_package_is_walked() -> None:
    walked: set[type[BaseModel]] = set()
    for model in PUBLIC_RESPONSE_MODELS:
        _walk(model, model.__name__, walked)
    defined = {
        obj
        for module in _public_modules()
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__.startswith(public_pkg.__name__)
    }
    request_models = {m for m in defined if m.__name__.endswith("Request")}
    unwalked = sorted(m.__name__ for m in defined - walked - request_models)
    assert not unwalked, f"public DTOs outside PUBLIC_RESPONSE_MODELS: {unwalked}"


def test_every_public_route_declares_an_allow_listed_response_model() -> None:
    routes = [
        route
        for module in _public_modules()
        for route in getattr(getattr(module, "router", None), "routes", [])
        if isinstance(route, APIRoute)
    ]
    assert routes, "no public routes found"
    allowed = set(PUBLIC_RESPONSE_MODELS)
    for route in routes:
        declared = set(_models_in(route.response_model))
        assert declared, f"{route.path} has no response_model"
        assert declared <= allowed, f"{route.path} returns {declared - allowed}"


def test_seeded_private_values_never_reach_the_response() -> None:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    db = mongomock_motor.AsyncMongoMockClient()["public-page-leak"]
    asyncio.run(seed(db))
    response = TestClient(build_app(db)).get(
        "/api/v2/public/academy", headers={"host": RIVERSIDE_HOST}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "published"
    raw = response.text
    leaked = {key: value for key, value in SECRETS.items() if value in raw}
    assert not leaked, f"private values in the public page response: {leaked}"
    # Seat counts: capacity 10 and 2 must not appear as numbers either.
    body = response.json()
    for cls in [c for p in body["programs"] for c in p["classes"]] + body["ungrouped_classes"]:
        assert set(cls["seats"]) == {"band", "seats_left"}
        assert cls["seats"]["seats_left"] is None or cls["seats"]["seats_left"] <= 3
