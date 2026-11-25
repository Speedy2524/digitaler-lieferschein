from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=True)
    role = Column(String(30), nullable=False, default="admin")  # 'admin' | 'staff'
    password_hash = Column(String(255), nullable=False)
    pin_hash = Column(String(255), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(128), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("User")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True, index=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    short_code = Column(String(50), nullable=True)
    email = Column(String(255), nullable=False)
    cc_email = Column(String(255), nullable=True)
    address = Column(String(300), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    delivery_notes = relationship("DeliveryNote", back_populates="school")


class StaffMember(Base):
    __tablename__ = "staff_members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, unique=True, index=True)
    role = Column(String(150), nullable=True)
    email = Column(String(255), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id = Column(Integer, primary_key=True, index=True)
    delivery_number = Column(String(50), nullable=False, unique=True, index=True)
    status = Column(String(30), nullable=False, default="ENTWURF", index=True)
    # Status-Werte: ENTWURF | BEREIT | ABGESCHLOSSEN

    school_id = Column(Integer, ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)
    school_name = Column(String(200), nullable=False, index=True)
    recipient_email = Column(String(255), nullable=False)
    cc_email = Column(String(255), nullable=True)

    # Stammdaten & Referenzen (Stufe 1)
    osticket_number = Column(String(50), nullable=True, index=True)
    ordered_by = Column(String(150), nullable=True)
    room = Column(String(150), nullable=True)
    supplier = Column(String(150), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)

    # Übergabe-Daten (Stufe 2)
    delivered_by = Column(String(150), nullable=True)
    received_by = Column(String(150), nullable=True, index=True)
    handover_notes = Column(Text, nullable=True)
    signature_data = Column(Text, nullable=True)  # Base64 Data-URL (PNG)

    # PDF & Versandstatus
    pdf_filename = Column(String(255), nullable=True)
    email_school_status = Column(String(40), nullable=False, default="AUSSTEHEND")
    # AUSSTEHEND | VERSENDET | SIMULIERT | FEHLER
    email_school_error = Column(Text, nullable=True)
    email_school_sent_at = Column(DateTime, nullable=True)

    email_osticket_status = Column(String(40), nullable=False, default="KEIN_TICKET")
    # KEIN_TICKET | NICHT_KONFIGURIERT | AUSSTEHEND | VERSENDET | SIMULIERT | FEHLER
    email_osticket_error = Column(Text, nullable=True)
    email_osticket_sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    school = relationship("School", back_populates="delivery_notes")
    items = relationship(
        "DeliveryItem",
        back_populates="delivery_note",
        cascade="all, delete-orphan",
        order_by="DeliveryItem.position",
    )


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, index=True)
    delivery_note_id = Column(
        Integer,
        ForeignKey("delivery_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False, default=1)
    device_type = Column(String(250), nullable=False)
    inventory_number = Column(String(120), nullable=False, index=True)
    serial_number = Column(String(150), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)

    delivery_note = relationship("DeliveryNote", back_populates="items")
