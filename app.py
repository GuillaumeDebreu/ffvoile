"""VoileCV - FastAPI backend."""

import os
import uuid
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime

import stripe
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from scraping.database import get_connection, init_db

# Config
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_PLACEHOLDER")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "pk_test_PLACEHOLDER")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_PLACEHOLDER")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
PRICE_CENTS = 999  # 9.99€

stripe.api_key = STRIPE_SECRET_KEY

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
            stripe_session_id TEXT,
            paid INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS candidatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL REFERENCES users(id),
            ecole_id INTEGER NOT NULL REFERENCES ecoles(id),
            status TEXT NOT NULL DEFAULT 'pending',
            sent_at TEXT,
            opened_at TEXT,
            replied_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, ecole_id)
        );

        CREATE INDEX IF NOT EXISTS idx_candidatures_user ON candidatures(user_id);
        CREATE INDEX IF NOT EXISTS idx_candidatures_status ON candidatures(status);
    """)
    conn.commit()
    conn.close()


init_app_db()


# ─── Landing Page ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"stripe_key": STRIPE_PUBLISHABLE_KEY},
    )


# ─── CV Upload ───────────────────────────────────────────────────────────

@app.post("/api/upload-cv")
async def upload_cv(file: UploadFile = File(...), email: str = Form("")):
    if not email or "@" not in email:
        raise HTTPException(400, "Email invalide")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Seuls les fichiers PDF sont acceptés")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB max
        raise HTTPException(400, "Fichier trop volumineux (max 5 Mo)")

    # Save file
    user_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    filename = f"{user_id}.pdf"
    filepath = UPLOAD_DIR / filename
    filepath.write_bytes(content)

    # Create user record
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO users (id, email, token, cv_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                cv_path = excluded.cv_path,
                token = excluded.token
        """, (user_id, email, token, str(filepath), datetime.now().isoformat()))
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
            success_url=f"{BASE_URL}/dashboard?token={token}",
            cancel_url=f"{BASE_URL}/?cancelled=true",
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
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
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

    # For demo: auto-mark as paid if coming from Stripe redirect
    # In production, rely on webhook only
    if not user["paid"]:
        conn.execute("UPDATE users SET paid = 1 WHERE id = ?", (user["id"],))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"user": dict(user), "token": token},
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
