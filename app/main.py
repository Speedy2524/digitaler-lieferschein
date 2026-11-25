import base64
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import generate_next_delivery_number, get_db, init_db_and_seed
from app.email_service import dispatch_delivery_note_emails
from app.models import DeliveryItem, DeliveryNote, School, StaffMember
from app.pdf_service import generate_delivery_note_pdf, render_delivery_note_html
from app.schemas import (
    DeliveryNoteCompleteRequest,
    DeliveryNoteResponse,
    DeliveryNoteSaveRequest,
    LoginRequest,
    SchoolCreate,
    SchoolResponse,
    SchoolUpdate,
    StaffCreate,
    StaffResponse,
    StaffUpdate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db_and_seed()
    yield


app = FastAPI(
    title=settings.APP_TITLE,
    description="Selbstgehostete Webanwendung für digitale IT-Lieferscheine (Schul-IT)",
    version="1.0.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ==============================================================================
# Zugriffsschutz / Authentifizierung (Optional via .env)
# ==============================================================================

def _compute_auth_token() -> str:
    secret = f"{settings.AUTH_USERNAME}:{settings.AUTH_PASSWORD}:{settings.AUTH_PIN}"
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _verify_credentials(secret_input: str, username_input: str | None = None) -> bool:
    secret_input = secret_input.strip()
    if settings.AUTH_PIN and hmac.compare_digest(secret_input, settings.AUTH_PIN):
        return True
    if settings.AUTH_PASSWORD and hmac.compare_digest(secret_input, settings.AUTH_PASSWORD):
        if not username_input or hmac.compare_digest(username_input.strip(), settings.AUTH_USERNAME):
            return True
    return False


def _is_request_authenticated(request: Request) -> bool:
    if not settings.AUTH_ENABLED:
        return True

    expected_token = _compute_auth_token()

    # 1. Token aus Header oder Cookie prüfen
    header_token = request.headers.get("X-Auth-Token", "")
    cookie_token = request.cookies.get("it_ls_token", "")
    if header_token and hmac.compare_digest(header_token, expected_token):
        return True
    if cookie_token and hmac.compare_digest(cookie_token, expected_token):
        return True

    # 2. HTTP Basic Auth prüfen
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            if _verify_credentials(password, username):
                return True
        except Exception:
            pass

    return False


def require_auth(request: Request) -> None:
    if not _is_request_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentifizierung erforderlich. Bitte PIN oder Zugangsdaten eingeben.",
        )


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_TITLE}


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "authenticated": _is_request_authenticated(request),
        "app_title": settings.APP_TITLE,
        "department_name": settings.DEPARTMENT_NAME,
        "department_subtitle": settings.DEPARTMENT_SUBTITLE,
        "smtp_enabled": settings.SMTP_ENABLED,
        "osticket_configured": bool(settings.OSTICKET_EMAIL),
        "osticket_email": settings.OSTICKET_EMAIL,
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    if not settings.AUTH_ENABLED:
        return {"authenticated": True, "token": "auth-disabled"}

    if not _verify_credentials(payload.pin_or_password, payload.username):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige PIN oder falsches Passwort.",
        )

    token = _compute_auth_token()
    response.set_cookie(
        key="it_ls_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,  # 14 Tage
    )
    return {"authenticated": True, "token": token}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("it_ls_token")
    return {"authenticated": False}


# ==============================================================================
# Dashboard-Statistiken
# ==============================================================================

@app.get("/api/stats", dependencies=[Depends(require_auth)])
def get_stats(db: Session = Depends(get_db)):
    count_draft = db.query(DeliveryNote).filter(DeliveryNote.status == "ENTWURF").count()
    count_ready = db.query(DeliveryNote).filter(DeliveryNote.status == "BEREIT").count()
    count_completed = db.query(DeliveryNote).filter(DeliveryNote.status == "ABGESCHLOSSEN").count()
    count_email_errors = (
        db.query(DeliveryNote)
        .filter(
            DeliveryNote.status == "ABGESCHLOSSEN",
            or_(
                DeliveryNote.email_school_status == "FEHLER",
                DeliveryNote.email_osticket_status == "FEHLER",
            ),
        )
        .count()
    )
    return {
        "draft": count_draft,
        "ready": count_ready,
        "completed": count_completed,
        "email_errors": count_email_errors,
    }


# ==============================================================================
# Stammdaten: Schulen
# ==============================================================================

