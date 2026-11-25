import base64
import hashlib
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base, DeliveryItem, DeliveryNote, School, StaffMember, SystemSetting

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# Verschlüsselung sensibler Systemeinstellungen (z. B. SMTP-Passwort)
# ==============================================================================

_ENC_PREFIX = "enc:v1:"


def _get_fernet() -> Fernet:
    """Lädt oder erzeugt einen persistenten 256-Bit-Schlüssel für DB-Secrets."""
    if settings.SECRET_KEY:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    key_file: Path = settings.DATA_DIR / ".secret_key"
    if key_file.exists():
        raw_key = key_file.read_text(encoding="utf-8").strip()
        if raw_key:
            return Fernet(raw_key.encode("utf-8"))

    new_key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(new_key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return Fernet(new_key)


def encrypt_secret_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    if plaintext.startswith(_ENC_PREFIX):
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX}{token}"


def decrypt_secret_value(stored: str) -> str:
    if not stored:
        return ""
    if not stored.startswith(_ENC_PREFIX):
        return stored
    try:
        raw = stored[len(_ENC_PREFIX):]
        return _get_fernet().decrypt(raw.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


PLACEHOLDER_SMTP_HOSTS = {"mail.kommune.local"}
PLACEHOLDER_EMAILS = {"tickets@kommune.local", "schul-it@kommune.local"}


def _clean_placeholder(val: str, placeholders: set[str]) -> str:
    v = (val or "").strip()
    return "" if v.lower() in placeholders else v


DEFAULT_SYSTEM_SETTINGS: dict[str, str] = {
    "app_title": settings.APP_TITLE,
    "department_name": settings.DEPARTMENT_NAME,
    "department_subtitle": settings.DEPARTMENT_SUBTITLE,
    "department_contact": settings.DEPARTMENT_CONTACT,
    "auth_enabled": "true" if settings.AUTH_ENABLED else "false",
    "smtp_enabled": "true" if settings.SMTP_ENABLED else "false",
    "smtp_host": _clean_placeholder(settings.SMTP_HOST, PLACEHOLDER_SMTP_HOSTS),
    "smtp_port": str(settings.SMTP_PORT),
    "smtp_security": settings.SMTP_SECURITY,
    "smtp_username": settings.SMTP_USERNAME,
    "smtp_password": encrypt_secret_value(settings.SMTP_PASSWORD) if settings.SMTP_PASSWORD else "",
    "smtp_from_email": _clean_placeholder(settings.SMTP_FROM_EMAIL, PLACEHOLDER_EMAILS),
    "smtp_from_name": settings.SMTP_FROM_NAME,
    "osticket_enabled": "true" if _clean_placeholder(settings.OSTICKET_EMAIL, PLACEHOLDER_EMAILS) else "false",
    "osticket_email": _clean_placeholder(settings.OSTICKET_EMAIL, PLACEHOLDER_EMAILS),
    "global_archive_cc_email": settings.GLOBAL_ARCHIVE_CC_EMAIL,
}


def get_runtime_settings(db: Session) -> dict[str, str]:
    """Liest alle Systemeinstellungen aus der DB und entschlüsselt gespeicherte Secrets."""
    result = dict(DEFAULT_SYSTEM_SETTINGS)
    rows = db.query(SystemSetting).all()
    for row in rows:
        result[row.key] = row.value

    result["smtp_password"] = decrypt_secret_value(result.get("smtp_password", ""))
    return result


def set_runtime_settings(db: Session, updates: dict[str, str]) -> dict[str, str]:
    """Speichert geänderte Systemeinstellungen persistent (mit verschlüsseltem SMTP-Passwort)."""
    for key, val in updates.items():
        if key not in DEFAULT_SYSTEM_SETTINGS:
            continue
        stored_val = str(val)
        if key == "smtp_password":
            stored_val = encrypt_secret_value(stored_val) if stored_val else ""

        existing = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if existing:
            existing.value = stored_val
        else:
            db.add(SystemSetting(key=key, value=stored_val))
    db.commit()
    return get_runtime_settings(db)


def generate_next_delivery_number(db: Session, year: int | None = None) -> str:
    """Erzeugt eine fortlaufende Lieferschein-Nummer im Format LS-YYYY-NNNN."""
    if year is None:
        try:
            year = datetime.now(ZoneInfo(settings.TIMEZONE)).year
        except Exception:
            year = datetime.now().year
    prefix = f"LS-{year}-"
    existing = (
        db.query(DeliveryNote.delivery_number)
        .filter(DeliveryNote.delivery_number.like(f"{prefix}%"))
        .all()
    )
    max_seq = 0
    for (num,) in existing:
        try:
            seq_part = num.replace(prefix, "").strip()
            seq = int(seq_part)
            if seq > max_seq:
                max_seq = seq
        except ValueError:
            continue
    return f"{prefix}{max_seq + 1:04d}"


def init_db_and_seed() -> None:
    """Erstellt Tabellen, führt sanfte Migrationen durch und legt initiale Stammdaten an."""
    Base.metadata.create_all(bind=engine)

    # SQLite-Datenbankdatei vor Lesezugriff durch andere lokale Systemkonten schützen
    if settings.DATABASE_URL.startswith("sqlite:///"):
        db_file = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
        if db_file.exists():
            try:
                os.chmod(db_file, 0o600)
            except OSError:
                pass

    db = SessionLocal()
    try:
        # 0. Sanfte Migration für bestehende SQLite-DBs (supplier & invoice_number an delivery_items)
        if settings.DATABASE_URL.startswith("sqlite"):
            cols = [row[1] for row in db.execute(text("PRAGMA table_info(delivery_items)")).fetchall()]
            if "supplier" not in cols:
                db.execute(text("ALTER TABLE delivery_items ADD COLUMN supplier VARCHAR(150)"))
            if "invoice_number" not in cols:
                db.execute(text("ALTER TABLE delivery_items ADD COLUMN invoice_number VARCHAR(100)"))
            db.commit()

        # 1. Initiale System-Settings in DB anlegen & Altlasten/Klartext-Secrets bereinigen
        existing_rows = {row.key: row for row in db.query(SystemSetting).all()}
        for k, v in DEFAULT_SYSTEM_SETTINGS.items():
            if k not in existing_rows:
                db.add(SystemSetting(key=k, value=v))

        if "smtp_password" in existing_rows:
            pw_row = existing_rows["smtp_password"]
            if pw_row.value and not pw_row.value.startswith(_ENC_PREFIX):
                pw_row.value = encrypt_secret_value(pw_row.value)

        if "osticket_email" in existing_rows:
            ot_row = existing_rows["osticket_email"]
            if ot_row.value.strip().lower() == "tickets@kommune.local":
                ot_row.value = ""
                if "osticket_enabled" in existing_rows:
                    existing_rows["osticket_enabled"].value = "false"

        db.flush()

        # 2. Beispielschulen & Mitarbeiter
        school_count = db.query(School).count()
        staff_count = db.query(StaffMember).count()

        if school_count == 0:
            schools = [
                School(
                    name="Musterschule Nord GS",
                    short_code="MSN-GS",
                    email="sekretariat@musterschule-nord.schule.local",
                    cc_email="rektorat@musterschule-nord.schule.local",
                    address="Schulstraße 12, 12345 Musterstadt",
                    active=True,
                ),
                School(
                    name="Friedrich-Schiller-Realschule",
                    short_code="FSR",
                    email="poststelle@fsr.schule.local",
                    cc_email="it-beauftragter@fsr.schule.local",
                    address="Schillerplatz 4, 12345 Musterstadt",
                    active=True,
                ),
                School(
                    name="Goethe-Gymnasium",
                    short_code="GG",
                    email="sekretariat@goethe-gymnasium.schule.local",
                    cc_email="",
                    address="Goetheallee 20, 12345 Musterstadt",
                    active=True,
                ),
                School(
                    name="Pestalozzischule Grund- und Werkrealschule",
                    short_code="PS-GWRS",
                    email="sekretariat@pestalozzischule.schule.local",
                    cc_email="",
                    address="Pestalozzistraße 8, 12345 Musterstadt",
                    active=True,
                ),
            ]
            db.add_all(schools)
            db.flush()

        if staff_count == 0:
            staff_members = [
                StaffMember(
                    name="Max Mustermann",
                    role="IT-Systemadministrator (Schul-IT)",
                    email="m.mustermann@kommune.local",
                    active=True,
                ),
                StaffMember(
                    name="Lukas Weber",
                    role="Auszubildender Fachinformatiker Systemintegration",
                    email="l.weber@kommune.local",
                    active=True,
                ),
                StaffMember(
                    name="Sarah Klein",
                    role="IT-Support & Inventarisierung",
                    email="s.klein@kommune.local",
                    active=True,
                ),
            ]
            db.add_all(staff_members)
            db.flush()

        # Falls noch gar keine Lieferscheine existieren, 2 realistische Beispiel-Lieferscheine anlegen
        if db.query(DeliveryNote).count() == 0:
            rbs = db.query(School).filter(School.name == "Musterschule Nord GS").first()
            asr = db.query(School).filter(School.name == "Friedrich-Schiller-Realschule").first()
            try:
                year = datetime.now(ZoneInfo(settings.TIMEZONE)).year
            except Exception:
                year = datetime.now().year

            if rbs:
                note1 = DeliveryNote(
                    delivery_number=f"LS-{year}-0001",
                    status="BEREIT",
                    school_id=rbs.id,
                    school_name=rbs.name,
                    recipient_email=rbs.email,
                    cc_email=rbs.cc_email,
                    osticket_number="382814",
                    ordered_by="Fr. Schneider (Konrektorin)",
                    room="Lehrerzimmer / Medienwagen 2",
                    notes="iPads sind im MDM (Jamf School) vorregistriert. Bitte Ladekoffer-Schlüssel im Sekretariat abgeben.",
                )
                db.add(note1)
                db.flush()
                db.add_all([
                    DeliveryItem(
                        delivery_note_id=note1.id,
                        position=1,
                        device_type="Apple iPad 10. Gen 64GB Wi-Fi inkl. Rugged Case",
                        inventory_number="INV-2026-1041",
                        serial_number="DLXQT98A11",
                        supplier="Bechtle Logistik & Service GmbH",
                        invoice_number="RE-2026-88412",
                        quantity=1,
                    ),
                    DeliveryItem(
                        delivery_note_id=note1.id,
                        position=2,
                        device_type="Apple iPad 10. Gen 64GB Wi-Fi inkl. Rugged Case",
                        inventory_number="INV-2026-1042",
                        serial_number="DLXQT98A12",
                        supplier="Bechtle Logistik & Service GmbH",
                        invoice_number="RE-2026-88412",
                        quantity=1,
                    ),
                    DeliveryItem(
                        delivery_note_id=note1.id,
                        position=3,
                        device_type="Apple Pencil (USB-C)",
                        inventory_number="INV-2026-1043",
                        serial_number="GQF882190A",
                        supplier="Cancom GmbH",
                        invoice_number="CN-994105",
                        quantity=2,
                    ),
                ])

            if asr:
                note2 = DeliveryNote(
                    delivery_number=f"LS-{year}-0002",
                    status="BEREIT",
                    school_id=asr.id,
                    school_name=asr.name,
                    recipient_email=asr.email,
                    cc_email=asr.cc_email,
                    osticket_number="382905",
                    ordered_by="Hr. Kienzle (IT-Beauftragter)",
                    room="EDV-Raum 2.04",
                    notes="Austauschgerät für defekten Lehrer-PC. Altgerät bitte zur Abholung mitnehmen.",
                )
                db.add(note2)
                db.flush()
                db.add_all([
                    DeliveryItem(
                        delivery_note_id=note2.id,
                        position=1,
                        device_type="HP Elite Mini 800 G9 (i5 / 16GB / 512GB SSD)",
                        inventory_number="INV-2026-2190",
                        serial_number="CZC41892KL",
                        supplier="Cancom GmbH",
                        invoice_number="CN-994210",
                        quantity=1,
                    ),
                    DeliveryItem(
                        delivery_note_id=note2.id,
                        position=2,
                        device_type="HP E24 G5 24-Zoll IPS-Monitor",
                        inventory_number="INV-2026-2191",
                        serial_number="CNC411087P",
                        supplier="Cancom GmbH",
                        invoice_number="CN-994210",
                        quantity=1,
                    ),
                ])

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
