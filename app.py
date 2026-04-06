"""VoileCV - FastAPI backend."""

import os
import uuid
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from scraping.database import get_connection, init_db

# Config — loaded at runtime, not at import time, to avoid Railpack secret issues
def _env(key, default=""):
    return os.environ.get(key, default)

PRICE_CENTS = 999  # 9.99€

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="VoileCV")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def init_app_db():
    """Create app-specific tables (users/payments)."""
    init_db()  # scraping tables
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            token TEXT UNIQUE NOT NULL,
            cv_path TEXT,
            diploma_path TEXT,
            letter_path TEXT,
            stripe_session_id TEXT,
            paid INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL REFERENCES users(id),
            ecole_id INTEGER NOT NULL REFERENCES ecoles(id),
            status TEXT NOT NULL DEFAULT 'pending',
            custom_letter TEXT,
            sent_at TEXT,
            opened_at TEXT,
            replied_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, ecole_id)
        );

        CREATE INDEX IF NOT EXISTS idx_candidatures_user ON candidatures(user_id);
        CREATE INDEX IF NOT EXISTS idx_candidatures_status ON candidatures(status);
    """)
    # Migration: add custom_letter column if missing
    cols = [r[1] for r in conn.execute("PRAGMA table_info(candidatures)").fetchall()]
    if "custom_letter" not in cols:
        conn.execute("ALTER TABLE candidatures ADD COLUMN custom_letter TEXT")
    conn.commit()
    conn.close()


init_app_db()

# Auto-scrape if database is empty (first deploy)
import threading, traceback

_conn = get_connection()
_offre_count = _conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
_conn.close()
print(f"[STARTUP] offres count = {_offre_count}")

if _offre_count == 0:
    def _initial_scrape():
        try:
            from scraping.scrape_offres import scrape_all_offers
            print("[STARTUP] Database empty, running initial scrape...")
            scrape_all_offers(max_detail_pages=None)
            print("[STARTUP] Initial scrape complete.")
        except Exception as e:
            print(f"[STARTUP ERROR] Scrape failed: {e}")
            traceback.print_exc()
    threading.Thread(target=_initial_scrape, daemon=True).start()


# ─── Manual scrape trigger ───────────────────────────────────────────────

@app.get("/api/scrape")
async def trigger_scrape(force: str = ""):
    """Trigger a manual scrape. Visit this URL to populate/refresh the database."""
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
    conn.close()

    if count > 0 and force != "1":
        return {"status": "already_populated", "offres": count,
                "hint": "Add ?force=1 to re-scrape"}

    def _bg_scrape():
        try:
            from scraping.scrape_offres import scrape_all_offers
            print("[SCRAPE] Starting...")
            scrape_all_offers(max_detail_pages=None)
            print("[SCRAPE] Complete.")
        except Exception as e:
            print(f"[SCRAPE ERROR] {e}")
            traceback.print_exc()

    threading.Thread(target=_bg_scrape, daemon=True).start()
    return {"status": "scraping_started", "message": "Refresh en cours, 2-3 minutes."}


@app.get("/api/cron-refresh")
async def cron_refresh(key: str = ""):
    """Daily cron endpoint. Called by Railway cron service."""
    cron_key = _env("CRON_KEY", "")
    if not cron_key or key != cron_key:
        raise HTTPException(403, "Invalid cron key")

    def _bg_refresh():
        try:
            from scraping.scrape_offres import scrape_all_offers
            print("[CRON] Daily refresh starting...")
            scrape_all_offers(max_detail_pages=None)
            conn = get_connection()
            count = conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
            conn.close()
            print(f"[CRON] Refresh complete. {count} offres in database.")
        except Exception as e:
            print(f"[CRON ERROR] {e}")
            traceback.print_exc()

    threading.Thread(target=_bg_refresh, daemon=True).start()
    return {"status": "cron_started"}


# ─── Landing Page ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"stripe_key": _env("STRIPE_PUBLISHABLE_KEY", "pk_test_PLACEHOLDER")},
    )


# ─── CV Upload ───────────────────────────────────────────────────────────

@app.post("/api/upload-cv")
async def upload_cv(
    file: UploadFile = File(...),
    email: str = Form(""),
    diploma: UploadFile = File(None),
    letter: UploadFile = File(None),
):
    if not email or "@" not in email:
        raise HTTPException(400, "Email invalide")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Seuls les fichiers PDF sont acceptés")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "Fichier trop volumineux (max 5 Mo)")

    # Save CV
    user_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    filepath = UPLOAD_DIR / f"{user_id}.pdf"
    filepath.write_bytes(content)

    # Save optional diploma
    diploma_path = None
    if diploma and diploma.filename:
        diploma_content = await diploma.read()
        if len(diploma_content) <= 5 * 1024 * 1024:
            dp = UPLOAD_DIR / f"{user_id}_diploma.pdf"
            dp.write_bytes(diploma_content)
            diploma_path = str(dp)

    # Save optional cover letter
    letter_path = None
    if letter and letter.filename:
        letter_content = await letter.read()
        if len(letter_content) <= 5 * 1024 * 1024:
            lp = UPLOAD_DIR / f"{user_id}_letter.pdf"
            lp.write_bytes(letter_content)
            letter_path = str(lp)

    # Create user record
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO users (id, email, token, cv_path, diploma_path, letter_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                cv_path = excluded.cv_path,
                diploma_path = COALESCE(excluded.diploma_path, users.diploma_path),
                letter_path = COALESCE(excluded.letter_path, users.letter_path),
                token = excluded.token
        """, (user_id, email, token, str(filepath), diploma_path, letter_path,
              datetime.now().isoformat()))
        conn.commit()

        # Get user id (might be existing user)
        row = conn.execute("SELECT id, token FROM users WHERE email = ?", (email,)).fetchone()
        user_id = row["id"]
        token = row["token"]
    finally:
        conn.close()

    return {"user_id": user_id, "token": token, "filename": file.filename}


