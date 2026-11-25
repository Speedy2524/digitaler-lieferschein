import re
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


def clean_osticket_number(val: str | None) -> str | None:
    """Bereinigt eine osTicket-Nummer von #, Leerzeichen oder Präfixen und prüft auf reine Ziffern."""
    if val is None:
        return None
    cleaned = val.strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"^[\[\s#]*(?:ticket\s*[:#-]?\s*)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\]\s#]+$", "", cleaned)
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        return None
    if not cleaned.isdigit():
        raise ValueError("Die osTicket-Nummer darf nach Bereinigung nur aus Ziffern bestehen (z. B. 382814).")
    return cleaned


# --- Schulen ---
class SchoolBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    short_code: str | None = Field(default=None, max_length=50)
    email: str = Field(..., min_length=3, max_length=255)
    cc_email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=300)
    active: bool = True

    @field_validator("name", "email")
    @classmethod
    def strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Darf nicht leer sein.")
        return v


class SchoolCreate(SchoolBase):
    pass


class SchoolUpdate(SchoolBase):
    pass


class SchoolResponse(SchoolBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- IT-Mitarbeiter / Azubis ---
class StaffBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    role: str | None = Field(default=None, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    active: bool = True

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name darf nicht leer sein.")
        return v


class StaffCreate(StaffBase):
    pass


class StaffUpdate(StaffBase):
    pass


class StaffResponse(StaffBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Lokale Benutzerverwaltung & Authentifizierung ---
class InitialSetupRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(..., min_length=4, max_length=200)
    pin: str | None = Field(default=None, max_length=20)
    add_to_staff_list: bool = True

    @field_validator("username", "full_name")
    @classmethod
    def strip_user_fields(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Feld darf nicht leer sein.")
        return v


class LoginRequest(BaseModel):
    username: str | None = None
    pin_or_password: str = Field(..., min_length=1)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    role: Literal["admin", "staff"] = "staff"
    password: str | None = Field(default=None, max_length=200)
    pin: str | None = Field(default=None, max_length=20)
    active: bool = True
    add_to_staff_list: bool = True

    @field_validator("username", "full_name")
    @classmethod
    def strip_required_user(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Benutzername und Anzeigename sind Pflichtfelder.")
        return v


class UserUpdateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    role: Literal["admin", "staff"] = "staff"
    password: str | None = Field(default=None, max_length=200)
    pin: str | None = Field(default=None, max_length=20)
    clear_pin: bool = False
    active: bool = True


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    email: str | None
    role: str
    has_pin: bool = False
    active: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- Systemeinstellungen (Konfigmenü) ---
class SystemSettingsUpdateRequest(BaseModel):
    app_title: str = Field(default="Digitaler IT-Lieferschein", min_length=2, max_length=150)
    department_name: str = Field(default="Stadtverwaltung – Schul-IT", min_length=2, max_length=200)
    department_subtitle: str = Field(default="", max_length=200)
    department_contact: str = Field(default="", max_length=250)
    auth_enabled: bool = True

    smtp_enabled: bool = False
    smtp_host: str = Field(default="", max_length=200)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str = Field(default="", max_length=200)
    smtp_password: str | None = None  # Wenn None oder "__UNCHANGED__", bleibt das gespeicherte Passwort erhalten
    smtp_from_email: str = Field(default="", max_length=200)
    smtp_from_name: str = Field(default="Schul-IT Lieferschein-System", max_length=200)

    osticket_enabled: bool = False
    osticket_email: str = Field(default="", max_length=200)
    global_archive_cc_email: str = Field(default="", max_length=200)


class SmtpTestRequest(BaseModel):
    recipient_email: str = Field(..., min_length=3, max_length=255)


# --- Gerätepositionen ---
class DeliveryItemInput(BaseModel):
    device_type: str = Field(..., min_length=1, max_length=250)
    inventory_number: str = Field(..., min_length=1, max_length=120)
    serial_number: str | None = Field(default=None, max_length=150)
    supplier: str | None = Field(default=None, max_length=150)
    invoice_number: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=1, le=9999)

    @field_validator("device_type", "inventory_number")
    @classmethod
    def strip_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Gerätebezeichnung und Inventarnummer sind Pflichtfelder.")
        return v

    @field_validator("serial_number", "supplier", "invoice_number")
    @classmethod
    def strip_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class DeliveryItemResponse(DeliveryItemInput):
    id: int
    position: int

    model_config = ConfigDict(from_attributes=True)


# --- Lieferschein anlegen / bearbeiten (Stufe 1 & Direkt-Übergabe) ---
class DeliveryNoteSaveRequest(BaseModel):
    school_id: int | None = None
    school_name: str | None = Field(default=None, max_length=200)
    recipient_email: str = Field(..., min_length=3, max_length=255)
    cc_email: str | None = Field(default=None, max_length=255)

    osticket_number: str | None = Field(default=None, max_length=50)
    ordered_by: str | None = Field(default=None, max_length=150)
    room: str | None = Field(default=None, max_length=150)
    supplier: str | None = Field(default=None, max_length=150)
    invoice_number: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    status: Literal["ENTWURF", "BEREIT"] = "BEREIT"
    items: list[DeliveryItemInput] = Field(..., min_length=1)

    @field_validator("osticket_number")
    @classmethod
    def validate_osticket(cls, v: str | None) -> str | None:
        return clean_osticket_number(v)

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v:
            raise ValueError("Bitte eine gültige Empfänger-E-Mail-Adresse eingeben.")
        return v


# --- Übergabe abschließen & unterschreiben (Stufe 2) ---
class DeliveryNoteCompleteRequest(BaseModel):
    delivered_by: str = Field(..., min_length=2, max_length=150)
    received_by: str = Field(..., min_length=2, max_length=150)
    handover_notes: str | None = None
    signature_data: str = Field(..., min_length=50)
    recipient_email: str | None = None
    cc_email: str | None = None

    @field_validator("delivered_by", "received_by")
    @classmethod
    def strip_names(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Übergebende und annehmende Person müssen angegeben werden.")
        return v

    @field_validator("signature_data")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("data:image/png;base64,"):
            raise ValueError("Ungültiges Signaturformat (PNG Data-URL erwartet).")
        return v


class DeliveryNoteResponse(BaseModel):
    id: int
    delivery_number: str
    status: str

    school_id: int | None
    school_name: str
    recipient_email: str
    cc_email: str | None

    osticket_number: str | None
    ordered_by: str | None
    room: str | None
    supplier: str | None
    invoice_number: str | None
    notes: str | None

    delivered_by: str | None
    received_by: str | None
    handover_notes: str | None
    signature_data: str | None

    pdf_filename: str | None
    email_school_status: str
    email_school_error: str | None
    email_school_sent_at: datetime | None

    email_osticket_status: str
    email_osticket_error: str | None
    email_osticket_sent_at: datetime | None

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    items: list[DeliveryItemResponse]
    total_quantity: int = 0

    model_config = ConfigDict(from_attributes=True)
