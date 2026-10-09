from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
import os

from dotenv import dotenv_values


@dataclass(frozen=True)
class Config:
    environment: str = "development"
    provider: str = "stripe"
    database: Path = Path("data/membership.sqlite3")
    public_url: str = "http://127.0.0.1:8010"
    secret_key: str = field(default="", repr=False)
    webhook_secret: str = field(default="", repr=False)
    price_id: str = ""
    mail_host: str = ""
    mail_port: int = 587
    mail_user: str = ""
    mail_password: str = field(default="", repr=False)
    mail_from: str = ""
    mail_directory: Path = Path("../.local/billing-mail")
    require_email_verification: bool = False
    free_limit: int = 3
    member_limit: int = 30

    @property
    def live(self):
        return self.environment == "production"

    def validate(self):
        if self.environment not in {"development", "production"} or self.provider not in {"stripe", "mock"}:
            raise ValueError("Invalid billing environment/provider")
        url = urlsplit(self.public_url)
        if url.username or url.password or url.query or url.fragment or url.path.rstrip("/"):
            raise ValueError("BILLING_PUBLIC_URL must be an origin")
        if url.scheme != "https" and not (not self.live and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}):
            raise ValueError("Public billing service requires HTTPS")
        if self.live and (self.provider != "stripe" or not self.mail_host or not self.mail_from or not self.mail_user or not self.mail_password):
            raise ValueError("Production requires Stripe and authenticated SMTP")
        if self.provider == "mock" and url.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Mock provider is loopback-only")
        if self.provider == "stripe":
            prefix = "sk_live_" if self.live else "sk_test_"
            if not self.secret_key.startswith(prefix) or not self.webhook_secret.startswith("whsec_") or not self.price_id.startswith("price_"):
                raise ValueError("Configure matching Stripe secret key, webhook secret and Price ID")
        if self.free_limit != 3 or self.member_limit != 30:
            raise ValueError("This release implements the approved 3/30 plan")


def load_config() -> Config:
    # Independent file: local app must never receive these payment secrets.
    file = Path(os.environ.get("BILLING_CONFIG_FILE", Path(__file__).resolve().parents[1] / ".env.billing"))
    values = dotenv_values(file) if file.is_file() else {}
    def value(key, default=""):
        return os.environ.get(key, values.get(key) or default)
    verification = value("BILLING_REQUIRE_EMAIL_VERIFICATION", "false").lower()
    if verification not in {"true", "false"}:
        raise ValueError("BILLING_REQUIRE_EMAIL_VERIFICATION must be true or false")
    config = Config(
        environment=value("BILLING_ENV", "development"), provider=value("BILLING_PROVIDER", "stripe"),
        database=Path(value("BILLING_DB", str(Path(__file__).resolve().parents[1] / "data/membership.sqlite3"))),
        public_url=value("BILLING_PUBLIC_URL", "http://127.0.0.1:8010").rstrip("/"),
        secret_key=value("STRIPE_SECRET_KEY"), webhook_secret=value("STRIPE_WEBHOOK_SECRET"), price_id=value("STRIPE_PRICE_ID"),
        mail_host=value("BILLING_SMTP_HOST"), mail_port=int(value("BILLING_SMTP_PORT", "587")),
        mail_user=value("BILLING_SMTP_USER"), mail_password=value("BILLING_SMTP_PASSWORD"), mail_from=value("BILLING_MAIL_FROM"),
        mail_directory=Path(value("BILLING_MAIL_DIR", str(Path(__file__).resolve().parents[2] / ".local/billing-mail"))),
        require_email_verification=verification == "true",
    )
    config.validate()
    return config
