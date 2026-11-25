import os
import tempfile
from pathlib import Path

# Test-Umgebung mit temporärem Datenverzeichnis konfigurieren
_tmp_dir = tempfile.mkdtemp(prefix="it_lieferschein_test_")
os.environ["DATA_DIR"] = _tmp_dir
os.environ["PDF_STORAGE_DIR"] = str(Path(_tmp_dir) / "pdfs")
os.environ["DATABASE_URL"] = f"sqlite:///{(Path(_tmp_dir) / 'test.db').as_posix()}"
os.environ["SMTP_ENABLED"] = "false"
os.environ["OSTICKET_EMAIL"] = "tickets@kommune.local"
os.environ["AUTH_ENABLED"] = "false"

from fastapi.testclient import TestClient
from app.main import app
from app.email_service import _build_osticket_email, _build_school_email
from app.models import DeliveryNote, DeliveryItem


SAMPLE_SIGNATURE_PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_full_two_stage_workflow():
    with TestClient(app) as client:
        # 1. Health & Initial Seed prüfen
        r_health = client.get("/api/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "ok"

        r_schools = client.get("/api/schools")
        assert r_schools.status_code == 200
        schools = r_schools.json()
        assert len(schools) >= 3
        musterschule = next(s for s in schools if "Musterschule" in s["name"])

        r_staff = client.get("/api/staff")
        assert r_staff.status_code == 200
        staff = r_staff.json()
        assert len(staff) >= 2

        # 2. Stufe 1: Neuen Lieferschein als ENTWURF anlegen (inkl. osTicket-Bereinigung von '# 382814 ')
        create_payload = {
            "school_id": musterschule["id"],
            "school_name": musterschule["name"],
            "recipient_email": musterschule["email"],
            "cc_email": musterschule["cc_email"],
            "osticket_number": " # 382814 ",
            "ordered_by": "Fr. Rektorin Müller",
            "room": "Sekretariat EG",
            "supplier": "Bechtle AG",
            "invoice_number": "RE-991122",
            "notes": "Geräte sind noch nicht eingerichtet, bitte an IT-Lehrkraft weitergeben",
            "status": "ENTWURF",
            "items": [
                {
                    "device_type": "HP ProBook 450 G10",
                    "inventory_number": "INV-2026-9001",
                    "serial_number": "5CD3401XYZ",
                    "quantity": 1,
                },
                {
                    "device_type": "USB-C Dockingstation G5",
                    "inventory_number": "INV-2026-9002",
                    "serial_number": "",
                    "quantity": 1,
                },
            ],
        }
        r_create = client.post("/api/delivery-notes", json=create_payload)
        assert r_create.status_code == 201, r_create.text
        note = r_create.json()
        assert note["status"] == "ENTWURF"
        assert note["osticket_number"] == "382814"  # Automatisch von '#' und Leerzeichen bereinigt
        assert note["total_quantity"] == 2
        note_id = note["id"]

        # 3. Stufe 1b: Lieferschein bearbeiten und zur Auslieferung freigeben (Status -> BEREIT)
        create_payload["status"] = "BEREIT"
        r_update = client.put(f"/api/delivery-notes/{note_id}", json=create_payload)
        assert r_update.status_code == 200
        assert r_update.json()["status"] == "BEREIT"

        # Suche nach Inventarnummer in offenen Auslieferungen testen
        r_search = client.get("/api/delivery-notes?status=BEREIT&search=INV-2026-9001")
        assert r_search.status_code == 200
        assert any(n["id"] == note_id for n in r_search.json())

        # 4. Stufe 2: Vor Ort digital unterschreiben & abschließen (Status -> ABGESCHLOSSEN)
        complete_payload = {
            "delivered_by": staff[0]["name"],
            "received_by": "Hr. Mayer (Hausmeister)",
            "handover_notes": "Abgegeben bei Hausmeister Hr. Mayer im Erdgeschoss",
            "signature_data": SAMPLE_SIGNATURE_PNG,
        }
        r_complete = client.post(f"/api/delivery-notes/{note_id}/complete", json=complete_payload)
        assert r_complete.status_code == 200, r_complete.text
        completed = r_complete.json()
        assert completed["status"] == "ABGESCHLOSSEN"
        assert completed["received_by"] == "Hr. Mayer (Hausmeister)"
        assert completed["pdf_filename"].endswith(".pdf")
        assert completed["email_school_status"] == "SIMULIERT"
        assert completed["email_osticket_status"] == "SIMULIERT"

        # 5. PDF-Abruf prüfen
        r_pdf = client.get(f"/api/delivery-notes/{note_id}/pdf")
        assert r_pdf.status_code == 200
        assert r_pdf.headers["content-type"] == "application/pdf"
        assert r_pdf.content.startswith(b"%PDF")

        # 6. E-Mail erneut senden prüfen
        r_resend = client.post(f"/api/delivery-notes/{note_id}/resend-email")
        assert r_resend.status_code == 200
        assert r_resend.json()["email_school_status"] == "SIMULIERT"

        # 7. Schutz abgeschlossener Lieferscheine gegen Löschen/Bearbeiten prüfen
        r_del_blocked = client.delete(f"/api/delivery-notes/{note_id}")
        assert r_del_blocked.status_code == 400


def test_osticket_subject_format():
    """Prüft das exakt geforderte osTicket-Betreff-Format: [#<TICKETNUMMER>] Lieferschein <LS-NR> - <Schule>"""
    dummy_note = DeliveryNote(
        delivery_number="LS-2026-0001",
        school_name="Musterschule Nord GS",
        recipient_email="sekretariat@musterschule-nord.schule.local",
        osticket_number="382814",
        delivered_by="Max Mustermann",
        received_by="Fr. Müller",
    )
    dummy_note.items = [
        DeliveryItem(
            position=1,
            device_type="Apple iPad 10",
            inventory_number="INV-100",
            quantity=1,
        )
    ]
    msg = _build_osticket_email(dummy_note, b"%PDF-1.4 dummy", "Lieferschein_LS-2026-0001.pdf")
    assert msg["Subject"] == "[#382814] Lieferschein LS-2026-0001 - Musterschule Nord GS"

    school_msg = _build_school_email(dummy_note, b"%PDF-1.4 dummy", "Lieferschein_LS-2026-0001.pdf")
    assert "LS-2026-0001" in school_msg["Subject"]
    assert "Musterschule Nord GS" in school_msg["Subject"]


def test_smtp_fault_tolerance_and_resend(monkeypatch):
    """Prüft, dass ein SMTP-Fehler den Abschluss nicht blockiert, sondern als FEHLER protokolliert wird."""
    from app.config import settings
    import app.email_service as email_srv

    monkeypatch.setattr(settings, "SMTP_ENABLED", True)

    def _fail_smtp(msg, cfg=None):
        raise ConnectionRefusedError("Exchange-Relay 10.0.0.25:587 nicht erreichbar")

    monkeypatch.setattr(email_srv, "_send_raw_email", _fail_smtp)

    with TestClient(app) as client:
        r_ready = client.get("/api/delivery-notes?status=BEREIT")
        ready_notes = r_ready.json()
        assert len(ready_notes) >= 1
        target_id = ready_notes[0]["id"]

        r_comp = client.post(
            f"/api/delivery-notes/{target_id}/complete",
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

        # Nun SMTP wieder funktionsfähig machen und erneut senden
        monkeypatch.setattr(email_srv, "_send_raw_email", lambda msg, cfg=None: None)
        r_resend = client.post(f"/api/delivery-notes/{target_id}/resend-email")
        assert r_resend.status_code == 200
        resent = r_resend.json()
        assert resent["email_school_status"] == "VERSENDET"
        assert resent["email_osticket_status"] == "VERSENDET"


def test_setup_user_management_and_settings_menu():
    """Prüft Ersteinrichtung, Login (Passwort & Schnell-PIN), Benutzerverwaltung und Konfigmenü."""
    with TestClient(app) as client:
        # 1. Vor dem Setup steht needs_setup auf True
        st = client.get("/api/auth/status").json()
        assert st["needs_setup"] is True

        # 2. Ersteinrichtung (Initiales Admin-Konto anlegen)
        r_setup = client.post(
            "/api/auth/setup",
            json={
                "username": "admin",
                "full_name": "Julian Admin",
                "email": "admin@kommune.local",
                "password": "secretPassword123",
                "pin": "9876",
                "add_to_staff_list": True,
            },
        )
        assert r_setup.status_code == 200, r_setup.text
        setup_data = r_setup.json()
        token = setup_data["token"]
        headers = {"X-Auth-Token": token}

        # 3. Konfigmenü (/api/settings) abrufen und ändern
        r_get_cfg = client.get("/api/settings", headers=headers)
        assert r_get_cfg.status_code == 200

        r_put_cfg = client.put(
            "/api/settings",
            headers=headers,
            json={
                "app_title": "Schul-IT Lieferschein",
                "department_name": "Stadtverwaltung – Schul-IT",
                "department_subtitle": "Amt für Bildung und Sport",
                "department_contact": "schul-it@kommune.local",
                "auth_enabled": True,
                "smtp_enabled": False,
                "smtp_host": "mail.schulen.local",
                "smtp_port": 587,
                "smtp_security": "starttls",
                "smtp_username": "",
                "smtp_password": "__UNCHANGED__",
                "smtp_from_email": "lieferschein@schulen.local",
                "smtp_from_name": "Schul-IT",
                "osticket_enabled": True,
                "osticket_email": "tickets@schulen.local",
                "global_archive_cc_email": "",
            },
        )
        assert r_put_cfg.status_code == 200
        assert r_put_cfg.json()["osticket_email"] == "tickets@schulen.local"

        # 4. Neuen Mitarbeiter-Benutzer in der lokalen Benutzerverwaltung anlegen
        r_new_user = client.post(
            "/api/users",
            headers=headers,
            json={
                "username": "azubi1",
                "full_name": "Tim Azubi",
                "email": "tim@kommune.local",
                "role": "staff",
                "password": "azubiPass",
                "pin": "4321",
                "active": True,
                "add_to_staff_list": True,
            },
        )
        assert r_new_user.status_code == 201, r_new_user.text

        # 5. Schnell-PIN-Login für den neuen Benutzer testen
        r_pin_login = client.post(
            "/api/auth/login",
            json={"username": None, "pin_or_password": "4321"},
        )
        assert r_pin_login.status_code == 200
        assert r_pin_login.json()["user"]["username"] == "azubi1"