# ─── Stripe Checkout ─────────────────────────────────────────────────────

@app.post("/api/create-checkout-session")
async def create_checkout_session(request: Request):
    import stripe
    data = await request.json()
    user_id = data.get("user_id")
    token = data.get("token")

    if not user_id or not token:
        raise HTTPException(400, "Données manquantes")

    conn = get_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE id = ? AND token = ?", (user_id, token)
    ).fetchone()
    conn.close()

    if not user:
        raise HTTPException(404, "Utilisateur non trouvé")

    try:
        stripe.api_key = _env("STRIPE_SECRET_KEY", "sk_test_PLACEHOLDER")
        base = _env("BASE_URL", "http://localhost:8000")
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {
                        "name": "VoileCV - Envoi de CV aux écoles de voile",
                        "description": "CV personnalisé envoyé à toutes les écoles de voile de France",
                    },
                    "unit_amount": PRICE_CENTS,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{base}/dashboard?token={token}",
            cancel_url=f"{base}/?cancelled=true",
            client_reference_id=user_id,
            customer_email=user["email"],
        )
    except stripe.StripeError as e:
        raise HTTPException(500, f"Erreur Stripe: {str(e)}")

    # Store session ID
    conn = get_connection()
    conn.execute(
        "UPDATE users SET stripe_session_id = ? WHERE id = ?",
        (session.id, user_id)
    )
    conn.commit()
    conn.close()

    return {"checkout_url": session.url, "session_id": session.id}


# ─── Stripe Webhook ──────────────────────────────────────────────────────

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    import stripe
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, _env("STRIPE_WEBHOOK_SECRET", "whsec_PLACEHOLDER")
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("client_reference_id")
        if user_id:
            conn = get_connection()
            conn.execute("UPDATE users SET paid = 1 WHERE id = ?", (user_id,))
            conn.commit()
            conn.close()

    return {"status": "ok"}


# ─── Dashboard (post-payment) ────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, token: str = ""):
    if not token:
        return RedirectResponse("/")

    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()

    if not user:
        conn.close()
        return RedirectResponse("/")

    # Auto-grant access (Stripe bypassed for now)
    # TODO: re-enable Stripe checkout and rely on webhook only
    if not user["paid"]:
        conn.execute("UPDATE users SET paid = 1 WHERE id = ?", (user["id"],))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()

    # Get last scrape date
    last_scrape = conn.execute(
        "SELECT MAX(date_scrape) as last FROM offres"
    ).fetchone()
    last_update = last_scrape["last"] if last_scrape else None

    offre_count = conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
    ecole_count = conn.execute("SELECT COUNT(*) FROM ecoles").fetchone()[0]

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": dict(user),
            "token": token,
            "last_update": last_update,
            "offre_count": offre_count,
            "ecole_count": ecole_count,
        },
    )


# ─── Dashboard API ───────────────────────────────────────────────────────

@app.get("/api/ecoles")
async def get_ecoles(token: str = "", departement: str = "", region: str = "",
                     offre_active: str = "", search: str = ""):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if not user or not user["paid"]:
        conn.close()
        raise HTTPException(403, "Accès non autorisé")

    query = """
        SELECT e.id, e.nom, e.email, e.ville, e.departement, e.url_site,
               o.id as offre_id, o.intitule as offre_intitule, o.url_offre,
               o.date_publication
        FROM ecoles e
        LEFT JOIN offres o ON o.ecole_id = e.id
    """
    conditions = []
    params = []

    if departement:
        conditions.append("e.departement = ?")
        params.append(departement)
    if region:
        conditions.append("o.region = ?")
        params.append(region)
    if offre_active == "oui":
        conditions.append("o.id IS NOT NULL")
    if search:
        conditions.append("(e.nom LIKE ? OR e.ville LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY (o.id IS NOT NULL) DESC, o.date_publication DESC, e.nom"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]


