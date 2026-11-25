import base64
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Test-Umgebung mit isoliertem temporärem Datenverzeichnis konfigurieren
_tmp_dir = tempfile.mkdtemp(prefix="it_lieferschein_test_")
os.environ["DATA_DIR"] = _tmp_dir
os.environ["PDF_STORAGE_DIR"] = str(Path(_tmp_dir) / "pdfs")
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(_tmp_dir) / 'test.db').as_posix()}"
os.environ["SMTP_ENABLED"] = "false"
os.environ["OSTICKET_EMAIL"] = ""
os.environ["AUTH_ENABLED"] = "true"
os.environ["SECRET_KEY"] = "test-only-static-key-for-pytest-suite-12345"

from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, SessionLocal, engine, get_runtime_settings, init_db_and_seed
from app.email_service import _build_osticket_email, _build_school_email
from app.main import _clear_rate_limiters, app
from app.models import DeliveryItem, DeliveryNote, SystemSetting, User
from app.pdf_service import format_dt_german

# Gültiges 1x1 PNG mit gültigem PNG-Magic-Header
SAMPLE_SIGNATURE_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def isolated_database():
    """Stellt für jeden Test eine saubere, frisch geseedete SQLite-DB & PDF-Ablage bereit."""
    _clear_rate_limiters()
    Base.metadata.drop_all(bind=engine)
    pdf_dir = Path(settings.PDF_STORAGE_DIR)
    if pdf_dir.exists():
        for pdf_file in pdf_dir.glob("*.pdf"):
            pdf_file.unlink()
    init_db_and_seed()
    yield
    _clear_rate_limiters()


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("it_ls_csrf")
    return {"X-CSRF-Token": token} if token else {}


def _setup_admin(
    client: TestClient,
    username: str = "admin",
    password: str = "secretPassword123",
    pin: str | None = "9876",
) -> dict:
    res = client.post(
        "/api/auth/setup",
        json={
            "username": username,
            "full_name": "Julian Admin",
            "email": "admin@schulen.example",
            "password": password,
            "pin": pin,
            "add_to_staff_list": True,
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_pre_setup_lockout_and_status_redaction():
    """Vor Abschluss der Ersteinrichtung müssen alle Daten-/Admin-Routen 401 liefern und /api/auth/status darf keine Interna leaken."""
    with TestClient(app) as client:
        st_res = client.get("/api/auth/status")
        assert st_res.status_code == 200
        st = st_res.json()
        assert st["needs_setup"] is True
        assert st["auth_enabled"] is True
        assert st["authenticated"] is False
        assert "login_users" not in st
        assert st["smtp_host"] == ""
        assert st["osticket_email"] == ""
        assert st["department_contact"] == ""

        # Ungeschützte Datenzugriffe vor Ersteinrichtung blockiert
        for method, path in [
            ("GET", "/api/delivery-notes"),
            ("GET", "/api/schools"),
            ("GET", "/api/staff"),
            ("GET", "/api/stats"),
            ("GET", "/api/settings"),
            ("GET", "/api/users"),
            ("POST", "/api/schools"),
        ]:
            resp = client.request(method, path, json={})
            assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"

        # Zu kurzes Passwort beim Setup abgelehnt
        bad_setup = client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "full_name": "Julian Admin",
                "password": "short",
                "pin": "12",
            },
        )
        assert bad_setup.status_code == 422

        setup_data = _setup_admin(client)
        assert "token" not in setup_data
        assert setup_data["authenticated"] is True
        assert "it_ls_token" in client.cookies
        assert "it_ls_csrf" in client.cookies


