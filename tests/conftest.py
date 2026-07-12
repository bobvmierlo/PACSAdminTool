"""Shared pytest fixtures/hooks for the test suite."""

import pytest


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """Clear login brute-force state between tests.

    The limiter tracks failures per client IP, and every test-client request
    comes from the same IP — without this, failed-login tests would lock each
    other out. The route module may hold a reference to an older instance of
    web.auth than sys.modules does (the web-API fixtures reload web.auth), so
    clear the dict reachable through the route's own function globals as well.
    """
    stores = []
    try:
        import web.auth as auth_mod
        stores.append(auth_mod._failed_logins)
    except Exception:
        pass
    try:
        from web.routes import auth_routes
        stores.append(auth_routes.record_login_failure.__globals__["_failed_logins"])
    except Exception:
        pass
    for store in stores:
        store.clear()
    yield
    for store in stores:
        store.clear()
