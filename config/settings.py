import json
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path(__file__).parent / "clients.json"


@dataclass
class ClientConfig:
    name: str
    base_url: str
    api_key: str
    table_prefix: str = "pw_"
    enabled: bool = True


@dataclass
class EmailConfig:
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender_email: str = ""
    sender_password: str = ""
    admin_emails: list = field(default_factory=list)


@dataclass
class AppSettings:
    days: int = 2
    max_workers: int = 4
    fetch_page_size: int = 5000
    request_timeout: int = 30
    clients: list[ClientConfig] = field(default_factory=list)
    email: EmailConfig = field(default_factory=EmailConfig)


def load_config() -> AppSettings:
    with open(CONFIG_PATH, "r") as f:
        raw = json.load(f)

    clients = [
        ClientConfig(**c) for c in raw.get("clients", []) if c.get("enabled", True)
    ]

    s = raw.get("settings", {})
    email_cfg = EmailConfig(**s.get("email", {}))

    return AppSettings(
        days=s.get("days", 2),
        max_workers=s.get("max_workers", 4),
        fetch_page_size=s.get("fetch_page_size", 5000),
        request_timeout=s.get("request_timeout", 30),
        clients=clients,
        email=email_cfg,
    )