def test_full_two_stage_workflow_and_security_headers():
    """Prüft den vollständigen 2-Stufen-Workflow, lokale Vendor-Assets, Security Header und UTC-Timestamps."""
    with TestClient(app) as client:
        _setup_admin(client)
        headers = _csrf_headers(client)

        # Health, Favicon & Security Header
        r_health = client.get("/api/health")
        assert r_health.status_code == 200
        assert r_health.headers["x-content-type-options"] == "nosniff"
        assert r_health.headers["x-frame-options"] == "DENY"
        assert "default-src 'self'" in r_health.headers["content-security-policy"]
        assert "'wasm-unsafe-eval'" in r_health.headers["content-security-policy"]

        r_fav = client.get("/favicon.ico")
        assert r_fav.status_code == 200
        assert "svg" in r_fav.headers["content-type"]

        # Lokales Barcode-WASM muss mit application/wasm ausgeliefert werden
        r_wasm = client.get("/static/vendor/zxing_reader.wasm")
        assert r_wasm.status_code == 200
        assert "application/wasm" in r_wasm.headers["content-type"]

        # Frontend nutzt nur lokale Bibliotheken (keine externen CDNs)
        r_spa = client.get("/")
        assert r_spa.status_code == 200
        for forbidden_cdn in ("cdn.tailwindcss.com", "cdn.jsdelivr.net", "unpkg.com"):
            assert forbidden_cdn not in r_spa.text
        assert "/static/vendor/alpine.min.js" in r_spa.text
        assert "/static/vendor/zxing-reader.iife.js" in r_spa.text

        schools = client.get("/api/schools").json()
        assert len(schools) >= 3
        musterschule = next(s for s in schools if "Musterschule" in s["name"])
        staff = client.get("/api/staff").json()
        assert len(staff) >= 2

        # Vorgeseedeter Beispiel-Lieferschein darf keinen pauschalen Header-Lieferanten haben
        existing_notes = client.get("/api/delivery-notes").json()
        assert existing_notes
        assert existing_notes[0]["supplier"] is None
        assert existing_notes[0]["invoice_number"] is None

        # Stufe 1: Lieferschein mit unterschiedlichen Bestellungen/Lieferanten pro Position anlegen
        create_payload = {
            "school_id": musterschule["id"],
            "school_name": musterschule["name"],
            "recipient_email": musterschule["email"],
            "cc_email": musterschule["cc_email"],
            "osticket_number": " # 382814 ",
            "ordered_by": "Fr. Rektorin Müller",
            "room": "Sekretariat EG",
            "notes": "Geräte sind noch nicht eingerichtet, bitte an IT-Lehrkraft weitergeben",
            "status": "ENTWURF",
            "items": [
                {
                    "device_type": "HP ProBook 450 G10",
                    "inventory_number": "INV-2026-9001",
                    "serial_number": "5CD3401XYZ",
                    "supplier": "Bechtle AG",
                    "invoice_number": "RE-991122",
                    "quantity": 1,
                },
                {
                    "device_type": "USB-C Dockingstation G5",
                    "inventory_number": "INV-2026-9002",
                    "serial_number": "",
                    "supplier": "Cancom GmbH",
                    "invoice_number": "RE-884411",
                    "quantity": 1,
                },
            ],
        }
        r_create = client.post("/api/delivery-notes", json=create_payload, headers=headers)
        assert r_create.status_code == 201, r_create.text
        note = r_create.json()
        assert note["status"] == "ENTWURF"
        assert note["osticket_number"] == "382814"
        assert note["total_quantity"] == 2
        assert note["created_at"].endswith("Z") or note["created_at"].endswith("+00:00")
        assert note["items"][0]["supplier"] == "Bechtle AG"
        assert note["items"][1]["invoice_number"] == "RE-884411"
        note_id = note["id"]

        # Stufe 1b: Auf BEREIT setzen und nach Lieferant/Inventarnummer suchen
        create_payload["status"] = "BEREIT"
        r_update = client.put(f"/api/delivery-notes/{note_id}", json=create_payload, headers=headers)
        assert r_update.status_code == 200
        assert r_update.json()["status"] == "BEREIT"

        r_search = client.get("/api/delivery-notes?status=BEREIT&search=Cancom")
        assert r_search.status_code == 200
        assert any(n["id"] == note_id for n in r_search.json())

        # Stufe 2: Quittieren & abschließen (inkl. Manipulationsversuch auf recipient_email ignorieren)
        r_complete = client.post(
            f"/api/delivery-notes/{note_id}/complete",
            headers=headers,
            json={
                "delivered_by": staff[0]["name"],
                "received_by": "Hr. Mayer (Hausmeister)",
                "handover_notes": "Abgegeben bei Hausmeister Hr. Mayer im Erdgeschoss",
                "signature_data": SAMPLE_SIGNATURE_PNG,
                "recipient_email": "attacker@evil.example",
            },
        )
        assert r_complete.status_code == 200, r_complete.text
        completed = r_complete.json()
        assert completed["status"] == "ABGESCHLOSSEN"
        assert completed["recipient_email"] == musterschule["email"]
        assert completed["completed_at"].endswith("Z") or completed["completed_at"].endswith("+00:00")
        assert completed["email_school_status"] == "SIMULIERT"

        # PDF-Abruf prüfen
        r_pdf = client.get(f"/api/delivery-notes/{note_id}/pdf")
        assert r_pdf.status_code == 200
        assert r_pdf.headers["content-type"] == "application/pdf"
        assert r_pdf.content.startswith(b"%PDF")

        # E-Mail erneut senden prüfen
        r_resend = client.post(f"/api/delivery-notes/{note_id}/resend-email", headers=headers)
        assert r_resend.status_code == 200

        # Schutz abgeschlossener Lieferscheine gegen Löschen
        r_del_blocked = client.delete(f"/api/delivery-notes/{note_id}", headers=headers)
        assert r_del_blocked.status_code == 400


