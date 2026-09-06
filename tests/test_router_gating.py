"""Which routers sit behind which module gate.

Reads the wiring off the app itself rather than re-listing it, so the assertions
stay true when a router moves. The gap this exists to prevent is the one phase 7
of the maps remodel closed: `/api/map/*` was gated on the `map` module while
`/api/geo/*` — heatmap, clusters, events, prospecting, and the service-area
write the whole premium surface is built on — was not, so an account that could
not see the map could still call everything behind it.

The complementary rule matters just as much: public, token-addressed routers
(the pay page, public quote/invoice, Stripe and Twilio webhooks, public intake)
must stay ungated, because they have to work with no login and no plan at all.
"""
import os

import pytest

# Importing the app evaluates its security config. Nothing here signs or checks
# a token — this only inspects the route table — so a throwaway secret keeps the
# module importable without a configured environment.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

from api.main import app  # noqa: E402


def _module_gates(path_fragment: str) -> set[str]:
    """Module keys guarding the router that serves `path_fragment`.

    This FastAPI version keeps an included router as a `_IncludedRouter` wrapper
    holding the original router plus the `include_router(...)` arguments, rather
    than flattening its routes onto the app. So the gate is read from the
    include context, and the module name out of the closure `require_module`
    returned — which is what actually runs per request.
    """
    gates: set[str] = set()
    for entry in app.routes:
        ctx = getattr(entry, "include_context", None)
        router = getattr(entry, "original_router", None)
        if ctx is None or router is None:
            continue
        prefix = getattr(ctx, "prefix", "") or ""
        if not any(f"{prefix}{getattr(r, 'path', '')}".startswith(path_fragment)
                   for r in router.routes):
            continue
        for dep in getattr(ctx, "dependencies", None) or []:
            for cell in getattr(dep.dependency, "__closure__", None) or ():
                if isinstance(cell.cell_contents, str):
                    gates.add(cell.cell_contents)
    return gates


def _routed(path_fragment: str) -> bool:
    """Whether any router actually serves this prefix (guards the skips below)."""
    for entry in app.routes:
        ctx = getattr(entry, "include_context", None)
        router = getattr(entry, "original_router", None)
        if ctx is None or router is None:
            continue
        prefix = getattr(ctx, "prefix", "") or ""
        if any(f"{prefix}{getattr(r, 'path', '')}".startswith(path_fragment)
               for r in router.routes):
            return True
    return False


class TestModuleGating:
    def test_the_probe_can_see_a_known_gate(self):
        # If the introspection above ever stops matching FastAPI's internals it
        # would return an empty set for everything, and every assertion here
        # would pass vacuously. This is the canary.
        assert _module_gates("/api/map/") == {"map"}

    def test_geo_is_gated_with_the_map(self):
        # /geo/* is the map's own backend — heatmap, clusters, events,
        # prospecting, the service-area write. Gating the map UI while leaving
        # this open is premium UI on an open door.
        assert "map" in _module_gates("/api/geo/")

    @pytest.mark.parametrize("prefix", [
        "/api/pay/",       # public pay page
        "/api/public/",    # public quote/invoice views and intake
        "/api/webhooks/",  # Stripe and Twilio callbacks
    ])
    def test_public_surfaces_stay_ungated(self, prefix):
        # Addressed by token, not by session: a plan check here would break
        # payment and inbound messaging for every tenant.
        if not _routed(prefix):
            pytest.skip(f"no routes under {prefix}")
        assert _module_gates(prefix) == set()


class TestAdminGuard:
    def test_every_router_serving_admin_is_platform_admin_guarded(self):
        # Three routers serve /api/admin now (admin, admin_usage, admin_data) and
        # each is included with its own guard line in api/main.py. This reads
        # the guard off the include context the same way _module_gates does, so
        # a fourth router cannot ship without it.
        from api.deps import require_platform_admin
        guarded = 0
        for entry in app.routes:
            ctx = getattr(entry, "include_context", None)
            router = getattr(entry, "original_router", None)
            if ctx is None or router is None:
                continue
            prefix = getattr(ctx, "prefix", "") or ""
            paths = [f"{prefix}{getattr(r, 'path', '')}" for r in router.routes]
            if not any(p.startswith("/api/admin") for p in paths):
                continue
            deps = getattr(ctx, "dependencies", None) or []
            assert any(getattr(d, "dependency", None) is require_platform_admin for d in deps), \
                f"unguarded admin router: {paths[:3]}"
            guarded += 1
        # If the probe stops seeing include contexts the loop above passes
        # vacuously, so the count is the canary.
        assert guarded >= 3
