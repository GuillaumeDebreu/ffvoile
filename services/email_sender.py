"""SMTP email sending with pixel tracking."""

import os
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from pathlib import Path

from scraping.database import get_connection

# SMTP config — read at runtime to avoid Railpack secret scanning
def _smtp_conf():
    user = os.environ.get("SMTP_USER", "")
    return {
        "host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": user,
        "pass": os.environ.get("SMTP_PASS", ""),
        "from": os.environ.get("SMTP_FROM", user),
        "base_url": os.environ.get("BASE_URL", "http://localhost:8000"),
    }


def send_candidature_email(
    to_email: str,
    ecole_nom: str,
    cover_letter: str,
    cv_path: str,
    candidature_id: int,
    user_email: str,
) -> bool:
    """Send a candidature email with CV attachment and tracking pixel.

    Returns True on success, False on failure.
    """
    conf = _smtp_conf()

    if not conf["user"] or not conf["pass"]:
        print(f"  [SKIP] SMTP not configured, skipping email to {to_email}")
        return False

    # Build tracking pixel URL
    tracking_url = f"{conf['base_url']}/track/{candidature_id}.png"

    msg = MIMEMultipart("mixed")
    msg["From"] = f"VoileCV <{conf['from']}>"
    msg["To"] = to_email
    msg["Reply-To"] = user_email
    msg["Subject"] = f"Candidature moniteur de voile - {ecole_nom}"

    # HTML body with tracking pixel
    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
{cover_letter.replace(chr(10), '<br>')}
<br><br>
<img src="{tracking_url}" width="1" height="1" alt="" style="display:none">
</body>
</html>"""

    text_body = cover_letter

    # Attach text and HTML alternatives
    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(text_body, "plain", "utf-8"))
    alt_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt_part)

    # Attach CV
    cv_file = Path(cv_path)
    if cv_file.exists():
        with open(cv_file, "rb") as f:
            pdf_part = MIMEApplication(f.read(), _subtype="pdf")
            pdf_part.add_header(
                "Content-Disposition", "attachment",
                filename="CV.pdf"
            )
            msg.attach(pdf_part)

    try:
        with smtplib.SMTP(conf["host"], conf["port"]) as server:
            server.starttls()
            server.login(conf["user"], conf["pass"])
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to send to {to_email}: {e}")
        return False


def send_batch(user_id: str, ecole_ids: list[int]) -> dict:
    """Send CV to multiple schools. Returns summary stats."""
    from services.cover_letter import generate_cover_letter

    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return {"error": "User not found"}

    results = {"sent": 0, "skipped": 0, "failed": 0, "details": []}

    for ecole_id in ecole_ids:
        ecole = conn.execute("SELECT * FROM ecoles WHERE id = ?", (ecole_id,)).fetchone()
        if not ecole or not ecole["email"]:
            results["skipped"] += 1
            results["details"].append({
                "ecole_id": ecole_id,
                "status": "skipped",
                "reason": "no email",
            })
            continue

        # Check if already sent
        existing = conn.execute(
            "SELECT id FROM candidatures WHERE user_id = ? AND ecole_id = ?",
            (user_id, ecole_id)
        ).fetchone()
        if existing:
            results["skipped"] += 1
            results["details"].append({
                "ecole_id": ecole_id,
                "status": "skipped",
                "reason": "already sent",
            })
            continue

        # Get active offer for this school
        offre = conn.execute(
            "SELECT intitule FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
            (ecole_id,)
        ).fetchone()

        # Create candidature record
        conn.execute("""
            INSERT INTO candidatures (user_id, ecole_id, status, created_at)
            VALUES (?, ?, 'pending', datetime('now'))
        """, (user_id, ecole_id))
        conn.commit()

        cand = conn.execute(
            "SELECT id FROM candidatures WHERE user_id = ? AND ecole_id = ?",
            (user_id, ecole_id)
        ).fetchone()

        # Generate cover letter
        letter = generate_cover_letter(
            user_email=user["email"],
            ecole_nom=ecole["nom"],
            ecole_ville=ecole["ville"],
            offre_intitule=offre["intitule"] if offre else None,
        )

        # Send email
        success = send_candidature_email(
            to_email=ecole["email"],
            ecole_nom=ecole["nom"],
            cover_letter=letter,
            cv_path=user["cv_path"],
            candidature_id=cand["id"],
            user_email=user["email"],
        )

        if success:
            conn.execute(
                "UPDATE candidatures SET status = 'sent', sent_at = datetime('now') WHERE id = ?",
                (cand["id"],)
            )
            results["sent"] += 1
        else:
            conn.execute(
                "UPDATE candidatures SET status = 'send_failed' WHERE id = ?",
                (cand["id"],)
            )
            results["failed"] += 1

        conn.commit()
        results["details"].append({
            "ecole_id": ecole_id,
            "ecole_nom": ecole["nom"],
            "status": "sent" if success else "failed",
        })

    conn.close()
    return results