@app.get("/api/schools", response_model=list[SchoolResponse], dependencies=[Depends(require_auth)])
def list_schools(
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = db.query(School)
    if active_only:
        query = query.filter(School.active.is_(True))
    return query.order_by(School.name.asc()).all()


@app.post(
    "/api/schools",
    response_model=SchoolResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_auth)],
)
def create_school(payload: SchoolCreate, db: Session = Depends(get_db)):
    existing = db.query(School).filter(School.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Eine Schule mit dem Namen '{payload.name}' existiert bereits.",
        )
    school = School(**payload.model_dump())
    db.add(school)
    db.commit()
    db.refresh(school)
    return school


@app.put("/api/schools/{school_id}", response_model=SchoolResponse, dependencies=[Depends(require_auth)])
def update_school(school_id: int, payload: SchoolUpdate, db: Session = Depends(get_db)):
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="Schule nicht gefunden.")

    duplicate = (
        db.query(School)
        .filter(School.name == payload.name, School.id != school_id)
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"Eine andere Schule mit dem Namen '{payload.name}' existiert bereits.",
        )

    for key, val in payload.model_dump().items():
        setattr(school, key, val)
    db.commit()
    db.refresh(school)
    return school


@app.delete("/api/schools/{school_id}", dependencies=[Depends(require_auth)])
def delete_school(school_id: int, db: Session = Depends(get_db)):
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="Schule nicht gefunden.")
    db.delete(school)
    db.commit()
    return {"deleted": True, "id": school_id}


# ==============================================================================
# Stammdaten: IT-Mitarbeiter / Azubis
# ==============================================================================