def test_osticket_subject_format_and_crlf_protection():
    """Prüft das exakt geforderte osTicket-Betreff-Format sowie Schutz gegen E-Mail-Header-Injection."""
    dummy_note = DeliveryNote(
        delivery_number="LS-2026-0001",
        school_name="Musterschule Nord GS",
        recipient_email="sekretariat@musterschule-nord.schule.example",
        osticket_number="382814",
        delivered_by="Max Mustermann",
        received_by="Fr. Müller",
    )
    dummy_note.items = [
        DeliveryItem(
            position=1,
            device_type="Apple iPad 10",
            inventory_number="INV-100",
            supplier="Bechtle AG",
            invoice_number="RE-2026-12",
            quantity=1,
        )
    ]
    msg = _build_osticket_email(dummy_note, b"%PDF-1.4 dummy", "Lieferschein_LS-2026-0001.pdf")
    assert msg["Subject"] == "[#382814] Lieferschein LS-2026-0001 - Musterschule Nord GS"
    plain_parts = [
        p.get_payload(decode=True).decode("utf-8", errors="ignore")
        for p in msg.walk()
        if p.get_content_type() == "text/plain"
    ]
    body_text = "\n".join(plain_parts)
    assert "Bechtle AG" in body_text
    assert "RE-2026-12" in body_text

    school_msg = _build_school_email(dummy_note, b"%PDF-1.4 dummy", "Lieferschein_LS-2026-0001.pdf")
    assert "LS-2026-0001" in school_msg["Subject"]
    assert "Musterschule Nord GS" in school_msg["Subject"]

    with TestClient(app) as client:
        _setup_admin(client)
        headers = _csrf_headers(client)
        schools = client.get("/api/schools").json()

        bad_crlf = client.post(
            "/api/delivery-notes",
            headers=headers,
            json={
                "school_id": schools[0]["id"],
                "recipient_email": "ok@schulen.example",
                "ordered_by": "Max\r\nBcc: evil@attacker.example",
                "status": "BEREIT",
                "items": [{"device_type": "Laptop", "inventory_number": "INV-1", "quantity": 1}],
            },
        )
        assert bad_crlf.status_code == 422

        bad_email = client.post(
            "/api/schools",
            headers=headers,
            json={"name": "Testschule", "email": "not-an-email"},
        )
        assert bad_email.status_code == 422


