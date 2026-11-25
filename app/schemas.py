import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def _ensure_utc(dt: datetime) -> datetime:
    """Stellt sicher, dass naive SQLite-Datetimes als UTC serialisiert werden (mit +00:00 / Z)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


UTCDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]

_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


def _reject_control_chars(v: str, field_label: str = "Eingabe") -> str:
    if any(ch in v for ch in ("\r", "\n", "\x00")):
        raise ValueError(f"{field_label} darf keine Steuer- oder Zeilenumbruchzeichen enthalten.")
    return v


def _validate_single_email(v: str | None, required: bool = False) -> str | None:
    if v is None:
        if required:
            raise ValueError("E-Mail-Adresse darf nicht leer sein.")
        return None
    cleaned = v.strip()
    if not cleaned:
        if required:
            raise ValueError("E-Mail-Adresse darf nicht leer sein.")
        return None
    _reject_control_chars(cleaned, "E-Mail-Adresse")
    if not _EMAIL_REGEX.match(cleaned):
        raise ValueError(f"Ungültige E-Mail-Adresse: '{cleaned}'")
    return cleaned


def _validate_email_list(v: str | None) -> str | None:
    if v is None:
        return None
    cleaned = v.strip()
    if not cleaned:
        return None
    _reject_control_chars(cleaned, "CC-E-Mail-Adresse")
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts:
        return None
    for part in parts:
        if not _EMAIL_REGEX.match(part):
            raise ValueError(f"Ungültige CC-E-Mail-Adresse: '{part}'")
    return ", ".join(parts)


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

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = _reject_control_chars(v.strip(), "Schulname")
        if len(v) < 2:
            raise ValueError("Schulname muss mindestens 2 Zeichen lang sein.")
        return v

    @field_validator("email")
    @classmethod
    def validate_school_email(cls, v: str) -> str:
        return _validate_single_email(v, required=True)  # type: ignore[return-value]

    @field_validator("cc_email")
    @classmethod
    def validate_school_cc(cls, v: str | None) -> str | None:
        return _validate_email_list(v)

    @field_validator("short_code", "address")
    @classmethod
    def strip_opt(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _reject_control_chars(v.strip())
        return v or None


class SchoolCreate(SchoolBase):
    pass


class SchoolUpdate(SchoolBase):
    pass


class SchoolResponse(SchoolBase):
    id: int
    created_at: UTCDatetime

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
        v = _reject_control_chars(v.strip(), "Mitarbeitername")
        if len(v) < 2:
            raise ValueError("Name muss mindestens 2 Zeichen lang sein.")
        return v

    @field_validator("email")
    @classmethod
    def validate_staff_email(cls, v: str | None) -> str | None:
        return _validate_single_email(v, required=False)


class StaffCreate(StaffBase):
    pass


class StaffUpdate(StaffBase):
    pass


class StaffResponse(StaffBase):
    id: int
    created_at: UTCDatetime

    model_config = ConfigDict(from_attributes=True)


# --- Lokale Benutzerverwaltung & Authentifizierung ---
class InitialSetupRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(..., min_length=8, max_length=200)
    pin: str | None = Field(default=None, max_length=20)
    add_to_staff_list: bool = True

    @field_validator("username", "full_name")
    @classmethod
    def strip_user_fields(cls, v: str) -> str:
        v = _reject_control_chars(v.strip())
        if len(v) < 2:
            raise ValueError("Feld muss mindestens 2 Zeichen lang sein.")
        return v

    @field_validator("email")
    @classmethod
    def validate_setup_email(cls, v: str | None) -> str | None:
        return _validate_single_email(v, required=False)

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if len(cleaned) < 4:
            raise ValueError("Die Schnell-PIN muss mindestens 4 Zeichen lang sein.")
        return cleaned


class LoginRequest(BaseModel):
    username: str | None = Field(default=None, max_length=150)
    pin_or_password: str = Field(..., min_length=1, max_length=200)


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
        v = _reject_control_chars(v.strip())
        if len(v) < 2:
            raise ValueError("Benutzername und Anzeigename müssen mindestens 2 Zeichen lang sein.")
        return v

    @field_validator("email")
    @classmethod
    def validate_user_email(cls, v: str | None) -> str | None:
        return _validate_single_email(v, required=False)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if len(cleaned) < 8:
            raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
        return cleaned

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if len(cleaned) < 4:
            raise ValueError("Die Schnell-PIN muss mindestens 4 Zeichen lang sein.")
        return cleaned


class UserUpdateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    role: Literal["admin", "staff"] = "staff"
    password: str | None = Field(default=None, max_length=200)
    pin: str | None = Field(default=None, max_length=20)
    clear_pin: bool = False
    active: bool = True

    @field_validator("username", "full_name")
    @classmethod
    def strip_required_user(cls, v: str) -> str:
        v = _reject_control_chars(v.strip())
        if len(v) < 2:
            raise ValueError("Benutzername und Anzeigename müssen mindestens 2 Zeichen lang sein.")
        return v

    @field_validator("email")
    @classmethod
    def validate_user_email(cls, v: str | None) -> str | None:
        return _validate_single_email(v, required=False)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if len(cleaned) < 8:
            raise ValueError("Das Passwort muss mindestens 8 Zeichen lang sein.")
        return cleaned

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if len(cleaned) < 4:
            raise ValueError("Die Schnell-PIN muss mindestens 4 Zeichen lang sein.")
        return cleaned


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str
    email: str | None
    role: str
    has_pin: bool = False
    has_password: bool = True
    active: bool
    last_login_at: UTCDatetime | None
    created_at: UTCDatetime

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
    smtp_password: str | None = None
    smtp_from_email: str = Field(default="", max_length=200)
    smtp_from_name: str = Field(default="Schul-IT Lieferschein-System", max_length=200)

    osticket_enabled: bool = False
    osticket_email: str = Field(default="", max_length=200)
    global_archive_cc_email: str = Field(default="", max_length=200)

    @field_validator(
        "app_title",
        "department_name",
        "department_subtitle",
        "department_contact",
        "smtp_host",
        "smtp_username",
        "smtp_from_name",
    )
    @classmethod
    def check_no_crlf(cls, v: str) -> str:
        return _reject_control_chars(v.strip())

    @field_validator("smtp_from_email", "osticket_email")
    @classmethod
    def validate_single_cfg_email(cls, v: str) -> str:
        return _validate_single_email(v, required=False) or ""

    @field_validator("global_archive_cc_email")
    @classmethod
    def validate_cc_cfg_email(cls, v: str) -> str:
        return _validate_email_list(v) or ""


class SmtpTestRequest(BaseModel):
    recipient_email: str = Field(..., min_length=3, max_length=255)

    @field_validator("recipient_email")
    @classmethod
    def validate_test_recipient(cls, v: str) -> str:
        return _validate_single_email(v, required=True)  # type: ignore[return-value]


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
        v = _reject_control_chars(v.strip())
        if not v:
            raise ValueError("Gerätebezeichnung und Inventarnummer sind Pflichtfelder.")
        return v

    @field_validator("serial_number", "supplier", "invoice_number")
    @classmethod
    def strip_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _reject_control_chars(v.strip())
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
    notes: str | None = Field(default=None, max_length=5000)

    status: Literal["ENTWURF", "BEREIT"] = "BEREIT"
    items: list[DeliveryItemInput] = Field(..., min_length=1, max_length=250)

    @field_validator("osticket_number")
    @classmethod
    def validate_osticket(cls, v: str | None) -> str | None:
        return clean_osticket_number(v)

    @field_validator("school_name", "ordered_by", "room")
    @classmethod
    def validate_single_line_text(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _reject_control_chars(v.strip())
        return v or None

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        return _validate_single_email(v, required=True)  # type: ignore[return-value]

    @field_validator("cc_email")
    @classmethod
    def validate_cc(cls, v: str | None) -> str | None:
        return _validate_email_list(v)


# --- Übergabe abschließen & unterschreiben (Stufe 2) ---
class DeliveryNoteCompleteRequest(BaseModel):
    delivered_by: str = Field(..., min_length=2, max_length=150)
    received_by: str = Field(..., min_length=2, max_length=150)
    handover_notes: str | None = Field(default=None, max_length=5000)
    signature_data: str = Field(..., min_length=50, max_length=700_000)

    @field_validator("delivered_by", "received_by")
    @classmethod
    def strip_names(cls, v: str) -> str:
        v = _reject_control_chars(v.strip())
        if len(v) < 2:
            raise ValueError("Übergebende und annehmende Person müssen mindestens 2 Zeichen lang sein.")
        return v

    @field_validator("signature_data")
    @classmethod
    def validate_signature(cls, v: str) -> str:
        v = v.strip()
        prefix = "data:image/png;base64,"
        if not v.startswith(prefix):
            raise ValueError("Ungültiges Signaturformat (PNG Data-URL erwartet).")
        b64_part = v[len(prefix):]
        try:
            raw = base64.b64decode(b64_part, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Ungültige Base64-Kodierung in der digitalen Unterschrift.") from exc
        if len(raw) < 24 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Die Signatur muss eine gültige PNG-Grafik sein.")
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
    email_school_sent_at: UTCDatetime | None

    email_osticket_status: str
    email_osticket_error: str | None
    email_osticket_sent_at: UTCDatetime | None

    created_at: UTCDatetime
    updated_at: UTCDatetime
    completed_at: UTCDatetime | None

    items: list[DeliveryItemResponse]
    total_quantity: int = 0

    model_config = ConfigDict(from_attributes=True)
