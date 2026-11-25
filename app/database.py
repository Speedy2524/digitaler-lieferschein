from datetime import datetime
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base, DeliveryItem, DeliveryNote, School, StaffMember

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


def generate_next_delivery_number(db: Session, year: int | None = None) -> str:
    """Erzeugt eine fortlaufende Lieferschein-Nummer im Format LS-YYYY-NNNN."""
    if year is None:
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
    """Erstellt Tabellen und legt initiale Beispiel-Stammdaten an, falls die DB leer ist."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
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
                    supplier="Bechtle Logistik & Service GmbH",
                    invoice_number="RE-2026-88412",
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
                        quantity=1,
                    ),
                    DeliveryItem(
                        delivery_note_id=note1.id,
                        position=2,
                        device_type="Apple iPad 10. Gen 64GB Wi-Fi inkl. Rugged Case",
                        inventory_number="INV-2026-1042",
                        serial_number="DLXQT98A12",
                        quantity=1,
                    ),
                    DeliveryItem(
                        delivery_note_id=note1.id,
                        position=3,
                        device_type="Apple Pencil (USB-C)",
                        inventory_number="INV-2026-1043",
                        serial_number="GQF882190A",
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
                    supplier="Cancom GmbH",
                    invoice_number="CN-994210",
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
                        quantity=1,
                    ),
                    DeliveryItem(
                        delivery_note_id=note2.id,
                        position=2,
                        device_type="HP E24 G5 24-Zoll IPS-Monitor",
                        inventory_number="INV-2026-2191",
                        serial_number="CNC411087P",
                        quantity=1,
                    ),
                ])

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
