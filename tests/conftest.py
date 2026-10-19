"""Shared fixtures for the RTM & Quality Prediction research test suite.

Isolation guarantees (so the suite is safe to run during a live demo):
  * DATABASE_URL is pointed at a throwaway SQLite file BEFORE the app is
    imported, so tests never read or write the real Neon database.
  * Component 1 / Component 2 are replaced in-process by `FakeComponents`
    for the offline tests; their real implementations are never modified.
  * The live tests (tests/test_live_integration.py) only issue read-only GETs.
"""

import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="rtm-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'rtm_test.db')}"
os.environ["COVERAGE_ENABLED"] = "false"  # never clone/run real repositories from tests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

pytest_plugins = ["tests.reporting"]


class FakeComponents:
    """Controllable stand-ins for Component 1 / Component 2 API calls."""

    def __init__(self):
        self.requirements: list[dict] = []
        self.test_cases: list[dict] = []
        self.runs: list[dict] = []
        self.c1_down = False
        self.c2_down = False
        self.calls: list[tuple] = []


@pytest.fixture
def fake_components(monkeypatch):
    from app.integrations import component1, component2

    fake = FakeComponents()

    async def get_requirements_with_stories(iteration_id):
        fake.calls.append(("c1.requirements_with_stories", iteration_id))
        if fake.c1_down:
            raise component1.Component1Unavailable("Component 1 request failed (simulated outage)")
        return [dict(r) for r in fake.requirements]

    async def get_traceability_test_cases(project_id, iteration_id=None):
        fake.calls.append(("c2.traceability_test_cases", project_id, iteration_id))
        if fake.c2_down:
            raise component2.Component2Unavailable("Component 2 request failed (simulated outage)")
        return [dict(t) for t in fake.test_cases]

    async def get_test_runs(project_id, limit=20):
        if fake.c2_down:
            raise component2.Component2Unavailable("Component 2 request failed (simulated outage)")
        return list(fake.runs)

    monkeypatch.setattr(component1, "get_requirements_with_stories", get_requirements_with_stories)
    monkeypatch.setattr(component2, "get_traceability_test_cases", get_traceability_test_cases)
    monkeypatch.setattr(component2, "get_test_runs", get_test_runs)
    return fake


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app import models
    from app.database import SessionLocal
    from app.main import app

    with TestClient(app) as c:
        yield c
    db = SessionLocal()
    try:
        db.query(models.GeneratedGapTestCase).delete()
        db.query(models.CoverageReport).delete()
        db.commit()
    finally:
        db.close()
