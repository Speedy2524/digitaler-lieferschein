import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _str_to_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "ja", "on")


class Settings:
    APP_TITLE: str = os.getenv("APP_TITLE", "Digitaler IT-Lieferschein")
    DEPARTMENT_NAME: str = os.getenv(
        "DEPARTMENT_NAME",
        "Stadtverwaltung – Schul-IT / Amt für Bildung und Sport",
    )
    DEPARTMENT_SUBTITLE: str = os.getenv(
        "DEPARTMENT_SUBTITLE",
        "Kommunale IT-Betreuung der Schulen",
    )
    DEPARTMENT_CONTACT: str = os.getenv(
        "DEPARTMENT_CONTACT",
        "schul-it@kommune.local | Tel. 01234 / 567-890",
    )
    TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Berlin")

    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "./data")).resolve()
    PDF_STORAGE_DIR: Path = Path(os.getenv("PDF_STORAGE_DIR", "./data/pdfs")).resolve()
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(Path(os.getenv('DATA_DIR', './data')).resolve() / 'lieferscheine.db').as_posix()}",
    )

    # Verschlüsselung & Zugriffsschutz
    SECRET_KEY: str = os.getenv("SECRET_KEY", "").strip()
    AUTH_ENABLED: bool = _str_to_bool(os.getenv("AUTH_ENABLED"), True)

    # SMTP-Initialeinstellungen
    SMTP_ENABLED: bool = _str_to_bool(os.getenv("SMTP_ENABLED"), False)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_SECURITY: str = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "").strip()
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "Schul-IT Lieferschein-System").strip()
    SMTP_TIMEOUT: int = int(os.getenv("SMTP_TIMEOUT", "15"))

    # osTicket & globales Archiv
    OSTICKET_EMAIL: str = os.getenv("OSTICKET_EMAIL", "").strip()
    GLOBAL_ARCHIVE_CC_EMAIL: str = os.getenv("GLOBAL_ARCHIVE_CC_EMAIL", "").strip()


settings = Settings()
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.PDF_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
