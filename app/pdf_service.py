import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.models import DeliveryNote

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def format_dt_german(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.now()
    try:
        tz = ZoneInfo(settings.TIMEZONE)
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz)
    except Exception:
        pass
    return dt.strftime("%d.%m.%Y um %H:%M Uhr")


def render_delivery_note_html(note: DeliveryNote) -> str:
    template = jinja_env.get_template("delivery_note_pdf.html")
    total_qty = sum(item.quantity for item in note.items)
    school_address = note.school.address if note.school and note.school.address else ""

    return template.render(
        note=note,
        department_name=settings.DEPARTMENT_NAME,
        department_subtitle=settings.DEPARTMENT_SUBTITLE,
        department_contact=settings.DEPARTMENT_CONTACT,
        school_address=school_address,
        total_quantity=total_qty,
        created_at_formatted=format_dt_german(note.created_at),
        completed_at_formatted=format_dt_german(note.completed_at or datetime.now()),
    )


def _write_fallback_pdf(target_path: Path, note: DeliveryNote) -> None:
    """
    Reiner Python-Fallback für minimale PDF-Erzeugung, falls lokal unter Windows
    ohne GTK/Pango-DLLs getestet wird. Im Docker-Container läuft immer WeasyPrint.
    """
    def _esc(text: str) -> str:
        replacements = {
            "ä": "ae", "ö": "oe", "ü": "ue",
            "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
            "–": "-", "—": "-",
        }
        for k, v in replacements.items():
            text = text.replace(k, v)
        text = text.encode("latin-1", "replace").decode("latin-1")
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    lines = [
        f"{settings.DEPARTMENT_NAME}",
        f"IT-LIEFERSCHEIN / UEBERGABEPROTOKOLL: {note.delivery_number}",
        f"Datum: {format_dt_german(note.completed_at)}",
        f"Schule: {note.school_name} ({note.recipient_email})",
        f"osTicket-Nr.: #{note.osticket_number}" if note.osticket_number else "osTicket-Nr.: -",
        f"Besteller: {note.ordered_by or '-'} | Raum: {note.room or '-'}",
        "-" * 75,
        "Pos. | Geraetebezeichnung / Typ | Inventarnr. | Seriennr. | Menge",
        "-" * 75,
    ]
    for idx, item in enumerate(note.items, start=1):
        lines.append(
            f"{idx}. {item.device_type} | Inv: {item.inventory_number} | SN: {item.serial_number or '-'} | x{item.quantity}"
        )
    lines.extend([
        "-" * 75,
        f"Notiz: {note.notes or '-'}",
        f"Uebergabe-Bemerkung: {note.handover_notes or '-'}",
        f"Uebergeben von (IT): {note.delivered_by or '-'}",
        f"Angenommen & digital unterschrieben von: {note.received_by or '-'}",
    ])

    stream_cmds = ["BT", "/F1 10 Tf", "45 790 Td", "14 TL"]
    for line in lines:
        stream_cmds.append(f"({_esc(line)}) Tj T*")
    stream_cmds.append("ET")
    stream_data = "\n".join(stream_cmds).encode("latin-1")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        f"5 0 obj\n<< /Length {len(stream_data)} >>\nstream\n".encode("latin-1")
        + stream_data
        + b"\nendstream\nendobj\n",
    ]

    pdf_bytes = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf_bytes))
        pdf_bytes.extend(obj)
    xref_pos = len(pdf_bytes)
    pdf_bytes.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("latin-1"))
    for off in offsets[1:]:
        pdf_bytes.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    pdf_bytes.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("latin-1")
    )
    target_path.write_bytes(bytes(pdf_bytes))


def generate_delivery_note_pdf(note: DeliveryNote) -> Path:
    """
    Generiert das DIN-A4 Übergabeprotokoll als PDF mit WeasyPrint und speichert es
    dauerhaft im konfigurierten PDF_STORAGE_DIR.
    """
    settings.PDF_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    safe_number = note.delivery_number.replace("/", "-").replace(" ", "_")
    filename = f"Lieferschein_{safe_number}.pdf"
    target_path = settings.PDF_STORAGE_DIR / filename

    html_content = render_delivery_note_html(note)

    try:
        from weasyprint import HTML

        HTML(string=html_content).write_pdf(str(target_path))
        logger.info("PDF erfolgreich mit WeasyPrint erstellt: %s", target_path)
    except Exception as exc:
        logger.warning(
            "WeasyPrint auf diesem Host nicht verfügbar (%s) – nutze integrierten PDF-Fallback.",
            exc,
        )
        _write_fallback_pdf(target_path, note)

    return target_path
