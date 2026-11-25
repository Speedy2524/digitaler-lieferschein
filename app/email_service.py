import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from app.config import settings
from app.models import DeliveryNote
from app.pdf_service import format_dt_german

logger = logging.getLogger(__name__)


def _send_raw_email(msg: EmailMessage) -> None:
    """Versendet eine EmailMessage über den in settings konfigurierten SMTP-Server."""
    security = settings.SMTP_SECURITY
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT
    timeout = settings.SMTP_TIMEOUT

    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host=host, port=port, timeout=timeout)
    else:
        server = smtplib.SMTP(host=host, port=port, timeout=timeout)

    try:
        server.ehlo()
        if security == "starttls":
            server.starttls()
            server.ehlo()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _build_school_email(note: DeliveryNote, pdf_bytes: bytes, pdf_filename: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    msg["To"] = note.recipient_email

    cc_list: list[str] = []
    if note.cc_email and note.cc_email.strip():
        cc_list.append(note.cc_email.strip())
    if settings.GLOBAL_ARCHIVE_CC_EMAIL and settings.GLOBAL_ARCHIVE_CC_EMAIL not in cc_list:
        cc_list.append(settings.GLOBAL_ARCHIVE_CC_EMAIL)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    subject = f"IT-Lieferschein {note.delivery_number} – {note.school_name}"
    if note.osticket_number:
        subject += f" (Ticket #{note.osticket_number})"
    msg["Subject"] = subject

    completed_str = format_dt_german(note.completed_at)
    items_lines = "\n".join(
        f"  - {item.quantity}x {item.device_type} (Inventar-Nr.: {item.inventory_number}"
        + (f", S/N: {item.serial_number})" if item.serial_number else ")")
        for item in note.items
    )

    body_text = (
        f"Guten Tag,\n\n"
        f"anbei erhalten Sie das digital quittierte Übergabeprotokoll (Lieferschein {note.delivery_number}) "
        f"für die Auslieferung von IT-Geräten an Ihre Schule ({note.school_name}).\n\n"
        f"Zusammenfassung der Übergabe:\n"
        f"------------------------------------------------------------\n"
        f"Lieferschein-Nr.:  {note.delivery_number}\n"
        f"Schule:            {note.school_name}\n"
        f"Datum / Uhrzeit:   {completed_str}\n"
        f"Übergeben durch:   {note.delivered_by or '-'}\n"
        f"Angenommen von:    {note.received_by or '-'}\n"
    )
    if note.ordered_by:
        body_text += f"Besteller/in:      {note.ordered_by}\n"
    if note.room:
        body_text += f"Aufstellort/Raum:  {note.room}\n"
    if note.osticket_number:
        body_text += f"osTicket-Nr.:      #{note.osticket_number}\n"

    body_text += (
        f"\nÜbergebene Geräte:\n"
        f"{items_lines}\n"
    )
    if note.notes:
        body_text += f"\nHinweise der Schul-IT:\n{note.notes}\n"
    if note.handover_notes:
        body_text += f"\nBemerkung bei der Übergabe:\n{note.handover_notes}\n"

    body_text += (
        f"------------------------------------------------------------\n\n"
        f"Den vollständigen Lieferschein inklusive digitaler Unterschrift finden Sie als PDF im Anhang.\n\n"
        f"Mit freundlichen Grüßen\n"
        f"{settings.DEPARTMENT_NAME}\n"
        f"{settings.DEPARTMENT_CONTACT}\n"
    )

    msg.set_content(body_text)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )
    return msg


