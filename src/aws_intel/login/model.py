"""Models used to describe AWS login chains."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Account:
    """One directly accessible or role-chained AWS account."""

    name: str
    account_id: str
    role_name: str
    region: str
    source: str | None = None
    sso_start_url: str | None = None
    sso_region: str | None = None
    session_duration_hours: int | None = None


@dataclass(frozen=True)
class Credentials:
    """Temporary AWS credentials suitable for a subprocess environment."""

    access_key_id: str
    secret_access_key: str
    session_token: str
    expires_at: datetime

    def environment(self) -> dict[str, str]:
        return {
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
            "AWS_SESSION_TOKEN": self.session_token,
        }