# ─── Preview candidature ─────────────────────────────────────────────

@app.get("/api/preview-candidature")
async def preview_candidature(token: str = "", ecole_id: int = 0, regenerate: int = 0):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if not user or not user["paid"]:
        conn.close()
        raise HTTPException(403, "Accès non autorisé")

    ecole = conn.execute("SELECT * FROM ecoles WHERE id = ?", (ecole_id,)).fetchone()
    if not ecole:
        conn.close()
        raise HTTPException(404, "École non trouvée")

    offre = conn.execute(
        "SELECT intitule, description FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
        (ecole_id,)
    ).fetchone()

    # Check if user already has a saved custom letter for this school
    cand = conn.execute(
        "SELECT id, custom_letter FROM candidatures WHERE user_id = ? AND ecole_id = ?",
        (user["id"], ecole_id)
    ).fetchone()

    conn.close()

    # Use saved letter if exists (unless regenerating)
    if cand and cand["custom_letter"] and not regenerate:
        letter = cand["custom_letter"]
    else:
        from services.cover_letter import generate_cover_letter
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

    return {
        "ecole_nom": ecole["nom"],
        "ecole_ville": ecole["ville"],
        "ecole_email": ecole["email"],
        "offre_intitule": offre["intitule"] if offre else None,
        "cover_letter": letter,
        "has_cv": bool(user["cv_path"]),
        "has_diploma": bool(user["diploma_path"]),
        "has_letter": bool(user["letter_path"]),
    }


# ─── Save custom cover letter ────────────────────────────────────────

@app.post("/api/save-letter")
async def save_letter(request: Request):
    data = await request.json()
    token = data.get("token")
    ecole_id = data.get("ecole_id")
    letter = data.get("letter", "").strip()

    if not token or not ecole_id or not letter:
        raise HTTPException(400, "Données manquantes")

    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if not user or not user["paid"]:
        conn.close()
        raise HTTPException(403, "Accès non autorisé")

    # Upsert candidature with custom letter (create if doesn't exist)
    existing = conn.execute(
        "SELECT id FROM candidatures WHERE user_id = ? AND ecole_id = ?",
        (user["id"], ecole_id)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE candidatures SET custom_letter = ? WHERE id = ?",
            (letter, existing["id"])
        )
    else:
        conn.execute("""
            INSERT INTO candidatures (user_id, ecole_id, status, custom_letter, created_at)
            VALUES (?, ?, 'draft', ?, datetime('now'))
        """, (user["id"], ecole_id, letter))

    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Send CV to selected schools ─────────────────────────────────────

@app.post("/api/send-cv")
async def send_cv(request: Request):
    data = await request.json()
    token = data.get("token")
    ecole_ids = data.get("ecole_ids", [])

    if not token or not ecole_ids:
        raise HTTPException(400, "Données manquantes")

    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    conn.close()

    if not user or not user["paid"]:
        raise HTTPException(403, "Accès non autorisé")

    from services.email_sender import send_batch
    results = send_batch(user["id"], ecole_ids)
    return results


# ─── Candidatures status ─────────────────────────────────────────────

@app.get("/api/candidatures")
async def get_candidatures(token: str = ""):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    if not user or not user["paid"]:
        conn.close()
        raise HTTPException(403, "Accès non autorisé")

    rows = conn.execute("""
        SELECT c.ecole_id, c.status, c.sent_at, c.opened_at, c.replied_at
        FROM candidatures c
        WHERE c.user_id = ?
    """, (user["id"],)).fetchall()
    conn.close()

    return {r["ecole_id"]: dict(r) for r in rows}


# ─── Email open tracking pixel ───────────────────────────────────────

# 1x1 transparent PNG
PIXEL_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01'
    b'\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


@app.get("/track/{candidature_id}.png")
async def track_open(candidature_id: int):
    conn = get_connection()
    cand = conn.execute(
        "SELECT * FROM candidatures WHERE id = ?", (candidature_id,)
    ).fetchone()

    if cand and cand["status"] == "sent":
        conn.execute(
            "UPDATE candidatures SET status = 'opened', opened_at = datetime('now') WHERE id = ?",
            (candidature_id,)
        )
        conn.commit()

    conn.close()

    return Response(
        content=PIXEL_PNG,
        media_type="image/png",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ─── PDF Report download ─────────────────────────────────────────────

@app.get("/api/report")
async def download_report(token: str = ""):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
    conn.close()

    if not user or not user["paid"]:
        raise HTTPException(403, "Accès non autorisé")

    from services.pdf_report import generate_report
    pdf_bytes = generate_report(user["id"])

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=voilecv-rapport.pdf"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
