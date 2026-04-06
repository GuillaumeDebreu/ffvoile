"""Email sending via Resend API with pixel tracking."""

import os
import base64
from pathlib import Path

from scraping.database import get_connection


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
    import resend

    api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("RESEND_FROM", "VoileCV <onboarding@resend.dev>")
    base_url = os.environ.get("BASE_URL", "http://localhost:8000")

    if not api_key:
        print(f"  [SKIP] RESEND_API_KEY not set, skipping email to {to_email}")
        return False

    resend.api_key = api_key

    # Build tracking pixel URL
    tracking_url = f"{base_url}/track/{candidature_id}.png"

    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
{cover_letter.replace(chr(10), '<br>')}
<br><br>
<img src="{tracking_url}" width="1" height="1" alt="" style="display:none">
</body>
</html>"""

    # Build attachments
    attachments = []
    cv_file = Path(cv_path)
    if cv_file.exists():
        cv_bytes = cv_file.read_bytes()
        attachments.append({
            "filename": "CV.pdf",
            "content": list(cv_bytes),
        })

    try:
        params = {
            "from": from_email,
            "to": [to_email],
            "reply_to": user_email,
            "subject": f"Candidature moniteur de voile - {ecole_nom}",
            "html": html_body,
            "text": cover_letter,
        }
        if attachments:
            params["attachments"] = attachments

        result = resend.Emails.send(params)
        print(f"  [OK] Email sent to {to_email} (id: {result.get('id', '?')})")
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
