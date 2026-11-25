# Digitaler IT-Lieferschein (Kommunale Schul-IT)

Eine vollständige, selbstgehostete Webanwendung für den internen 2-Stufen-Workflow einer kommunalen Schul-IT-Abteilung:
1. **Stufe 1 – Vorbereitung im Büro (Desktop- & Barcodescanner-optimiert):** Erfassung von Lieferscheinen bei der Inventarisierung am PC (Schulauswahl mit automatischer Sekretariats-E-Mail, optionale osTicket-Nummer, Besteller, Raum, Lieferant, dynamische Geräteliste mit USB-/Kamera-Barcodescanner).
2. **Stufe 2 – Übergabe & Digitale Unterschrift vor Ort (Mobile-/iPad-First):** Auswahl des offenen Lieferscheins auf dem iPad oder Diensthandy vor Ort an der Schule, digitale Quittierung per Touch/Apple Pencil (`signature_pad`), automatische Erstellung eines amtlichen DIN-A4-Übergabeprotokolls als PDF (`WeasyPrint`) und Versand per E-Mail an das Schulsekretariat sowie optional direkt in das bestehende **osTicket-Ticket**.

---

## Schnellstart mit Docker Compose

### 1. Konfiguration anlegen
Kopieren Sie die Beispiel-Konfiguration `.env.example` nach `.env` und passen Sie bei Bedarf Abteilungsname, SMTP-Server und `OSTICKET_EMAIL` an:

```bash
cp .env.example .env
```

### 2. Container bauen und im Hintergrund starten

```bash
docker compose up -d --build
```

Die Anwendung ist anschließend unter **`http://localhost:8000`** erreichbar.
Alle Daten (SQLite-Datenbank `lieferscheine.db` sowie alle generierten PDF-Übergabeprotokolle unter `pdfs/`) werden dauerhaft im gemounteten Host-Verzeichnis `./data` gespeichert.

---

## Architektur & Projektstruktur

```text
.
├── .env.example                     # Vorlage für Umgebungsvariablen (SMTP, osTicket, Auth, Abteilung)
├── Dockerfile                       # Python 3.12 Container inkl. WeasyPrint-Systembibliotheken (Pango/Cairo)
├── docker-compose.yml               # Container-Orchestrierung mit persistentem Volume ./data:/app/data
├── requirements.txt                 # Python-Abhängigkeiten (FastAPI, SQLAlchemy, WeasyPrint, Jinja2)
├── README.md                        # Dokumentation & Betriebsanleitung
├── tests/
│   └── test_workflow.py             # Automatisierte End-to-End-Tests für den gesamten Workflow
└── app/
    ├── main.py                      # FastAPI REST-API, Auth-Schutz & Auslieferung der Web-App
    ├── config.py                    # Zentrale Konfiguration über Umgebungsvariablen (.env)
    ├── database.py                  # SQLite-Engine, fortlaufende LS-Nummern & initiales Seeding
    ├── models.py                    # SQLAlchemy-Modelle (School, StaffMember, DeliveryNote, DeliveryItem)
    ├── schemas.py                   # Pydantic-Validierung inkl. osTicket-Bereinigung
    ├── pdf_service.py               # WeasyPrint DIN-A4 PDF-Generator
    ├── email_service.py             # Fehlertoleranter SMTP-Versand (Schule + osTicket + globales CC)
    ├── templates/
    │   └── delivery_note_pdf.html   # Deutsches DIN-A4 Übergabeprotokoll-Template (HTML/CSS)
    └── static/
        ├── index.html               # Responsive Single-Page-UI (Desktop & iPad/Smartphone)
        ├── app.js                   # Alpine.js Frontend-Logik, Barcode-Scanner & SignaturePad
        └── styles.css               # Touch-, Dialog- und Responsive-Table-Styles
```

---

## Funktionsübersicht

### Status-Workflow
Jeder Lieferschein durchläuft folgende Status:
1. **`ENTWURF`**: Unvollständige Vorbereitungen im Büro; jederzeit bearbeitbar oder löschbar.
2. **`BEREIT`**: Zur Auslieferung freigegeben; erscheint prominent als Karte in der mobilen Ansicht **„Offene Auslieferungen“**.
3. **`ABGESCHLOSSEN`**: Vor Ort digital unterschrieben, DIN-A4-PDF generiert und dauerhaft archiviert, E-Mails versendet.

### Automatische osTicket-Zuordnung
Wenn in einem Lieferschein eine **osTicket-Nummer** hinterlegt ist (Eingaben wie `#382814` oder ` 382814 ` werden automatisch auf reine Ziffern `382814` bereinigt) und in der `.env` die Variable `OSTICKET_EMAIL` gesetzt ist, versendet das System beim Abschließen automatisch eine E-Mail mit dem PDF-Anhang und dem exakt für osTicket erforderlichen Betreff:

```text
[#382814] Lieferschein LS-2026-0001 - Musterschule Nord GS
```

Dadurch ordnet osTicket das digital unterschriebene Übergabeprotokoll automatisch dem bestehenden Ticket zu.

### Fehlertoleranter E-Mail-Versand
- Schlägt der SMTP-Versand fehl (z. B. Mail-Relay temporär nicht erreichbar), bleibt der Lieferschein samt Unterschrift und PDF **sicher als `ABGESCHLOSSEN` gespeichert**.
- Der Versandstatus wird getrennt für **Schule** und **osTicket** erfasst (`VERSENDET`, `SIMULIERT`, `FEHLER`, `KEIN_TICKET`, `NICHT_KONFIGURIERT`).
- Über den Button **„↻ E-Mail erneut senden“** im Archiv oder direkt nach der Übergabe kann der Versand jederzeit wiederholt werden.

### Zugriffsschutz (Optional)
Über `.env` aktivierbar (`AUTH_ENABLED="true"`):
- Unterstützt sowohl **PIN-Anmeldung** direkt im Web-Dialog (`AUTH_PIN="1234"`) als auch **HTTP Basic Auth** (`AUTH_USERNAME` / `AUTH_PASSWORD`).

---

## Lokale Entwicklung & Tests (ohne Docker)

```bash
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload --port 8000
```
