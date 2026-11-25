import base64
import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import (
    generate_next_delivery_number,
    get_db,
    get_runtime_settings,
    init_db_and_seed,
    set_runtime_settings,
)
from app.email_service import dispatch_delivery_note_emails, send_test_email
from app.models import DeliveryItem, DeliveryNote, School, StaffMember, User, UserSession
from app.pdf_service import generate_delivery_note_pdf, render_delivery_note_html
from app.schemas import (
    DeliveryNoteCompleteRequest,
    DeliveryNoteResponse,
    DeliveryNoteSaveRequest,
    InitialSetupRequest,
    LoginRequest,
    SchoolCreate,
    SchoolResponse,
    SchoolUpdate,
    SmtpTestRequest,
    StaffCreate,
    StaffResponse,
    StaffUpdate,
    SystemSettingsUpdateRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db_and_seed()
    yield


app = FastAPI(
    title=settings.APP_TITLE,
    description="Selbstgehostete Webanwendung für digitale IT-Lieferscheine (Schul-IT)",
    version="1.1.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ==============================================================================
# Passwort-/PIN-Hashing (PBKDF2-HMAC-SHA256) & Session-Management
# ==============================================================================

def hash_secret(secret: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_secret(secret: str, stored_hash: str | None) -> bool:
    if not stored_hash or not secret:
        return False
    try:
        algo, salt, hex_digest = stored_hash.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("utf-8"), 120_000)
        return hmac.compare_digest(dk.hex(), hex_digest)
    except Exception:
        return False


def _compute_legacy_env_token() -> str:
    secret = f"{settings.AUTH_USERNAME}:{settings.AUTH_PASSWORD}:{settings.AUTH_PIN}"
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _create_user_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=14)
    user.last_login_at = now
    db.add(UserSession(token=token, user_id=user.id, created_at=now, expires_at=expires))
    db.commit()
    return token


def _serialize_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        has_pin=bool(user.pin_hash),
        active=user.active,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _get_current_user_optional(request: Request, db: Session) -> User | None:
    now = datetime.now(timezone.utc)
    candidate_tokens = [
        request.headers.get("X-Auth-Token", "").strip(),
        request.cookies.get("it_ls_token", "").strip(),
    ]
    for token in candidate_tokens:
        if not token:
            continue
        session_row = (
            db.query(UserSession)
            .options(joinedload(UserSession.user))
            .filter(UserSession.token == token)
            .first()
        )
        if session_row and session_row.user and session_row.user.active:
            exp = session_row.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                return session_row.user

    # HTTP Basic Auth prüfen
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = decoded.split(":", 1)
            uname = username.strip().lower()
            active_users = db.query(User).filter(User.active.is_(True)).all()
            for u in active_users:
                if u.username.lower() == uname or u.full_name.lower() == uname:
                    if verify_secret(password, u.password_hash) or verify_secret(password, u.pin_hash):
                        return u
        except Exception:
            pass

    return None


def _is_auth_enforced(db: Session) -> bool:
    """
    Prüft, ob die Anmeldung aktuell erzwungen wird:
    - Sobald mindestens ein lokaler Benutzer in der DB existiert UND auth_enabled in den Settings aktiv ist -> True
    - Oder wenn AUTH_ENABLED=true explizit in der .env gesetzt ist -> True
    """
    if settings.AUTH_ENABLED:
        return True
    user_count = db.query(User).count()
    if user_count == 0:
        return False
    cfg = get_runtime_settings(db)
    return cfg.get("auth_enabled", "true").lower() == "true"


def require_auth(request: Request, db: Session = Depends(get_db)) -> User | None:
    user = _get_current_user_optional(request, db)
    if user is not None:
        return user

    if not _is_auth_enforced(db):
        return None

    # Fallback auf .env-Token falls noch gar keine DB-User existieren
    if db.query(User).count() == 0:
        expected = _compute_legacy_env_token()
        token = request.headers.get("X-Auth-Token", "") or request.cookies.get("it_ls_token", "")
        if token and hmac.compare_digest(token, expected):
            return None

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentifizierung erforderlich. Bitte melden Sie sich an.",
    )


def require_admin(request: Request, db: Session = Depends(get_db)) -> User | None:
    user = require_auth(request, db)
    if user is not None and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Diese Aktion erfordert Administrator-Berechtigungen.",
        )
    return user


# ==============================================================================
# Health, Auth-Status, Ersteinrichtung (Setup) & Login/Logout
# ==============================================================================

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.APP_TITLE}


