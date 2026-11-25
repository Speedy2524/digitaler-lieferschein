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


def _resolve_cfg(cfg: dict[str, str] | None = None) -> dict[str, str]:
    base = {
        "department_name": settings.DEPARTMENT_NAME,
        "department_contact": settings.DEPARTMENT_CONTACT,
        "smtp_enabled": "true" if settings.SMTP_ENABLED else "false",
        "smtp_host": settings.SMTP_HOST,
        "smtp_port": str(settings.SMTP_PORT),
        "smtp_security": settings.SMTP_SECURITY,
        "smtp_username": settings.SMTP_USERNAME,
        "smtp_password": settings.SMTP_PASSWORD,
        "smtp_from_email": settings.SMTP_FROM_EMAIL,
        "smtp_from_name": settings.SMTP_FROM_NAME,
        "osticket_enabled": "true" if bool(settings.OSTICKET_EMAIL) else "false",
        "osticket_email": settings.OSTICKET_EMAIL,
        "global_archive_cc_email": settings.GLOBAL_ARCHIVE_CC_EMAIL,
    }
    if cfg:
        for k, v in cfg.items():
            if v is not None:
                base[k] = str(v)
    return base


def _send_raw_email(msg: EmailMessage, cfg: dict[str, str] | None = None) -> None:
    """Versendet eine EmailMessage über den konfigurierten SMTP-Server."""
    c = _resolve_cfg(cfg)
    security = (c.get("smtp_security") or "starttls").strip().lower()
    host = (c.get("smtp_host") or "").strip()
    if not host:
        raise ValueError("Kein SMTP-Host in den Systemeinstellungen hinterlegt.")
    port = int(c.get("smtp_port") or 587)
    timeout = settings.SMTP_TIMEOUT
    username = (c.get("smtp_username") or "").strip()
    password = c.get("smtp_password") or ""

    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(host=host, port=port, timeout=timeout)
    else:
        server = smtplib.SMTP(host=host, port=port, timeout=timeout)

    try:
        server.ehlo()
        if security == "starttls":
            server.starttls()
            server.ehlo()
        if username and password:
            server.login(username, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _build_school_email(
    note: DeliveryNote,
    pdf_bytes: bytes,
    pdf_filename: str,
    cfg: dict[str, str] | None = None,
) -> EmailMessage:
    c = _resolve_cfg(cfg)
    from_email = (c.get("smtp_from_email") or settings.SMTP_FROM_EMAIL).strip() or "schul-it@kommune.local"
    from_name = (c.get("smtp_from_name") or settings.SMTP_FROM_NAME).strip() or "Schul-IT Lieferschein-System"
    global_cc = (c.get("global_archive_cc_email") or "").strip()
    dept_name = c.get("department_name") or settings.DEPARTMENT_NAME
    dept_contact = c.get("department_contact") or settings.DEPARTMENT_CONTACT

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = note.recipient_email

    cc_list: list[str] = []
    if note.cc_email and note.cc_email.strip():
        cc_list.append(note.cc_email.strip())
    if global_cc and global_cc not in cc_list:
        cc_list.append(global_cc)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    subject = f"IT-Lieferschein {note.delivery_number} – {note.school_name}"
    if note.osticket_number:
        subject += f" (Ticket #{note.osticket_number})"
    msg["Subject"] = subject

    completed_str = format_dt_german(note.completed_at)
    items_lines = "\n".join(
        f"  - {item.quantity}x {item.device_type} (Inventar-Nr.: {item.inventory_number}"
        + (f", S/N: {item.serial_number}" if item.serial_number else "")
        + (f", Lieferant: {item.supplier}" if item.supplier else "")
        + (f", Rechnung: {item.invoice_number}" if item.invoice_number else "")
        + ")"
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
        f"{dept_name}\n"
        f"{dept_contact}\n"
    )

    msg.set_content(body_text)
    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=pdf_filename,
    )
    return msg


