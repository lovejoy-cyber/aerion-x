"""Real tests for the optional site-wide passphrase gate — disabled by
default (verified: the whole rest of the suite runs with it off), and when
enabled, actually blocks unauthenticated requests and admits correct ones.
"""
from fastapi.testclient import TestClient

import backend.main as main_module


def test_gate_disabled_by_default_allows_everything():
    assert main_module._SITE_PASSPHRASE == ""  # not set in the test environment
    with TestClient(main_module.app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200


def test_gate_blocks_and_admits_with_correct_passphrase():
    original = main_module._SITE_PASSPHRASE
    main_module._SITE_PASSPHRASE = "test-gate-secret"
    try:
        with TestClient(main_module.app) as client:
            # no cookie yet — blocked
            blocked = client.get("/events")
            assert blocked.status_code == 403

            # wrong passphrase — rejected, no cookie set
            wrong = client.post("/gate", json={"passphrase": "not-it"})
            assert wrong.status_code == 403

            # correct passphrase — cookie set, subsequent requests pass
            ok = client.post("/gate", json={"passphrase": "test-gate-secret"})
            assert ok.status_code == 200
            admitted = client.get("/events")
            assert admitted.status_code == 200
    finally:
        main_module._SITE_PASSPHRASE = original  # never leak this into other tests
