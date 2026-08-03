"""
Tests for the Meta Conversions API emitter (api/connectors/meta_capi.py) that run
without network or credentials — monkeypatching module-level config, mirroring
how test_stripe_client.py stubs STRIPE_* on its module.
"""
import hashlib

from api.connectors import meta_capi as mc


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def test_configured_gate(monkeypatch):
    monkeypatch.setattr(mc, "META_PIXEL_ID", "", raising=False)
    monkeypatch.setattr(mc, "META_CAPI_TOKEN", "", raising=False)
    assert mc.capi_configured() is False
    monkeypatch.setattr(mc, "META_PIXEL_ID", "123", raising=False)
    monkeypatch.setattr(mc, "META_CAPI_TOKEN", "tok", raising=False)
    assert mc.capi_configured() is True


def test_user_data_hashing_and_normalization():
    ud = mc.build_user_data(
        email="  Contractor@Example.COM ", phone="+1 (713) 555-0142",
        zip_code="77007-1234", external_id="Cust_9001",
    )
    assert ud["em"] == [_sha("contractor@example.com")]
    assert ud["ph"] == [_sha("17135550142")]      # digits only, keeps country code
    assert ud["zp"] == [_sha("77007")]            # first 5
    assert ud["external_id"] == [_sha("cust_9001")]


def test_raw_keys_not_hashed():
    ud = mc.build_user_data(email="a@b.com", fbp="fb.1.2.3", client_ip="203.0.113.7",
                            client_ua="UA/1.0")
    assert ud["fbp"] == "fb.1.2.3"
    assert ud["client_ip_address"] == "203.0.113.7"
    assert ud["client_user_agent"] == "UA/1.0"
    assert "em" in ud and ud["em"] != ["a@b.com"]  # email still hashed


def test_send_is_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(mc, "META_CAPI_TOKEN", "", raising=False)
    # Must return False and never attempt a network call.
    monkeypatch.setattr(mc.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network hit")))
    assert mc.send_event("Subscribe", {"em": ["x"]}, event_id="e1") is False


def test_send_skips_when_no_match_keys(monkeypatch):
    monkeypatch.setattr(mc, "META_PIXEL_ID", "123", raising=False)
    monkeypatch.setattr(mc, "META_CAPI_TOKEN", "tok", raising=False)
    monkeypatch.setattr(mc.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network hit")))
    assert mc.send_event("Subscribe", {}, event_id="e1") is False


def test_track_subscribe_builds_expected_payload(monkeypatch):
    monkeypatch.setattr(mc, "META_PIXEL_ID", "123", raising=False)
    monkeypatch.setattr(mc, "META_CAPI_TOKEN", "tok", raising=False)
    monkeypatch.setattr(mc, "META_TEST_EVENT_CODE", "TEST999", raising=False)
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"events_received": 1}'

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = __import__("json").loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)

    ok = mc.track_subscribe(email="a@b.com", value=249, event_id="sub_x", external_id="42")
    assert ok is True
    body = captured["body"]
    assert body["test_event_code"] == "TEST999"
    ev = body["data"][0]
    assert ev["event_name"] == "Subscribe"
    assert ev["event_id"] == "sub_x"
    assert ev["custom_data"]["value"] == 249.0
    assert ev["custom_data"]["currency"] == "USD"
    assert ev["user_data"]["em"] == [_sha("a@b.com")]
    assert ev["user_data"]["external_id"] == [_sha("42")]
    assert "123/events" in captured["url"]


def test_track_start_trial_builds_expected_payload(monkeypatch):
    monkeypatch.setattr(mc, "META_PIXEL_ID", "123", raising=False)
    monkeypatch.setattr(mc, "META_CAPI_TOKEN", "tok", raising=False)
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"events_received": 1}'

    def fake_urlopen(req, timeout=None):
        captured["body"] = __import__("json").loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)

    ok = mc.track_start_trial(
        email="a@b.com", external_id="42", event_id="trial_42",
        fbp="fb.1.2.3", fbc="fb.1.2.click", client_ip="203.0.113.7",
        client_ua="UA/1.0", event_source_url="https://axonhtx.com/signup",
    )
    assert ok is True
    ev = captured["body"]["data"][0]
    assert ev["event_name"] == "StartTrial"
    assert ev["event_id"] == "trial_42"                       # shared with browser Pixel for dedup
    assert ev["action_source"] == "website"
    assert ev["event_source_url"] == "https://axonhtx.com/signup"
    assert ev["user_data"]["em"] == [_sha("a@b.com")]
    assert ev["user_data"]["external_id"] == [_sha("42")]     # same key as Subscribe → links trial→paid
    assert ev["user_data"]["fbp"] == "fb.1.2.3"               # forwarded browser cookie, not hashed
    assert ev["user_data"]["fbc"] == "fb.1.2.click"
    assert ev["user_data"]["client_ip_address"] == "203.0.113.7"
