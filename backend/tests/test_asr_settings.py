"""Mock-only configuration checks; all credentials are fabricated."""
import os
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.analysis_errors import AnalysisError
from app.asr import settings
from app.asr.config import get_config
from app.asr.providers import AliyunParaformer
from app.asr.storage import OSSStorage


@pytest.fixture(autouse=True)
def no_operator_settings(monkeypatch):
    for name in settings.NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def file_settings(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        'ASR_ENABLED=true\n'
        'DASHSCOPE_API_KEY="fake-file-api-key"\n'
        'ALIYUN_OSS_BUCKET=unit-env-bucket\n'
        'ALIYUN_OSS_ENDPOINT=https://oss-cn-beijing.aliyuncs.com\n'
        'ALIYUN_OSS_ACCESS_KEY_ID=fake-file-ak\n'
        'ALIYUN_OSS_ACCESS_KEY_SECRET=fake-file-sk\n'
        'ALIYUN_OSS_SECURITY_TOKEN=fake-file-token\n'
        'ASR_MONTHLY_BUDGET_CNY=8.5\n'
        'ASR_MAX_DURATION_SECONDS=1200\n', encoding="utf-8")
    values = settings.read_local_settings(path)
    monkeypatch.setattr(settings, "_LOCAL_CONFIG", values)
    return values


def test_file_credentials_do_not_populate_environment(file_settings, tmp_path):
    config = get_config(tmp_path)
    config.require()
    assert config.budget == 8.5 and config.max_duration == 1200
    assert all(name not in os.environ for name in settings.NAMES)
    assert not any(value in repr(config) for value in (
        "fake-file-api-key", "fake-file-ak", "fake-file-sk", "fake-file-token"))


def test_process_values_override_file_including_empty(file_settings, monkeypatch, tmp_path):
    monkeypatch.setenv("ASR_MONTHLY_BUDGET_CNY", "10")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-process-api-key")
    assert get_config(tmp_path).budget == 10
    assert settings.setting("DASHSCOPE_API_KEY") == "fake-process-api-key"
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    with pytest.raises(AnalysisError) as error:
        get_config(tmp_path).require()
    assert error.value.code == "ASR_NOT_CONFIGURED" and ".env" in str(error.value)
    monkeypatch.setenv("ASR_ENABLED", "false")
    assert not get_config(tmp_path).enabled


def test_file_loading_ignores_unrelated_settings_and_paid_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIT_INTERPOLATION", "expanded-value")
    path = tmp_path / ".env"
    path.write_text(
        'DASHSCOPE_API_KEY="literal-${UNIT_INTERPOLATION}-value"\n'
        'ASR_RUN_LIVE_TESTS=1\nASR_RUN_DOUYIN_E2E=1\n'
        'DEEPSEEK_API_KEY=not-an-asr-setting\n'
        'VITE_DASHSCOPE_API_KEY=never-export\nDOWNLOAD_FIREFOX_COOKIES=true\n'
        'ALLOWED_HOSTS=*\nASR_MODEL\n', encoding="utf-8-sig")
    assert settings.read_local_settings(path) == {
        "DASHSCOPE_API_KEY": "literal-${UNIT_INTERPOLATION}-value"}


@pytest.mark.parametrize("failure", [PermissionError, UnicodeDecodeError])
def test_unreadable_file_warning_does_not_disclose_content(tmp_path, monkeypatch, caplog, failure):
    path = tmp_path / ".env"
    path.touch()
    error = (PermissionError("fake-sensitive-path") if failure is PermissionError
             else UnicodeDecodeError("utf-8", b"fake-sensitive-content", 0, 1, "invalid"))

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(settings, "dotenv_values", fail)
    assert settings.read_local_settings(path) == {}
    assert failure.__name__ in caplog.text and "fake-sensitive" not in caplog.text


def test_missing_file_keeps_original_defaults(tmp_path):
    assert settings.read_local_settings(tmp_path / "missing.env") == {}
    config = get_config(tmp_path)
    assert config.concurrency == config.threads == 1
    assert config.max_duration == 3600 and config.budget == 10


