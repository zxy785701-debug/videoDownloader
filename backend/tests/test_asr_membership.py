"""Mock ASR and isolated Mock billing; no cloud calls, real users or databases."""
import hashlib
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app import subtitle_service
from app.analysis_errors import AnalysisError
from app.asr import settings
from app.asr import store as asr_store
from app.asr.config import ASRUser, get_config
from test_asr import URL, service
from test_learning import api, engine, finish, store, transcript_result
from test_membership import billing, bridge, paid


def transcribe(service, number, user):
    return service.transcribe(URL, "unit-" + str(number), user, lambda: None, lambda _: None)


def membership_stub(me):
    return SimpleNamespace(me=me, recover=lambda _: None)


def test_independent_limits_support_file_and_process_config(tmp_path, monkeypatch):
    config = get_config(tmp_path)
    assert config.per_user_hour == 3 and config.member_per_user_hour == 10
    fingerprint = config.fingerprint("auto")
    path = tmp_path / ".env"
    path.write_text("ASR_USER_HOURLY_LIMIT=4\nASR_MEMBER_HOURLY_LIMIT=12\n", encoding="utf-8")
    monkeypatch.setattr(settings, "_LOCAL_CONFIG", settings.read_local_settings(path))
    config = get_config(tmp_path)
    assert config.per_user_hour == 4 and config.member_per_user_hour == 12
    monkeypatch.setenv("ASR_MEMBER_HOURLY_LIMIT", "15")
    assert get_config(tmp_path).member_per_user_hour == 15
    assert get_config(tmp_path).fingerprint("auto") == fingerprint


@pytest.mark.parametrize("expiry,expected", [
    (lambda: time.time() + 3600, True), (lambda: time.time() - 1, False),
    (lambda: None, False), (lambda: True, False), (lambda: "9999999999", False),
    (lambda: float("nan"), False), (lambda: float("inf"), False),
])
def test_tier_uses_only_verified_unexpired_membership(engine, expiry, expected):
    sessions = []

    def me(session):
        sessions.append(session)
        return {"email": " Buyer@Example.COM ", "quota": {"member_expires": expiry()}}

    engine.membership = membership_stub(me)
    identity = engine._asr_user("peer", "server-session")
    assert identity == ASRUser(hashlib.sha256(b"account:buyer@example.com").hexdigest(), expected)
    assert sessions == ["server-session"]


def test_invalid_or_unavailable_session_never_gets_member_limit(engine):
    def unavailable(session):
        raise AnalysisError("MEMBERSHIP_UNAVAILABLE", "mock service unavailable", 503)

    engine.membership = membership_stub(unavailable)
    assert engine._asr_user("peer", "forged-cookie") == "peer"
    assert engine._asr_user("peer", None) == "peer"
    engine.membership = membership_stub(lambda _: {"email": " ", "quota": {"member_expires": time.time() + 3600}})
    assert engine._asr_user("peer", "session") == "peer"


def test_members_receive_ten_and_ordinary_accounts_three_with_separate_counters(service):
    member = ASRUser("member-account", True)
    for number in range(10):
        assert transcribe(service, number, member)["cues"]
    assert transcribe(service, 0, member)["cues"]  # Cache still works at the cap.
    with pytest.raises(AnalysisError) as error:
        transcribe(service, 10, member)
    assert error.value.code == "ASR_USER_RATE_LIMIT" and "会员" in error.value.message
    assert "60 分钟 10 次" in error.value.message
    for number in range(11, 14):
        assert transcribe(service, number, ASRUser("ordinary-account"))["cues"]
    with pytest.raises(AnalysisError) as error:
        transcribe(service, 14, ASRUser("ordinary-account"))
    assert "60 分钟 3 次" in error.value.message
    assert len(service.provider.submits) == 13


