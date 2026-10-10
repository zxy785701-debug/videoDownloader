import os
import re
import logging

from ..analysis_errors import AnalysisError

# SDK INFO/DEBUG diagnostics can contain signed object URLs.
for _name in ("oss2", "aliyunsdkcore", "alibabacloud_credentials"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class OSSStorage:
    def __init__(self, config):
        self.config = config
        self.bucket = None

    def connect(self):
        if self.bucket is not None:
            return self.bucket
        endpoint = os.getenv("ALIYUN_OSS_ENDPOINT", "https://oss-cn-beijing.aliyuncs.com").rstrip("/")
        bucket_name = os.getenv("ALIYUN_OSS_BUCKET", "").strip()
        if not re.fullmatch(r"https://oss-[a-z0-9-]+\.aliyuncs\.com", endpoint) or "-internal" in endpoint:
            raise AnalysisError("ASR_OSS_CONFIG_INVALID", "OSS 需配置公网地域 HTTPS Endpoint。", 409)
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket_name):
            raise AnalysisError("ASR_OSS_NOT_CONFIGURED", "请管理员配置私有 ALIYUN_OSS_BUCKET。", 409)
        try:
            import oss2
            from oss2.credentials import Credentials, CredentialsProvider

            class Provider(CredentialsProvider):
                def __init__(self):
                    # Explicit RAM-role/default chain is preferred. Fixed RAM
                    # credentials are an optional fallback, never read from UI.
                    self.client = None
                    if not os.getenv("ALIYUN_OSS_ACCESS_KEY_ID"):
                        from alibabacloud_credentials.client import Client
                        self.client = Client()

                def get_credentials(self):
                    if self.client:
                        value = self.client.get_credential()
                        return Credentials(value.access_key_id, value.access_key_secret, value.security_token)
                    return Credentials(os.environ["ALIYUN_OSS_ACCESS_KEY_ID"],
                        os.environ["ALIYUN_OSS_ACCESS_KEY_SECRET"], os.getenv("ALIYUN_OSS_SECURITY_TOKEN"))

            region = endpoint.removeprefix("https://oss-").removesuffix(".aliyuncs.com")
            bucket = oss2.Bucket(oss2.ProviderAuthV4(Provider()), endpoint, bucket_name,
                                 region=region, connect_timeout=20)
            if bucket.get_bucket_acl().acl != oss2.BUCKET_ACL_PRIVATE:
                raise AnalysisError("ASR_OSS_NOT_PRIVATE", "ASR Bucket 必须设为私有，请管理员检查 OSS ACL 与 Bucket Policy。", 409)
            self.bucket = bucket
            return bucket
        except AnalysisError:
            raise
        except ImportError as error:
            raise AnalysisError("ASR_DEPENDENCY_MISSING", "请管理员安装 requirements-asr.txt 中的云存储依赖。", 409) from error
        except Exception as error:
            raise AnalysisError("ASR_OSS_UNAVAILABLE", "无法连接私有 OSS，请管理员检查凭证、地域及 RAM 权限。") from error

    @staticmethod
    def validate_key(key):
        if not re.fullmatch(r"asr/[0-9a-f]{32}\.flac", key):
            raise AnalysisError("ASR_OBJECT_INVALID", "临时音频对象标识无效。")

    def upload(self, path, key, check):
        self.validate_key(key)
        try:
            import oss2
            bucket = self.connect()
            def progress(consumed, total):
                check()
            check()
            bucket.put_object_from_file(key, str(path), headers={
                "x-oss-object-acl": oss2.OBJECT_ACL_PRIVATE, "Content-Type": "audio/flac"}, progress_callback=progress)
            return bucket.sign_url("GET", key, self.config.url_ttl, slash_safe=True)
        except AnalysisError:
            raise
        except Exception as error:
            from ..analysis_errors import JobStopped
            if isinstance(error, JobStopped):
                raise
            raise AnalysisError("ASR_OSS_UPLOAD_FAILED", "临时音频上传 OSS 失败，未提交识别任务。") from error

    def delete(self, key):
        self.validate_key(key)
        self.connect().delete_object(key)
