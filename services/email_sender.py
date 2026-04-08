"""Email sending via Resend API with pixel tracking."""

import os
from pathlib import Path

from scraping.database import get_connection


def send_welcome_email(to_email: str, dashboard_url: str) -> bool:
    """Send a welcome email with the dashboard access link.

    Returns True on success, False on failure.
    """
    import resend

    api_key = os.environ.get("RESEND" + "_API_KEY", "")
    from_email = os.environ.get("RESEND" + "_FROM", "VoileCV <onboarding@resend.dev>")

    if not api_key:
        print(f"  [SKIP] RESEND_API_KEY not set, skipping welcome email to {to_email}")
        return False

    resend.api_key = api_key

    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto;">
<div style="background: linear-gradient(135deg, #0077b6, #00b4d8); padding: 30px; border-radius: 12px 12px 0 0; text-align: center;">
    <h1 style="color: white; margin: 0; font-size: 28px;">Bienvenue sur VoileCV !</h1>
</div>
<div style="padding: 30px; background: #f8f9fa; border-radius: 0 0 12px 12px;">
    <p>Bonjour,</p>
    <p>Votre CV a bien été reçu. Votre dashboard est prêt : vous pouvez consulter les écoles de voile, personnaliser vos lettres de motivation et envoyer vos candidatures en un clic.</p>

    <div style="text-align: center; margin: 30px 0;">
        <a href="{dashboard_url}" style="background: #0077b6; color: white; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 16px;">Accéder à mon dashboard</a>
    </div>

    <p style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 12px 16px; font-size: 14px;">
        <strong>Conservez cet email</strong> — le lien ci-dessus est votre accès personnel au dashboard. Pas de mot de passe, il suffit de cliquer.
    </p>

    <p style="margin-top: 24px;">Bonne recherche,<br><strong>L'équipe VoileCV</strong></p>
</div>
</body>
</html>"""

    text_body = f"""Bienvenue sur VoileCV !

Votre CV a bien été reçu. Votre dashboard est prêt.

Accédez à votre dashboard : {dashboard_url}

Conservez cet email — le lien ci-dessus est votre accès personnel.

Bonne recherche,
L'équipe VoileCV"""

    try:
        result = resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": "Bienvenue sur VoileCV — Votre dashboard est prêt",
            "html": html_body,
            "text": text_body,
        })
        print(f"  [OK] Welcome email sent to {to_email} (id: {result.get('id', '?')})")
        return True
    except Exception as e:
        print(f"  [ERROR] Failed to send welcome email to {to_email}: {e}")
        return False


def send_candidature_email(
    to_email: str,
    ecole_nom: str,
    cover_letter: str,
    cv_path: str,
    candidature_id: int,
    user_email: str,
    diploma_path: str = None,
    sender_name: str = "",
) -> bool:
    """Send a candidature email with CV attachment, optional diploma, and tracking pixel.

    Returns True on success, False on failure.
    """
    import resend

    api_key = os.environ.get("RESEND" + "_API_KEY", "")
    from_domain = os.environ.get("RESEND" + "_FROM", "VoileCV <onboarding@resend.dev>")
    base_url = os.environ.get("BASE" + "_URL", "http://localhost:8000")

    # Use candidate's name as sender display name
    if sender_name:
        # Extract email address from RESEND_FROM (e.g. "VoileCV <candidature@voilecv.fr>" -> "candidature@voilecv.fr")
        import re
        match = re.search(r'<(.+?)>', from_domain)
        addr = match.group(1) if match else from_domain
        from_email = f"{sender_name} <{addr}>"
    else:
        from_email = from_domain

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

    if diploma_path:
        diploma_file = Path(diploma_path)
        if diploma_file.exists():
            diploma_bytes = diploma_file.read_bytes()
            attachments.append({
                "filename": "Diplome.pdf",
                "content": list(diploma_bytes),
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
            "SELECT id, custom_letter, status FROM candidatures WHERE user_id = ? AND ecole_id = ?",
            (user_id, ecole_id)
        ).fetchone()
        if existing and existing["status"] in ("sent", "opened", "replied"):
            results["skipped"] += 1
            results["details"].append({
                "ecole_id": ecole_id,
                "status": "skipped",
                "reason": "already sent",
            })
            continue

        # Get active offer for this school
        offre = conn.execute(
            "SELECT intitule, description FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
            (ecole_id,)
        ).fetchone()

        # Use saved custom letter if available
        custom_letter = existing["custom_letter"] if existing and existing["custom_letter"] else None

        if existing:
            # Update existing draft candidature to pending
            conn.execute(
                "UPDATE candidatures SET status = 'pending' WHERE id = ?",
                (existing["id"],)
            )
        else:
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

        # Generate or use saved cover letter
        if custom_letter:
            letter = custom_letter
        else:
            letter = generate_cover_letter(
                user_email=user["email"],
                ecole_nom=ecole["nom"],
                ecole_ville=ecole["ville"],
                offre_intitule=offre["intitule"] if offre else None,
                offre_description=offre["description"] if offre else None,
                has_diploma=bool(user["diploma_path"]),
                has_user_letter=bool(user["letter_path"]),
                cv_path=user["cv_path"],
            )

        # Send email
        success = send_candidature_email(
            to_email=ecole["email"],
            ecole_nom=ecole["nom"],
            cover_letter=letter,
            cv_path=user["cv_path"],
            candidature_id=cand["id"],
            user_email=user["email"],
            diploma_path=user["diploma_path"],
            sender_name=user["name"] if user["name"] else "",
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