def test_upgrading_keeps_history_and_raising_limit_does_not_reset_ledger(service):
    for number in range(3):
        transcribe(service, number, ASRUser("same-account"))
    with pytest.raises(AnalysisError):
        transcribe(service, 3, ASRUser("same-account"))
    for number in range(3, 10):
        transcribe(service, number, ASRUser("same-account", True))
    with pytest.raises(AnalysisError):
        transcribe(service, 10, ASRUser("same-account", True))
    assert len(service.provider.submits) == service.store.usage_report()[0]["accepted_tasks"] == 10
    service.config = replace(service.config, member_per_user_hour=11)
    transcribe(service, 10, ASRUser("same-account", True))
    assert service.store.usage_report()[0]["accepted_tasks"] == 11


def test_member_window_expires_without_erasing_cached_transcripts_or_usage(service, monkeypatch):
    started = time.time()
    monkeypatch.setattr(asr_store.time, "time", lambda: started)
    user = ASRUser("member", True)
    for number in range(10):
        transcribe(service, number, user)
    monkeypatch.setattr(asr_store.time, "time", lambda: started + 3599)
    with pytest.raises(AnalysisError) as error:
        transcribe(service, 10, user)
    assert error.value.code == "ASR_USER_RATE_LIMIT"
    monkeypatch.setattr(asr_store.time, "time", lambda: started + 3601)
    assert transcribe(service, 10, user)["cues"]
    assert transcribe(service, 0, user)["cues"]
    assert len(service.provider.submits) == service.store.usage_report()[0]["accepted_tasks"] == 11


def test_member_limit_does_not_bypass_budget_or_unknown_submission(service):
    service.config = replace(service.config, budget=0)
    with pytest.raises(AnalysisError) as error:
        transcribe(service, 0, ASRUser("member", True))
    assert error.value.code == "ASR_BUDGET_EXCEEDED" and not service.provider.submits
    service.config = replace(service.config, budget=10)
    calls = []

    def unknown(*args):
        calls.append(1)
        raise AnalysisError("ASR_SUBMISSION_UNKNOWN", "mock unknown result")

    service.provider.submit = unknown
    for _ in range(2):
        with pytest.raises(AnalysisError) as error:
            transcribe(service, 0, ASRUser("member", True))
        assert error.value.code == "ASR_SUBMISSION_UNKNOWN"
    assert len(calls) == 1


def test_billing_grant_and_revocation_select_tier_without_new_summary_charge(engine, billing, bridge):
    remote, user, _, _ = billing
    local, session, _ = bridge
    engine.membership = local
    free_identity = engine._asr_user("peer", session)
    assert isinstance(free_identity, ASRUser) and not free_identity.member
    paid(remote, user)  # Isolated Mock payment; never Stripe network.
    assert engine._asr_user("peer", session) == ASRUser(free_identity.key, True)
    with remote.store.connection(write=True) as db:
        db.execute("UPDATE grants SET revoked=1 WHERE user_id=?", (user["id"],))
    assert engine._asr_user("peer", session) == free_identity
    assert local.me(session)["quota"]["used"] == 0


def test_client_member_fields_cannot_raise_asr_limit(api, engine, service, monkeypatch):
    engine.asr = service
    engine.membership = membership_stub(lambda _: {"email": "free@example.test", "quota": {"member_expires": None}})
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *a, **kw:
        (_ for _ in ()).throw(AnalysisError("NO_CAPTIONS", "mock no captions")))
    api.cookies.set("saveany_account", "server-local-session")
    for number in range(4):
        created = api.post("/api/v1/analyses", json={"url": URL, "language": "unit-" + str(number),
            "member": True, "asr_hourly_limit": 100, "member_expires": 9999999999}).json()
        job = finish(engine, created["job_id"])
        assert job["status"] == ("ready" if number < 3 else "failed")
    assert job["error_code"] == "ASR_USER_RATE_LIMIT"
    assert len(service.provider.submits) == 3


def test_native_subtitles_do_not_query_membership_or_use_asr(engine, service, monkeypatch):
    engine.asr = service
    engine.membership = membership_stub(lambda _: pytest.fail("No member lookup for native captions"))
    monkeypatch.setattr(subtitle_service, "extract_transcript", lambda *a, **kw: transcript_result())
    created = engine.start_transcript(URL, "auto", member_session="session")
    assert finish(engine, created["job_id"])["status"] == "ready"
    assert service.provider.submits == service.audio_calls == []