def test_smtp_fault_tolerance_and_resend(monkeypatch):
    """Prüft, dass ein SMTP-Fehler den Abschluss nicht blockiert, sondern als FEHLER protokolliert wird."""
    import app.email_service as email_srv

    def _fail_smtp(msg, cfg=None):
        raise ConnectionRefusedError("Exchange-Relay 10.0.0.25:587 nicht erreichbar")

    monkeypatch.setattr(email_srv, "_send_raw_email", _fail_smtp)

    with TestClient(app) as client:
        _setup_admin(client)
        headers = _csrf_headers(client)

        r_put_cfg = client.put(
            "/api/settings",
            headers=headers,
            json={
                "app_title": "Schul-IT Lieferschein",
                "department_name": "Stadtverwaltung – Schul-IT",
                "department_subtitle": "Amt für Bildung und Sport",
                "department_contact": "schul-it@schulen.example",
                "auth_enabled": True,
                "smtp_enabled": True,
                "smtp_host": "mail.schulen.example",
                "smtp_port": 587,
                "smtp_security": "starttls",
                "smtp_username": "",
                "smtp_password": "",
                "smtp_from_email": "lieferschein@schulen.example",
                "smtp_from_name": "Schul-IT",
                "osticket_enabled": True,
                "osticket_email": "tickets@schulen.example",
                "global_archive_cc_email": "",
            },
        )
        assert r_put_cfg.status_code == 200

        ready_notes = client.get("/api/delivery-notes?status=BEREIT").json()
        assert len(ready_notes) >= 1
        target_id = ready_notes[0]["id"]

        r_comp = client.post(
            f"/api/delivery-notes/{target_id}/complete",
            headers=headers,
            json={
                "delivered_by": "Lukas Weber",
                "received_by": "Fr. Schneider",
                "handover_notes": "Übergabe im Sekretariat",
                "signature_data": SAMPLE_SIGNATURE_PNG,
            },
        )
        assert r_comp.status_code == 200
        data = r_comp.json()
        assert data["status"] == "ABGESCHLOSSEN"
        assert data["email_school_status"] == "FEHLER"
        assert "nicht erreichbar" in (data["email_school_error"] or "")
        assert data["email_osticket_status"] == "FEHLER"

        monkeypatch.setattr(email_srv, "_send_raw_email", lambda msg, cfg=None: None)
        r_resend = client.post(f"/api/delivery-notes/{target_id}/resend-email", headers=headers)
        assert r_resend.status_code == 200
        resent = r_resend.json()
        assert resent["email_school_status"] == "VERSENDET"
        assert resent["email_osticket_status"] == "VERSENDET"


