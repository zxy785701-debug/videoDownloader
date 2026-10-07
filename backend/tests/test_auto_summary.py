"""Automatic continuation tests: no network, paid model, or personal database."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import subtitle_service, summary_service
from app.analysis_errors import AnalysisError
from app.analysis_jobs import AnalysisEngine
from test_learning import api, content, engine, finish, ready_record, store, transcript_result

URL = 'https://www.youtube.com/watch?v=abcdefghijk'


def wait_until(predicate):
    for _ in range(300):
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Automatic continuation did not settle')


@pytest.fixture
def fake_services(monkeypatch):
    calls = []
    monkeypatch.setattr(subtitle_service, 'extract_transcript', lambda *a, **k: transcript_result())
    def generate(*args, **kwargs):
        calls.append(args[0]['id'])
        return content()
    monkeypatch.setattr(summary_service, 'generate_summary', generate)
    return calls


def test_legacy_create_remains_caption_only(api, engine, fake_services):
    response = api.post('/api/v1/analyses', json={'url': URL, 'language': 'auto'})
    assert response.status_code == 202
    finish(engine, response.json()['job_id'])
    assert not fake_services
    assert engine.store.get(response.json()['id'])['summary_status'] == 'idle'


def test_auto_create_and_reparse_make_one_streaming_summary(api, engine, fake_services):
    result = api.post('/api/v1/analyses', json={'url': URL, 'auto_summary': True}).json()
    wait_until(lambda: engine.store.get(result['id'])['summary_status'] == 'ready')
    for _ in range(3):
        assert api.post('/api/v1/analyses', json={'url': URL, 'auto_summary': True}).json()['id'] == result['id']
    assert fake_services == [result['id']]
    assert engine.store.summary(result['id'])
    assert api.get('/api/v1/ai/config').json()['auto_summary_version'] == 1


def test_continuation_is_streaming_and_does_not_wait_in_worker(store, monkeypatch, fake_services):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake')
    single = AnalysisEngine(store, workers=1)
    observed = []
    original = single.start_summary
    def start(*args, **kwargs):
        observed.append(kwargs.get('streaming'))
        return original(*args, **kwargs)
    monkeypatch.setattr(single, 'start_summary', start)
    try:
        result = single.start_transcript(URL, 'auto', True)
        wait_until(lambda: store.get(result['id'])['summary_status'] == 'ready')
        assert observed == [True]
    finally:
        single.close()


def test_concurrent_reparse_reuses_active_caption_and_summary(engine, monkeypatch, fake_services):
    release = threading.Event()
    def extract(*args, **kwargs):
        assert release.wait(3)
        return transcript_result()
    monkeypatch.setattr(subtitle_service, 'extract_transcript', extract)
    try:
        with ThreadPoolExecutor(max_workers=8) as clients:
            results = list(clients.map(lambda _: engine.start_transcript(URL, 'auto', True), range(8)))
        assert len({result['id'] for result in results}) == 1
        assert len({result['job_id'] for result in results}) == 1
    finally:
        release.set()
    wait_until(lambda: engine.store.get(results[0]['id'])['summary_status'] == 'ready')
    assert len(fake_services) == 1


def test_opt_in_while_caption_in_progress(engine, monkeypatch, fake_services):
    release = threading.Event()
    monkeypatch.setattr(subtitle_service, 'extract_transcript', lambda *a, **k: (release.wait(3), transcript_result())[1])
    first = engine.start_transcript(URL, 'auto')
    try:
        second = engine.start_transcript(URL, 'auto', True)
        assert first['job_id'] == second['job_id']
        assert engine.store.active_job(first['id'], 'auto_summary')
    finally:
        release.set()
    wait_until(lambda: engine.store.get(first['id'])['summary_status'] == 'ready')
    assert len(fake_services) == 1


@pytest.mark.parametrize('code', ['NO_CAPTIONS', 'ACCESS_DENIED', 'VIDEO_TOO_LONG'])
def test_failed_caption_never_calls_model_or_auto_retries(engine, monkeypatch, fake_services, code):
    extracts = []
    def fail(*args, **kwargs):
        extracts.append(1)
        raise AnalysisError(code, '模拟字幕不可用')
    monkeypatch.setattr(subtitle_service, 'extract_transcript', fail)
    first = engine.start_transcript(URL, 'auto', True)
    finish(engine, first['job_id'])
    wait_until(lambda: not engine.store.active_job(first['id'], 'auto_summary'))
    assert engine.start_transcript(URL, 'auto', True)['job_id'] is None
    assert len(extracts) == 1 and not fake_services


def test_auto_without_key_keeps_caption_and_requires_manual_retry(engine, monkeypatch, fake_services):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    result = engine.start_transcript(URL, 'auto', True)
    wait_until(lambda: engine.store.get(result['id'])['summary_status'] == 'failed')
    assert engine.store.get(result['id'])['subtitle_status'] == 'ready'
    assert not fake_services
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'fake')
    engine.start_transcript(URL, 'auto', True)
    assert not fake_services
    summary = engine.start_summary(result['id'], streaming=True)
    finish(engine, summary['job_id'])
    assert len(fake_services) == 1


def test_saved_summary_reused_after_model_change_and_without_key(engine, monkeypatch, fake_services):
    record = ready_record(engine.store)
    engine.store.save_summary(record['id'], 'saved', 'old-fingerprint', content(), 'old-model', 'old-prompt')
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setenv('DEEPSEEK_MODEL', 'different-model')
    result = engine.start_transcript(URL, 'auto', True)
    assert result['cached']
    assert engine.store.summary(record['id'])['id'] == 'saved'
    assert not fake_services


@pytest.mark.parametrize('status', ['failed', 'interrupted'])
def test_failed_summary_does_not_restart_on_parse(engine, fake_services, status):
    record = ready_record(engine.store)
    engine.store.update(record['id'], summary_status=status)
    engine.start_transcript(URL, 'auto', True)
    assert not fake_services
    assert engine.store.get(record['id'])['summary_status'] == status


def test_language_switch_without_auto_does_not_generate(engine, fake_services):
    result = engine.start_transcript(URL, 'en', False)
    finish(engine, result['job_id'])
    assert not fake_services


def test_restart_recovers_pending_intent_without_calling_model(store, fake_services):
    ready_record(store)
    store.new_job('pending-auto', 'record-1', 'auto_summary', '等待字幕')
    restarted = AnalysisEngine(store)
    try:
        assert store.job('pending-auto')['status'] == 'interrupted'
        restarted.start_transcript(URL, 'auto', True)
        assert not fake_services
    finally:
        restarted.close()


def test_deleted_record_cannot_be_resurrected_by_continuation(engine, monkeypatch, fake_services):
    release = threading.Event()
    monkeypatch.setattr(subtitle_service, 'extract_transcript', lambda *a, **k: (release.wait(3), transcript_result())[1])
    result = engine.start_transcript(URL, 'auto', True)
    engine.delete(result['id'])
    release.set()
    wait_until(lambda: not engine.futures)
    assert not fake_services
    with pytest.raises(AnalysisError):
        engine.store.get(result['id'])


def test_queue_full_preserves_caption_and_manual_retry(engine, fake_services):
    record = ready_record(engine.store)
    reserved = 0
    while engine.slots.acquire(blocking=False):
        reserved += 1
    try:
        engine.start_transcript(URL, 'auto', True)
        assert engine.store.get(record['id'])['subtitle_status'] == 'ready'
        assert engine.store.get(record['id'])['summary_status'] == 'failed'
        intent = next(job for job in engine.store.latest_jobs(record['id']) if job['kind'] == 'auto_summary')
        assert intent['error_code'] == 'QUEUE_FULL'
        assert not fake_services
    finally:
        for _ in range(reserved):
            engine.slots.release()
    engine.start_transcript(URL, 'auto', True)
    assert not fake_services
    result = engine.start_summary(record['id'], streaming=True)
    finish(engine, result['job_id'])
    assert len(fake_services) == 1


def test_auto_reuses_an_active_manual_summary(engine, monkeypatch, fake_services):
    record = ready_record(engine.store)
    release = threading.Event()
    def generate(*args, **kwargs):
        fake_services.append(record['id'])
        assert release.wait(3)
        return content()
    monkeypatch.setattr(summary_service, 'generate_summary', generate)
    original = engine.start_summary(record['id'], streaming=True)
    try:
        engine.start_transcript(URL, 'auto', True)
        assert engine.store.active_job(record['id'], 'summary')['id'] == original['job_id']
    finally:
        release.set()
    finish(engine, original['job_id'])
    assert len(fake_services) == 1