def _build_osticket_email(
    note: DeliveryNote,
    pdf_bytes: bytes,
    pdf_filename: str,
    cfg: dict[str, str] | None = None,
) -> EmailMessage:
    """
    Erzeugt die E-Mail an osTicket mit dem zwingend erforderlichen Betreff-Format:
    [#<TICKETNUMMER>] Lieferschein <LS-NR> - <Schule>
    """
    c = _resolve_cfg(cfg)
    from_email = (c.get("smtp_from_email") or settings.SMTP_FROM_EMAIL).strip() or "schul-it@kommune.local"
    from_name = (c.get("smtp_from_name") or settings.SMTP_FROM_NAME).strip() or "Schul-IT Lieferschein-System"
    osticket_to = (c.get("osticket_email") or settings.OSTICKET_EMAIL).strip()

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = osticket_to
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


def send_test_email(recipient_email: str, cfg: dict[str, str] | None = None) -> dict[str, str]:
    """Sendet eine Test-E-Mail über die aktuell gespeicherte SMTP-Konfiguration."""
    c = _resolve_cfg(cfg)
    from_email = (c.get("smtp_from_email") or "").strip() or "schul-it@kommune.local"
    from_name = (c.get("smtp_from_name") or "").strip() or "Schul-IT Lieferschein-System"
    dept_name = c.get("department_name") or settings.DEPARTMENT_NAME

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = recipient_email.strip()
    msg["Subject"] = f"SMTP-Testmail – {c.get('app_title', 'Digitaler IT-Lieferschein')}"
    msg.set_content(
        f"Guten Tag,\n\n"
        f"dies ist eine automatische Test-E-Mail der Anwendung '{c.get('app_title', 'Digitaler IT-Lieferschein')}'.\n"
        f"Die SMTP-Verbindung zu '{c.get('smtp_host')}:{c.get('smtp_port')}' ({c.get('smtp_security')}) "
        f"funktioniert einwandfrei.\n\n"
        f"Mit freundlichen Grüßen\n"
        f"{dept_name}\n"
    )
    _send_raw_email(msg, cfg=c)
    return {"status": "ok", "message": f"Test-E-Mail erfolgreich an {recipient_email} gesendet."}


def dispatch_delivery_note_emails(
    note: DeliveryNote,
    pdf_path: Path,
    cfg: dict[str, str] | None = None,
) -> None:
    """
    Versendet (oder simuliert, falls smtp_enabled=false) die E-Mail an das Schulsekretariat
    sowie – falls eine osTicket-Nummer hinterlegt ist – die Zuordnungs-E-Mail an osTicket.
    """
    c = _resolve_cfg(cfg)
    smtp_is_enabled = c.get("smtp_enabled", "false").lower() == "true" or settings.SMTP_ENABLED
    osticket_email = (c.get("osticket_email") or "").strip()
    osticket_is_enabled = c.get("osticket_enabled", "false").lower() == "true" or bool(osticket_email)

    pdf_bytes = pdf_path.read_bytes()
    pdf_filename = pdf_path.name
    now = datetime.now(timezone.utc)

    # 1. E-Mail an das Schulsekretariat
    try:
        school_msg = _build_school_email(note, pdf_bytes, pdf_filename, cfg=c)
        if smtp_is_enabled:
            _send_raw_email(school_msg, cfg=c)
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

    if not osticket_is_enabled or not osticket_email:
        note.email_osticket_status = "NICHT_KONFIGURIERT"
        note.email_osticket_error = "Keine osTicket-E-Mail-Adresse im Konfigmenü hinterlegt oder osTicket-Anbindung deaktiviert."
        return

    try:
        osticket_msg = _build_osticket_email(note, pdf_bytes, pdf_filename, cfg=c)
        if smtp_is_enabled:
            _send_raw_email(osticket_msg, cfg=c)
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
        logger.error("Fehler beim E-Mail-Versand an osTicket (%s): %s", osticket_email, exc)
        note.email_osticket_status = "FEHLER"
        note.email_osticket_error = str(exc)