def _build_osticket_email(note: DeliveryNote, pdf_bytes: bytes, pdf_filename: str) -> EmailMessage:
    """
    Erzeugt die E-Mail an osTicket mit dem zwingend erforderlichen Betreff-Format:
    [#<TICKETNUMMER>] Lieferschein <LS-NR> - <Schule>
    """
    msg = EmailMessage()
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    msg["To"] = settings.OSTICKET_EMAIL
    msg["Subject"] = f"[#{note.osticket_number}] Lieferschein {note.delivery_number} - {note.school_name}"

    completed_str = format_dt_german(note.completed_at)
    items_lines = "\n".join(
        f"  * {item.quantity}x {item.device_type} | Inv.-Nr.: {item.inventory_number}"
        + (f" | S/N: {item.serial_number}" if item.serial_number else "")
        for item in note.items
    )

    body_text = (
        f"Automatische Lieferschein-Zuordnung zum osTicket #{note.osticket_number}\n"
        f"====================================================================\n\n"
        f"Der Lieferschein {note.delivery_number} für {note.school_name} wurde vor Ort digital quittiert.\n\n"
        f"- Lieferschein-Nr.: {note.delivery_number}\n"
        f"- Schule:           {note.school_name}\n"
        f"- Zeitpunkt:        {completed_str}\n"
        f"- Übergeben von:    {note.delivered_by or '-'}\n"
        f"- Angenommen von:   {note.received_by or '-'}\n"
        f"- Aufstellort/Raum: {note.room or '-'}\n\n"
        f"Ausgelieferte Geräte:\n"
        f"{items_lines}\n\n"
        f"Bemerkungen vor Ort: {note.handover_notes or 'Keine'}\n\n"
        f"Das unterschriebene Übergabeprotokoll ({pdf_filename}) ist dieser E-Mail als PDF beigefügt.\n"
    )

    msg.set_content(body_text)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )
    return msg


def dispatch_delivery_note_emails(note: DeliveryNote, pdf_path: Path) -> None:
    """
    Versendet (oder simuliert, falls SMTP_ENABLED=false) die E-Mail an das Schulsekretariat
    sowie – falls eine osTicket-Nummer hinterlegt ist – die Zuordnungs-E-Mail an osTicket.
    Aktualisiert die Statusfelder am DeliveryNote-Objekt fehlertolerant.
    """
    pdf_bytes = pdf_path.read_bytes()
    pdf_filename = pdf_path.name
    now = datetime.now(timezone.utc)

    # 1. E-Mail an das Schulsekretariat
    try:
        school_msg = _build_school_email(note, pdf_bytes, pdf_filename)
        if settings.SMTP_ENABLED:
            _send_raw_email(school_msg)
            note.email_school_status = "VERSENDET"
        else:
            logger.info(
                "[SMTP-Testmodus] Schul-E-Mail simuliert an '%s' (Betreff: '%s')",
                school_msg["To"],
                school_msg["Subject"],
            )
            note.email_school_status = "SIMULIERT"
        note.email_school_error = None
        note.email_school_sent_at = now
    except Exception as exc:
        logger.error("Fehler beim E-Mail-Versand an Schule (%s): %s", note.recipient_email, exc)
        note.email_school_status = "FEHLER"
        note.email_school_error = str(exc)

    # 2. Automatische osTicket-Zuordnung
    if not note.osticket_number:
        note.email_osticket_status = "KEIN_TICKET"
        note.email_osticket_error = None
        return

    if not settings.OSTICKET_EMAIL:
        note.email_osticket_status = "NICHT_KONFIGURIERT"
        note.email_osticket_error = "Keine OSTICKET_EMAIL in der .env konfiguriert."
        return

    try:
        osticket_msg = _build_osticket_email(note, pdf_bytes, pdf_filename)
        if settings.SMTP_ENABLED:
            _send_raw_email(osticket_msg)
            note.email_osticket_status = "VERSENDET"
        else:
            logger.info(
                "[SMTP-Testmodus] osTicket-E-Mail simuliert an '%s' (Betreff: '%s')",
                osticket_msg["To"],
                osticket_msg["Subject"],
            )
            note.email_osticket_status = "SIMULIERT"
        note.email_osticket_error = None
        note.email_osticket_sent_at = now
    except Exception as exc:
        logger.error("Fehler beim E-Mail-Versand an osTicket (%s): %s", settings.OSTICKET_EMAIL, exc)
        note.email_osticket_status = "FEHLER"
        note.email_osticket_error = str(exc)