def test_credentials_do_not_change_recognition_cache_identity(file_settings, monkeypatch, tmp_path):
    fingerprint = get_config(tmp_path).fingerprint("zh")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "another-fake-key")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "another-fake-secret")
    assert get_config(tmp_path).fingerprint("zh") == fingerprint


def test_file_key_used_for_mocked_provider_request(file_settings, tmp_path, monkeypatch, caplog):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"output": {"task_id": "mock-env-task"}})

    real_client = httpx.Client
    monkeypatch.setattr("app.asr.providers.httpx.Client", lambda **kwargs:
        real_client(transport=httpx.MockTransport(respond), **kwargs))
    result = AliyunParaformer(get_config(tmp_path)).submit(
        "https://unit-env-bucket.oss-cn-beijing.aliyuncs.com/asr/mock.flac", "auto")
    assert result == "mock-env-task" and len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer fake-file-api-key"
    assert requests[0].url.host == "dashscope.aliyuncs.com"
    assert "fake-file-api-key" not in caplog.text


def test_empty_process_key_prevents_provider_network(file_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")

    def forbidden(*args, **kwargs):
        pytest.fail("A missing key must never start a network client")

    monkeypatch.setattr("app.asr.providers.httpx.Client", forbidden)
    with pytest.raises(AnalysisError) as error:
        AliyunParaformer(get_config(tmp_path)).submit("https://example.com/audio", "auto")
    assert error.value.code == "ASR_NOT_CONFIGURED"


def test_file_oss_credentials_sign_private_upload_without_network(file_settings, tmp_path, monkeypatch):
    oss2 = pytest.importorskip("oss2")
    seen = []
    monkeypatch.setattr(oss2.Bucket, "get_bucket_acl", lambda _: SimpleNamespace(acl="private"))
    monkeypatch.setattr(oss2.Bucket, "put_object_from_file", lambda self, *args, **kwargs: seen.append(kwargs))
    source = tmp_path / "audio.flac"
    source.write_bytes(b"fake-audio")
    storage = OSSStorage(get_config(tmp_path))
    url = urlsplit(storage.upload(source, "asr/" + "a" * 32 + ".flac", lambda: None))
    query = parse_qs(url.query)
    assert url.scheme == "https" and url.hostname == "unit-env-bucket.oss-cn-beijing.aliyuncs.com"
    assert query["x-oss-security-token"] == ["fake-file-token"]
    assert query["x-oss-credential"][0].startswith("fake-file-ak/")
    assert seen[0]["headers"]["x-oss-object-acl"] == "private"


def test_empty_fixed_process_keys_select_mocked_role_chain(file_settings, tmp_path, monkeypatch):
    oss2 = pytest.importorskip("oss2")
    from alibabacloud_credentials.client import Client
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "")
    monkeypatch.setattr(oss2.Bucket, "get_bucket_acl", lambda _: SimpleNamespace(acl="private"))
    monkeypatch.setattr(Client, "__init__", lambda self: None)
    monkeypatch.setattr(Client, "get_credential", lambda _: SimpleNamespace(
        access_key_id="fake-role-ak", access_key_secret="fake-role-sk", security_token="fake-role-token"))
    bucket = OSSStorage(get_config(tmp_path)).connect()
    query = parse_qs(urlsplit(bucket.sign_url("GET", "asr/" + "a" * 32 + ".flac", 60)).query)
    assert query["x-oss-credential"][0].startswith("fake-role-ak/")
    assert query["x-oss-security-token"] == ["fake-role-token"]


def test_presence_preflight_reports_names_only(file_settings, monkeypatch, capsys):
    assert settings.main() == 0
    output = capsys.readouterr().out
    assert "not cloud-validated" in output and "fake-file" not in output
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "")
    assert settings.main() == 1
    output = capsys.readouterr().out
    assert "DASHSCOPE_API_KEY" in output and "ALIYUN_OSS_ACCESS_KEY_SECRET" in output
    assert "fake-file" not in output


def test_presence_preflight_allows_role_credentials_without_resolving_them(file_settings, monkeypatch):
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "")
    assert settings.missing_configuration() == []