@app.get("/api/staff", response_model=list[StaffResponse], dependencies=[Depends(require_auth)])
def list_staff(
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    query = db.query(StaffMember)
    if active_only:
        query = query.filter(StaffMember.active.is_(True))
    return query.order_by(StaffMember.name.asc()).all()


@app.post(
    "/api/staff",
    response_model=StaffResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_auth)],
)
def create_staff(payload: StaffCreate, db: Session = Depends(get_db)):
    existing = db.query(StaffMember).filter(StaffMember.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ein Mitarbeiter mit dem Namen '{payload.name}' existiert bereits.",
        )
    member = StaffMember(**payload.model_dump())
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@app.put("/api/staff/{staff_id}", response_model=StaffResponse, dependencies=[Depends(require_auth)])
def update_staff(staff_id: int, payload: StaffUpdate, db: Session = Depends(get_db)):
    member = db.query(StaffMember).filter(StaffMember.id == staff_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Mitarbeiter nicht gefunden.")

    duplicate = (
        db.query(StaffMember)
        .filter(StaffMember.name == payload.name, StaffMember.id != staff_id)
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail=f"Ein anderer Mitarbeiter mit dem Namen '{payload.name}' existiert bereits.",
        )

    for key, val in payload.model_dump().items():
        setattr(member, key, val)
    db.commit()
    db.refresh(member)
    return member


@app.delete("/api/staff/{staff_id}", dependencies=[Depends(require_auth)])
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    member = db.query(StaffMember).filter(StaffMember.id == staff_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Mitarbeiter nicht gefunden.")
    db.delete(member)
    db.commit()
    return {"deleted": True, "id": staff_id}


# ==============================================================================
# Lieferscheine (Stufe 1, Stufe 2, PDF & E-Mail-Versand)
# ==============================================================================

def _serialize_note(note: DeliveryNote) -> DeliveryNoteResponse:
    resp = DeliveryNoteResponse.model_validate(note)
    resp.total_quantity = sum(item.quantity for item in note.items)
    return resp


def _resolve_school_name(db: Session, school_id: int | None, school_name: str | None) -> tuple[int | None, str]:
    if school_id:
        school = db.query(School).filter(School.id == school_id).first()
        if school:
            return school.id, school.name
    if school_name and school_name.strip():
        return None, school_name.strip()
    raise HTTPException(
        status_code=400,
        detail="Bitte eine gültige Schule auswählen oder einen Schulnamen angeben.",
    )


@app.get(
    "/api/delivery-notes",
    response_model=list[DeliveryNoteResponse],
    dependencies=[Depends(require_auth)],
)
def list_delivery_notes(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(DeliveryNote).options(joinedload(DeliveryNote.items))

    if status_filter:
        statuses = [s.strip().upper() for s in status_filter.split(",") if s.strip()]
        if statuses:
            query = query.filter(DeliveryNote.status.in_(statuses))

    if search and search.strip():
        term = f"%{search.strip()}%"
        matching_item_note_ids = select(DeliveryItem.delivery_note_id).where(
            or_(
                DeliveryItem.inventory_number.ilike(term),
                DeliveryItem.serial_number.ilike(term),
                DeliveryItem.device_type.ilike(term),
            )
        )
        query = query.filter(
            or_(
                DeliveryNote.delivery_number.ilike(term),
                DeliveryNote.school_name.ilike(term),
                DeliveryNote.osticket_number.ilike(term),
                DeliveryNote.ordered_by.ilike(term),
                DeliveryNote.room.ilike(term),
                DeliveryNote.received_by.ilike(term),
                DeliveryNote.delivered_by.ilike(term),
                DeliveryNote.notes.ilike(term),
                DeliveryNote.id.in_(matching_item_note_ids),
            )
        )

    notes = query.order_by(DeliveryNote.created_at.desc(), DeliveryNote.id.desc()).all()
    return [_serialize_note(n) for n in notes]


@app.get(
    "/api/delivery-notes/{note_id}",
    response_model=DeliveryNoteResponse,
    dependencies=[Depends(require_auth)],
)
def get_delivery_note(note_id: int, db: Session = Depends(get_db)):
    note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")
    return _serialize_note(note)


@app.post(
    "/api/delivery-notes",
    response_model=DeliveryNoteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_auth)],
)
def create_delivery_note(payload: DeliveryNoteSaveRequest, db: Session = Depends(get_db)):
    school_id, resolved_school_name = _resolve_school_name(db, payload.school_id, payload.school_name)
    delivery_number = generate_next_delivery_number(db)

    note = DeliveryNote(
        delivery_number=delivery_number,
        status=payload.status,
        school_id=school_id,
        school_name=resolved_school_name,
        recipient_email=payload.recipient_email,
        cc_email=payload.cc_email.strip() if payload.cc_email else None,
        osticket_number=payload.osticket_number,
        ordered_by=payload.ordered_by.strip() if payload.ordered_by else None,
        room=payload.room.strip() if payload.room else None,
        supplier=payload.supplier.strip() if payload.supplier else None,
        invoice_number=payload.invoice_number.strip() if payload.invoice_number else None,
        notes=payload.notes.strip() if payload.notes else None,
        email_osticket_status="AUSSTEHEND" if payload.osticket_number else "KEIN_TICKET",
    )
    db.add(note)
    db.flush()

    for idx, item_in in enumerate(payload.items, start=1):
        db.add(
            DeliveryItem(
                delivery_note_id=note.id,
                position=idx,
                device_type=item_in.device_type,
                inventory_number=item_in.inventory_number,
                serial_number=item_in.serial_number,
                quantity=item_in.quantity,
            )
        )

    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@app.put(
    "/api/delivery-notes/{note_id}",
    response_model=DeliveryNoteResponse,
    dependencies=[Depends(require_auth)],
)
def update_delivery_note(note_id: int, payload: DeliveryNoteSaveRequest, db: Session = Depends(get_db)):
    note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")
    if note.status == "ABGESCHLOSSEN":
        raise HTTPException(
            status_code=400,
            detail="Abgeschlossene und unterschriebene Lieferscheine können nicht mehr geändert werden.",
        )

    school_id, resolved_school_name = _resolve_school_name(db, payload.school_id, payload.school_name)

    note.status = payload.status
    note.school_id = school_id
    note.school_name = resolved_school_name
    note.recipient_email = payload.recipient_email
    note.cc_email = payload.cc_email.strip() if payload.cc_email else None
    note.osticket_number = payload.osticket_number
    note.ordered_by = payload.ordered_by.strip() if payload.ordered_by else None
    note.room = payload.room.strip() if payload.room else None
    note.supplier = payload.supplier.strip() if payload.supplier else None
    note.invoice_number = payload.invoice_number.strip() if payload.invoice_number else None
    note.notes = payload.notes.strip() if payload.notes else None
    note.email_osticket_status = "AUSSTEHEND" if payload.osticket_number else "KEIN_TICKET"

    # Alte Positionen ersetzen
    db.query(DeliveryItem).filter(DeliveryItem.delivery_note_id == note.id).delete()
    db.flush()

    for idx, item_in in enumerate(payload.items, start=1):
        db.add(
            DeliveryItem(
                delivery_note_id=note.id,
                position=idx,
                device_type=item_in.device_type,
                inventory_number=item_in.inventory_number,
                serial_number=item_in.serial_number,
                quantity=item_in.quantity,
            )
        )

    db.commit()
    db.expire_all()
    updated_note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    return _serialize_note(updated_note)


@app.delete("/api/delivery-notes/{note_id}", dependencies=[Depends(require_auth)])
def delete_delivery_note(note_id: int, db: Session = Depends(get_db)):
    note = db.query(DeliveryNote).filter(DeliveryNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")
    if note.status == "ABGESCHLOSSEN":
        raise HTTPException(
            status_code=400,
            detail="Abgeschlossene Lieferscheine sind archiviert und können nicht gelöscht werden.",
        )
    db.delete(note)
    db.commit()
    return {"deleted": True, "id": note_id}


@app.post(
    "/api/delivery-notes/{note_id}/complete",
    response_model=DeliveryNoteResponse,
    dependencies=[Depends(require_auth)],
)
def complete_delivery_note(
    note_id: int,
    payload: DeliveryNoteCompleteRequest,
    db: Session = Depends(get_db),
):
    note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items), joinedload(DeliveryNote.school))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")
    if note.status == "ABGESCHLOSSEN":
        raise HTTPException(status_code=400, detail="Dieser Lieferschein wurde bereits abgeschlossen.")
    if not note.items:
        raise HTTPException(status_code=400, detail="Ein Lieferschein ohne Gerätepositionen kann nicht abgeschlossen werden.")

    if payload.recipient_email and "@" in payload.recipient_email:
        note.recipient_email = payload.recipient_email.strip()
    if payload.cc_email is not None:
        note.cc_email = payload.cc_email.strip() or None

    note.delivered_by = payload.delivered_by
    note.received_by = payload.received_by
    note.handover_notes = payload.handover_notes.strip() if payload.handover_notes else None
    note.signature_data = payload.signature_data
    note.status = "ABGESCHLOSSEN"
    note.completed_at = datetime.now(timezone.utc)

    # 1. PDF generieren und dauerhaft speichern
    pdf_path = generate_delivery_note_pdf(note)
    note.pdf_filename = pdf_path.name

    # 2. E-Mails (Schule + optional osTicket) fehlertolerant versenden
    dispatch_delivery_note_emails(note, pdf_path)

    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@app.post(
    "/api/delivery-notes/{note_id}/resend-email",
    response_model=DeliveryNoteResponse,
    dependencies=[Depends(require_auth)],
)
def resend_delivery_note_email(note_id: int, db: Session = Depends(get_db)):
    note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items), joinedload(DeliveryNote.school))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")
    if note.status != "ABGESCHLOSSEN":
        raise HTTPException(
            status_code=400,
            detail="E-Mails können nur für abgeschlossene Lieferscheine versendet werden.",
        )

    pdf_path = settings.PDF_STORAGE_DIR / (note.pdf_filename or f"Lieferschein_{note.delivery_number}.pdf")
    if not pdf_path.exists():
        pdf_path = generate_delivery_note_pdf(note)
        note.pdf_filename = pdf_path.name

    dispatch_delivery_note_emails(note, pdf_path)
    db.commit()
    db.refresh(note)
    return _serialize_note(note)


@app.get("/api/delivery-notes/{note_id}/pdf", dependencies=[Depends(require_auth)])
def get_delivery_note_pdf(
    note_id: int,
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items), joinedload(DeliveryNote.school))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")

    if note.pdf_filename:
        pdf_path = settings.PDF_STORAGE_DIR / note.pdf_filename
    else:
        pdf_path = settings.PDF_STORAGE_DIR / f"Lieferschein_{note.delivery_number}.pdf"

    if not pdf_path.exists():
        pdf_path = generate_delivery_note_pdf(note)
        if note.status == "ABGESCHLOSSEN":
            note.pdf_filename = pdf_path.name
            db.commit()

    disposition = "attachment" if download else "inline"
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
        content_disposition_type=disposition,
    )


@app.get("/api/delivery-notes/{note_id}/preview-html", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def preview_delivery_note_html(note_id: int, db: Session = Depends(get_db)):
    note = (
        db.query(DeliveryNote)
        .options(joinedload(DeliveryNote.items), joinedload(DeliveryNote.school))
        .filter(DeliveryNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Lieferschein nicht gefunden.")
    return HTMLResponse(content=render_delivery_note_html(note))


@app.get("/", response_class=HTMLResponse)
def serve_spa():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(
        content=index_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