@app.get("/api/auth/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    cfg = get_runtime_settings(db)
    user_count = db.query(User).count()
    needs_setup = user_count == 0
    auth_enabled = cfg.get("auth_enabled", "true").lower() == "true" or settings.AUTH_ENABLED
    current_user = _get_current_user_optional(request, db)

    is_authenticated = current_user is not None or (not auth_enabled and not needs_setup)

    smtp_host = (cfg.get("smtp_host") or "").strip()
    smtp_enabled = (
        cfg.get("smtp_enabled", "false").lower() == "true"
        and bool(smtp_host)
        and smtp_host != "mail.kommune.local"
    )
    osticket_email = (cfg.get("osticket_email") or "").strip()
    osticket_enabled = (
        cfg.get("osticket_enabled", "false").lower() == "true"
        and bool(osticket_email)
        and osticket_email != "tickets@kommune.local"
    )

    active_users = db.query(User).filter(User.active.is_(True)).order_by(User.full_name.asc()).all()
    login_users_hint = [
        {"username": u.username, "full_name": u.full_name, "has_pin": bool(u.pin_hash)}
        for u in active_users
    ]

    return {
        "needs_setup": needs_setup,
        "auth_enabled": auth_enabled,
        "authenticated": is_authenticated,
        "current_user": _serialize_user(current_user).model_dump() if current_user else None,
        "login_users": login_users_hint,
        "app_title": cfg.get("app_title") or settings.APP_TITLE,
        "department_name": cfg.get("department_name") or settings.DEPARTMENT_NAME,
        "department_subtitle": cfg.get("department_subtitle") or settings.DEPARTMENT_SUBTITLE,
        "department_contact": cfg.get("department_contact") or settings.DEPARTMENT_CONTACT,
        "smtp_enabled": smtp_enabled,
        "smtp_host": smtp_host,
        "osticket_configured": osticket_enabled,
        "osticket_email": osticket_email if osticket_enabled else "",
    }


@app.post("/api/auth/setup")
def initial_setup(payload: InitialSetupRequest, response: Response, db: Session = Depends(get_db)):
    """Ersteinrichtung: Legt das erste Administrator-Konto an, falls noch kein Benutzer existiert."""
    if db.query(User).count() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die Ersteinrichtung wurde bereits abgeschlossen. Bitte melden Sie sich an.",
        )

    pin_clean = payload.pin.strip() if payload.pin and payload.pin.strip() else None
    admin_user = User(
        username=payload.username.strip(),
        full_name=payload.full_name.strip(),
        email=payload.email.strip() if payload.email else None,
        role="admin",
        password_hash=hash_secret(payload.password),
        pin_hash=hash_secret(pin_clean) if pin_clean else None,
        active=True,
    )
    db.add(admin_user)
    db.flush()

    if payload.add_to_staff_list:
        existing_staff = db.query(StaffMember).filter(StaffMember.name == admin_user.full_name).first()
        if not existing_staff:
            db.add(
                StaffMember(
                    name=admin_user.full_name,
                    role="Schul-IT Administration",
                    email=admin_user.email,
                    active=True,
                )
            )

    set_runtime_settings(db, {"auth_enabled": "true"})
    token = _create_user_session(db, admin_user)

    response.set_cookie(
        key="it_ls_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return {
        "authenticated": True,
        "token": token,
        "user": _serialize_user(admin_user),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    secret_in = payload.pin_or_password.strip()
    username_in = payload.username.strip() if payload.username else ""

    matched_user: User | None = None
    active_users = db.query(User).filter(User.active.is_(True)).all()

    if username_in:
        uname_lower = username_in.lower()
        for u in active_users:
            if (
                u.username.lower() == uname_lower
                or u.full_name.lower() == uname_lower
                or (u.email and u.email.lower() == uname_lower)
            ):
                if verify_secret(secret_in, u.pin_hash) or verify_secret(secret_in, u.password_hash):
                    matched_user = u
                    break
    else:
        # Schnell-PIN-Login (oder Passwort) ohne Benutzernamen
        for u in active_users:
            if verify_secret(secret_in, u.pin_hash) or verify_secret(secret_in, u.password_hash):
                matched_user = u
                break

    if not matched_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Anmeldung fehlgeschlagen: Benutzername oder Passwort/PIN ungültig.",
        )

    token = _create_user_session(db, matched_user)
    response.set_cookie(
        key="it_ls_token",
        value=token,
        path="/",
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return {
        "authenticated": True,
        "token": token,
        "user": _serialize_user(matched_user),
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    header_token = request.headers.get("X-Auth-Token", "").strip()
    cookie_token = request.cookies.get("it_ls_token", "").strip()
    tokens_to_remove = [t for t in {header_token, cookie_token} if t]
    if tokens_to_remove:
        # Auch alle anderen Sessions desselben Benutzers beim expliziten Logout bereinigen
        sess_rows = db.query(UserSession).filter(UserSession.token.in_(tokens_to_remove)).all()
        user_ids = {s.user_id for s in sess_rows}
        db.query(UserSession).filter(UserSession.token.in_(tokens_to_remove)).delete(synchronize_session=False)
        if user_ids:
            db.query(UserSession).filter(UserSession.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    response.delete_cookie(key="it_ls_token", path="/", samesite="lax", httponly=True)
    return {"authenticated": False}


# ==============================================================================
# Lokale Benutzerverwaltung (/api/users)
# ==============================================================================

@app.get("/api/users", response_model=list[UserResponse], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.username.asc()).all()
    return [_serialize_user(u) for u in users]


@app.post(
    "/api/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_user(payload: UserCreateRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username.ilike(payload.username.strip())).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ein Benutzer mit dem Benutzernamen '{payload.username}' existiert bereits.",
        )

    pin_clean = payload.pin.strip() if payload.pin and payload.pin.strip() else None
    pw_clean = payload.password.strip() if payload.password and payload.password.strip() else None
    if not pw_clean and not pin_clean:
        raise HTTPException(
            status_code=400,
            detail="Bitte entweder ein Passwort oder eine Schnell-PIN (oder beides) vergeben.",
        )
    effective_pw = pw_clean or pin_clean

    new_user = User(
        username=payload.username.strip(),
        full_name=payload.full_name.strip(),
        email=payload.email.strip() if payload.email else None,
        role=payload.role,
        password_hash=hash_secret(effective_pw),
        pin_hash=hash_secret(pin_clean) if pin_clean else None,
        active=payload.active,
    )
    db.add(new_user)
    db.flush()

    if payload.add_to_staff_list:
        existing_staff = db.query(StaffMember).filter(StaffMember.name == new_user.full_name).first()
        if not existing_staff:
            role_label = "Schul-IT Administration" if new_user.role == "admin" else "Schul-IT Mitarbeiter / Azubi"
            db.add(
                StaffMember(
                    name=new_user.full_name,
                    role=role_label,
                    email=new_user.email,
                    active=True,
                )
            )

    db.commit()
    db.refresh(new_user)
    return _serialize_user(new_user)


@app.put("/api/users/{user_id}", response_model=UserResponse, dependencies=[Depends(require_admin)])
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    current_user: User | None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    dup = (
        db.query(User)
        .filter(User.username.ilike(payload.username.strip()), User.id != user_id)
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="Dieser Benutzername ist bereits vergeben.")

    if current_user and current_user.id == user.id and not payload.active:
        raise HTTPException(status_code=400, detail="Sie können Ihr eigenes Konto nicht deaktivieren.")

    user.username = payload.username.strip()
    user.full_name = payload.full_name.strip()
    user.email = payload.email.strip() if payload.email else None
    user.role = payload.role
    user.active = payload.active

    if payload.password and payload.password.strip():
        user.password_hash = hash_secret(payload.password.strip())

    if payload.clear_pin:
        user.pin_hash = None
    elif payload.pin and payload.pin.strip():
        user.pin_hash = hash_secret(payload.pin.strip())

    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@app.delete("/api/users/{user_id}", dependencies=[Depends(require_admin)])
def delete_user(
    user_id: int,
    current_user: User | None = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
    if current_user and current_user.id == user.id:
        raise HTTPException(status_code=400, detail="Sie können Ihr eigenes Benutzerkonto nicht löschen.")

    admin_count = db.query(User).filter(User.role == "admin", User.active.is_(True)).count()
    if user.role == "admin" and admin_count <= 1:
        raise HTTPException(
            status_code=400,
            detail="Der letzte aktive Administrator kann nicht gelöscht werden.",
        )

    db.delete(user)
    db.commit()
    return {"deleted": True, "id": user_id}


# ==============================================================================
# Systemeinstellungen / Konfigmenü (/api/settings)
# ==============================================================================

@app.get("/api/settings", dependencies=[Depends(require_admin)])
def get_system_settings(db: Session = Depends(get_db)):
    cfg = get_runtime_settings(db)
    has_pw = bool(cfg.get("smtp_password"))
    return {
        "app_title": cfg.get("app_title", settings.APP_TITLE),
        "department_name": cfg.get("department_name", settings.DEPARTMENT_NAME),
        "department_subtitle": cfg.get("department_subtitle", settings.DEPARTMENT_SUBTITLE),
        "department_contact": cfg.get("department_contact", settings.DEPARTMENT_CONTACT),
        "auth_enabled": cfg.get("auth_enabled", "true").lower() == "true",
        "smtp_enabled": cfg.get("smtp_enabled", "false").lower() == "true",
        "smtp_host": cfg.get("smtp_host", ""),
        "smtp_port": int(cfg.get("smtp_port") or 587),
        "smtp_security": cfg.get("smtp_security", "starttls"),
        "smtp_username": cfg.get("smtp_username", ""),
        "smtp_password_set": has_pw,
        "smtp_from_email": cfg.get("smtp_from_email", ""),
        "smtp_from_name": cfg.get("smtp_from_name", "Schul-IT Lieferschein-System"),
        "osticket_enabled": cfg.get("osticket_enabled", "false").lower() == "true",
        "osticket_email": cfg.get("osticket_email", ""),
        "global_archive_cc_email": cfg.get("global_archive_cc_email", ""),
    }


@app.put("/api/settings", dependencies=[Depends(require_admin)])
def update_system_settings(payload: SystemSettingsUpdateRequest, db: Session = Depends(get_db)):
    current = get_runtime_settings(db)
    updates = {
        "app_title": payload.app_title.strip(),
        "department_name": payload.department_name.strip(),
        "department_subtitle": payload.department_subtitle.strip(),
        "department_contact": payload.department_contact.strip(),
        "auth_enabled": "true" if payload.auth_enabled else "false",
        "smtp_enabled": "true" if payload.smtp_enabled else "false",
        "smtp_host": payload.smtp_host.strip(),
        "smtp_port": str(payload.smtp_port),
        "smtp_security": payload.smtp_security,
        "smtp_username": payload.smtp_username.strip(),
        "smtp_from_email": payload.smtp_from_email.strip(),
        "smtp_from_name": payload.smtp_from_name.strip(),
        "osticket_enabled": "true" if payload.osticket_enabled else "false",
        "osticket_email": payload.osticket_email.strip(),
        "global_archive_cc_email": payload.global_archive_cc_email.strip(),
    }
    if payload.smtp_password is not None and payload.smtp_password != "__UNCHANGED__":
        updates["smtp_password"] = payload.smtp_password
    else:
        updates["smtp_password"] = current.get("smtp_password", "")

    set_runtime_settings(db, updates)
    return get_system_settings(db)


@app.post("/api/settings/test-smtp", dependencies=[Depends(require_admin)])
def test_smtp_connection(payload: SmtpTestRequest, db: Session = Depends(get_db)):
    cfg = get_runtime_settings(db)
    try:
        return send_test_email(payload.recipient_email, cfg=cfg)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SMTP-Test fehlgeschlagen: {exc}",
        )


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
                DeliveryItem.supplier.ilike(term),
                DeliveryItem.invoice_number.ilike(term),
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
                supplier=item_in.supplier,
                invoice_number=item_in.invoice_number,
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
                supplier=item_in.supplier,
                invoice_number=item_in.invoice_number,
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

    cfg = get_runtime_settings(db)

    # 1. PDF generieren und dauerhaft speichern
    pdf_path = generate_delivery_note_pdf(note, cfg=cfg)
    note.pdf_filename = pdf_path.name

    # 2. E-Mails (Schule + optional osTicket) fehlertolerant versenden
    dispatch_delivery_note_emails(note, pdf_path, cfg=cfg)

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

    cfg = get_runtime_settings(db)
    pdf_path = settings.PDF_STORAGE_DIR / (note.pdf_filename or f"Lieferschein_{note.delivery_number}.pdf")
    if not pdf_path.exists():
        pdf_path = generate_delivery_note_pdf(note, cfg=cfg)
        note.pdf_filename = pdf_path.name

    dispatch_delivery_note_emails(note, pdf_path, cfg=cfg)
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

    cfg = get_runtime_settings(db)
    if note.pdf_filename:
        pdf_path = settings.PDF_STORAGE_DIR / note.pdf_filename
    else:
        pdf_path = settings.PDF_STORAGE_DIR / f"Lieferschein_{note.delivery_number}.pdf"

    if not pdf_path.exists():
        pdf_path = generate_delivery_note_pdf(note, cfg=cfg)
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
    cfg = get_runtime_settings(db)
    return HTMLResponse(content=render_delivery_note_html(note, cfg=cfg))


@app.get("/", response_class=HTMLResponse)
def serve_spa():
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(
        content=index_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