def test_auth_rbac_pin_login_csrf_sessions_and_ratelimit():
    """Prüft Benutzerverwaltung, Username+PIN, PIN-Kollisionsschutz, CSRF, RBAC auch bei auth_enabled=false & Rate-Limits."""
    with TestClient(app) as client:
        _setup_admin(client)
        admin_headers = _csrf_headers(client)

        # 1. CSRF-Schutz erzwingen (authentifiziert ohne X-CSRF-Token -> 403)
        r_no_csrf = client.post(
            "/api/schools",
            json={"name": "Ohne CSRF", "email": "test@schulen.example"},
        )
        assert r_no_csrf.status_code == 403

        # 2. Cross-Origin-Schutz auf Login
        r_bad_origin = client.post(
            "/api/auth/login",
            headers={"Origin": "https://evil.attacker.example"},
            json={"username": "admin", "pin_or_password": "secretPassword123"},
        )
        assert r_bad_origin.status_code == 403

        # 3. Zwei Mitarbeiter anlegen (azubi1 ohne Passwort mit PIN, azubi2 mit gleicher PIN)
        r_u1 = client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "username": "azubi1",
                "full_name": "Tim Azubi",
                "email": "tim@schulen.example",
                "role": "staff",
                "password": "",
                "pin": "4321",
                "active": True,
                "add_to_staff_list": True,
            },
        )
        assert r_u1.status_code == 201, r_u1.text
        u1 = r_u1.json()
        assert u1["has_password"] is False
        assert u1["has_pin"] is True

        # Sicherstellen, dass die PIN NICHT in password_hash dupliziert wurde
        with SessionLocal() as db:
            db_u1 = db.query(User).filter(User.id == u1["id"]).first()
            assert db_u1.password_hash == ""

        # Letzten Admin nicht selbst herabstufen oder deaktivieren lassen
        admin_me = client.get("/api/auth/status").json()["current_user"]
        r_self_demote = client.put(
            f"/api/users/{admin_me['id']}",
            headers=admin_headers,
            json={
                "username": admin_me["username"],
                "full_name": admin_me["full_name"],
                "email": admin_me["email"],
                "role": "staff",
                "active": True,
            },
        )
        assert r_self_demote.status_code == 400

        # Zweiten Staff mit gleicher PIN anlegen
        r_u2 = client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "username": "azubi2",
                "full_name": "Lisa Azubi",
                "role": "staff",
                "password": "lisaPassword123",
                "pin": "4321",
                "active": True,
                "add_to_staff_list": False,
            },
        )
        assert r_u2.status_code == 201

        # auth_enabled auf false setzen und prüfen, dass /api/settings weiterhin Admin erfordert
        r_cfg = client.put(
            "/api/settings",
            headers=admin_headers,
            json={
                "app_title": "Schul-IT Lieferschein",
                "department_name": "Stadtverwaltung – Schul-IT",
                "department_subtitle": "",
                "department_contact": "",
                "auth_enabled": False,
                "smtp_enabled": False,
                "smtp_host": "",
                "smtp_port": 587,
                "smtp_security": "starttls",
                "smtp_username": "",
                "smtp_password": "",
                "smtp_from_email": "",
                "smtp_from_name": "Schul-IT",
                "osticket_enabled": False,
                "osticket_email": "",
                "global_archive_cc_email": "",
            },
        )
        assert r_cfg.status_code == 200

    # Separater Kiosk-Client (ohne Cookie) wenn auth_enabled=false
    with TestClient(app) as kiosk_client:
        assert kiosk_client.get("/api/delivery-notes").status_code == 200
        assert kiosk_client.get("/api/settings").status_code == 401
        assert kiosk_client.get("/api/users").status_code == 401

    # Separater HTTPS-Client prüft Secure-Cookie-Flag und Staff-RBAC (403)
    with TestClient(app, base_url="https://testserver") as https_staff_client:
        r_https_login = https_staff_client.post(
            "/api/auth/login",
            json={"username": "azubi1", "pin_or_password": "4321"},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert r_https_login.status_code == 200
        assert "Secure" in r_https_login.headers.get("set-cookie", "")
        assert https_staff_client.get("/api/settings").status_code == 403

    # Separater Staff-Client: Username+PIN muss funktionieren, PIN-only bei Kollision wird abgelehnt
    with TestClient(app) as staff_client:
        r_ambig = staff_client.post(
            "/api/auth/login",
            json={"username": None, "pin_or_password": "4321"},
        )
        assert r_ambig.status_code == 401

        r_login = staff_client.post(
            "/api/auth/login",
            json={"username": "azubi1", "pin_or_password": "4321"},
        )
        assert r_login.status_code == 200
        assert r_login.json()["user"]["username"] == "azubi1"

        # Staff darf keine Admin-Endpunkte aufrufen -> 403
        assert staff_client.get("/api/settings").status_code == 403
        assert staff_client.get("/api/users").status_code == 403

        # Admin ändert azubi1 -> dessen Session wird sofort invalidiert
        with TestClient(app) as admin_client:
            admin_client.post("/api/auth/login", json={"username": "admin", "pin_or_password": "secretPassword123"})
            ah = _csrf_headers(admin_client)
            r_clear_fail = admin_client.put(
                f"/api/users/{u1['id']}",
                headers=ah,
                json={
                    "username": "azubi1",
                    "full_name": "Tim Azubi",
                    "role": "staff",
                    "clear_pin": True,
                    "active": True,
                },
            )
            assert r_clear_fail.status_code == 400

            r_upd = admin_client.put(
                f"/api/users/{u1['id']}",
                headers=ah,
                json={
                    "username": "azubi1",
                    "full_name": "Tim Azubi",
                    "role": "staff",
                    "password": "newAzubiPassword123",
                    "clear_pin": True,
                    "active": True,
                },
            )
            assert r_upd.status_code == 200
            assert r_upd.json()["has_password"] is True
            assert r_upd.json()["has_pin"] is False

        # Bisherige Staff-Session darf nach Passwort-/PIN-Änderung nicht mehr gültig sein (401/403 je auth_enabled, User ist ausgeloggt)
        st_after = staff_client.get("/api/auth/status").json()
        assert st_after["current_user"] is None

        # Rate-Limiter testen (10 fehlgeschlagene Logins -> 429)
        for _ in range(10):
            r_fail = staff_client.post(
                "/api/auth/login",
                json={"username": "admin", "pin_or_password": "wrongPassword99"},
            )
            assert r_fail.status_code == 401
        r_limited = staff_client.post(
            "/api/auth/login",
            json={"username": "admin", "pin_or_password": "wrongPassword99"},
        )
        assert r_limited.status_code == 429


def test_smtp_encryption_png_validation_and_berlin_timezone():
    """Prüft Verschlüsselung des SMTP-Passworts in SQLite, PNG-Signaturprüfung und UTC->Berlin-Umrechnung."""
    # 1. Zeitzonen-Umrechnung (naive UTC aus SQLite -> Europe/Berlin Sommer- & Winterzeit)
    assert format_dt_german(datetime(2026, 7, 15, 12, 0)) == "15.07.2026 um 14:00 Uhr"
    assert format_dt_german(datetime(2026, 1, 15, 12, 0)) == "15.01.2026 um 13:00 Uhr"

    with TestClient(app) as client:
        _setup_admin(client)
        headers = _csrf_headers(client)

        # 2. SMTP-Passwort muss verschlüsselt (enc:v1:...) in DB gespeichert werden
        r_cfg = client.put(
            "/api/settings",
            headers=headers,
            json={
                "app_title": "Schul-IT Lieferschein",
                "department_name": "Stadtverwaltung – Schul-IT",
                "department_subtitle": "",
                "department_contact": "",
                "auth_enabled": True,
                "smtp_enabled": True,
                "smtp_host": "mail.schulen.example",
                "smtp_port": 587,
                "smtp_security": "starttls",
                "smtp_username": "mailer",
                "smtp_password": "SuperSecretSmtpPassword!",
                "smtp_from_email": "ls@schulen.example",
                "smtp_from_name": "Schul-IT",
                "osticket_enabled": False,
                "osticket_email": "",
                "global_archive_cc_email": "",
            },
        )
        assert r_cfg.status_code == 200
        assert r_cfg.json()["smtp_password_set"] is True
        assert "smtp_password" not in r_cfg.json()

        with SessionLocal() as db:
            raw_row = db.query(SystemSetting).filter(SystemSetting.key == "smtp_password").first()
            assert raw_row is not None
            assert raw_row.value.startswith("enc:v1:")
            assert "SuperSecretSmtpPassword!" not in raw_row.value
            decrypted = get_runtime_settings(db)["smtp_password"]
            assert decrypted == "SuperSecretSmtpPassword!"

        # 3. Gefälschte / ungültige Signaturdaten (kein echter PNG-Header) ablehnen
        ready_notes = client.get("/api/delivery-notes?status=BEREIT").json()
        target_id = ready_notes[0]["id"]
        fake_png = "data:image/png;base64," + base64.b64encode(b"NOT_A_PNG_PAYLOAD").decode("ascii")
        r_bad_sig = client.post(
            f"/api/delivery-notes/{target_id}/complete",
            headers=headers,
            json={
                "delivered_by": "Max Mustermann",
                "received_by": "Fr. Test",
                "signature_data": fake_png,
            },
        )
        assert r_bad_sig.status_code == 422


def test_bulk_40_ipads_delivery_note_and_search():
    """Prüft Lieferscheine mit 40 Einzelpositionen (Rollout z. B. EDV-00120..EDV-00159), Suche und PDF-Erzeugung."""
    with TestClient(app) as client:
        _setup_admin(client)
        headers = _csrf_headers(client)
        schools = client.get("/api/schools").json()

        items = [
            {
                "device_type": "Apple iPad 10. Gen 64GB",
                "inventory_number": f"EDV-{120 + i:05d}",
                "serial_number": f"DMQTEST{1000 + i}",
                "supplier": "Bechtle AG",
                "invoice_number": "RE-2026-400",
                "quantity": 1,
            }
            for i in range(40)
        ]

        r_create = client.post(
            "/api/delivery-notes",
            headers=headers,
            json={
                "school_id": schools[0]["id"],
                "recipient_email": schools[0]["email"],
                "osticket_number": "401122",
                "status": "BEREIT",
                "items": items,
            },
        )
        assert r_create.status_code == 201, r_create.text
        created = r_create.json()
        assert created["total_quantity"] == 40
        assert len(created["items"]) == 40
        assert created["items"][0]["inventory_number"] == "EDV-00120"
        assert created["items"][39]["inventory_number"] == "EDV-00159"

        # Einzelne mittlere Inventar- & Seriennummer muss über Archiv-/Bestandssuche auffindbar sein
        r_search_inv = client.get("/api/delivery-notes?status=BEREIT&search=EDV-00137")
        assert any(n["id"] == created["id"] for n in r_search_inv.json())
        r_search_sn = client.get("/api/delivery-notes?status=BEREIT&search=DMQTEST1025")
        assert any(n["id"] == created["id"] for n in r_search_sn.json())

        r_complete = client.post(
            f"/api/delivery-notes/{created['id']}/complete",
            headers=headers,
            json={
                "delivered_by": "Julian Admin",
                "received_by": "Schulsekretariat",
                "signature_data": SAMPLE_SIGNATURE_PNG,
            },
        )
        assert r_complete.status_code == 200
        assert client.get(f"/api/delivery-notes/{created['id']}/pdf").content.startswith(b"%PDF")
