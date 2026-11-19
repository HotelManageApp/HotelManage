"""Every /api/v1 endpoint must be authenticated, unless it is explicitly public (SPEC-staff-auth).

An endpoint counts as protected when its dependency tree contains a staff or guest auth
dependency. Adding an endpoint without one makes this test fail until it is either protected or
added to PUBLIC_ENDPOINTS with a reason.
"""

from collections.abc import Callable, Iterator
from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from app.main import API_V1_PREFIX, create_app
from app.modules.staff_auth.deps import current_staff
from tests.conftest import make_settings

# (method, path): reason it needs no Authorization header.
PUBLIC_ENDPOINTS: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/staff/auth/login"): "credentials in body; rate limited",
    ("POST", "/api/v1/staff/auth/refresh"): "HttpOnly refresh cookie + Origin check",
    ("POST", "/api/v1/staff/auth/logout"): "HttpOnly refresh cookie + Origin check",
}

# Guest auth (`current_stay`) is added here when stay-access lands (T15).
AUTH_DEPENDENCIES: set[Callable[..., Any]] = {current_staff}


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for sub in dependant.dependencies:
        if sub.call is not None:
            yield sub.call
        yield from _calls(sub)


def _api_routes(app: FastAPI | None = None) -> list[tuple[str, str, APIRoute]]:
    """Every (method, path, route) under /api/v1, including routes of included routers.

    FastAPI >= 0.16x keeps included routers as nested objects, so `app.routes` alone is not
    flat; `iter_route_contexts` resolves the effective path and route of each endpoint.
    """
    app = app or create_app(make_settings())
    found = []
    for context in iter_route_contexts(app.routes):
        route = context.route
        if isinstance(route, APIRoute) and context.path.startswith(API_V1_PREFIX):
            found.extend((method, context.path, route) for method in sorted(context.methods))
    return found


def test_scan_sees_the_api() -> None:
    """Guards against the scan silently finding nothing (it would then pass vacuously)."""
    paths = {path for _, path, _ in _api_routes()}
    assert "/api/v1/staff/me" in paths
    assert "/api/v1/staff/auth/login" in paths


def test_every_api_endpoint_is_protected_or_explicitly_public() -> None:
    unprotected = [
        f"{method} {path}"
        for method, path, route in _api_routes()
        if (method, path) not in PUBLIC_ENDPOINTS
        and not AUTH_DEPENDENCIES.intersection(_calls(route.dependant))
    ]
    assert unprotected == [], f"endpoints without auth dependency: {unprotected}"


def test_public_list_has_no_stale_entries() -> None:
    existing = {(method, path) for method, path, _ in _api_routes()}
    assert set(PUBLIC_ENDPOINTS) <= existing


def test_guard_detects_an_unprotected_endpoint() -> None:
    """Self-check: the scan really fails for an endpoint without auth."""
    app = create_app(make_settings())

    @app.get(f"{API_V1_PREFIX}/oops")
    async def oops() -> dict[str, str]:
        return {}

    oops_route = next(route for _, path, route in _api_routes(app) if path.endswith("/oops"))
    assert not AUTH_DEPENDENCIES.intersection(_calls(oops_route.dependant))
    me_route = next(route for _, path, route in _api_routes(app) if path == "/api/v1/staff/me")
    assert AUTH_DEPENDENCIES.intersection(_calls(me_route.dependant))
