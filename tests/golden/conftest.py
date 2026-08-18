"""Shared fixtures for the golden suite.

Layer A hermeticity is enforced, not assumed: every test in this directory
that is not marked ``live`` runs with socket connections disabled, so a stage
that accidentally reaches a real vendor (a fixture typo, a new code path that
bypasses the replayed boundary) fails loudly instead of producing a golden
that silently depends on the network.
"""
import socket

import pytest

from tests.golden import harness
from tests.golden.clock import frozen_clock


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        yield
        return

    def _blocked(self, *args, **kwargs):
        raise RuntimeError(
            "Network access attempted from a hermetic golden test. "
            "Layer A must replay fixtures from disk only; live vendor calls "
            "belong in test_vendor_contract.py (-m live)."
        )

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    yield


@pytest.fixture
def frozen():
    """The frozen scoring clock, for tests that score rows directly (the
    harness freezes internally for cascade replays)."""
    with frozen_clock() as frozen_date:
        yield frozen_date


@pytest.fixture(scope="session")
def corpus():
    return harness.load_corpus()


@pytest.fixture(scope="session")
def golden_scores():
    import json
    with harness.EXPECTED_SCORES.open() as f:
        return json.load(f)
