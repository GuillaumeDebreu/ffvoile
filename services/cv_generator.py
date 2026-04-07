"""ATS-optimized CV PDF generation.

Inspired by career-ops cv-template.html and generate-pdf.mjs.
Uses Claude API to restructure the candidate's CV for each school/offer,
then generates a clean PDF with reportlab.
"""

import os
import json
import re
from io import BytesIO

from services.cover_letter import extract_cv_text


def generate_adapted_cv(user_id: str, ecole_id: int) -> bytes:
    """Generate an ATS-optimized PDF CV tailored for a specific school.

    Returns PDF bytes, or None on failure.
    """
    from scraping.database import get_connection

    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    ecole = conn.execute("SELECT * FROM ecoles WHERE id = ?", (ecole_id,)).fetchone()
    offre = conn.execute(
        "SELECT * FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
        (ecole_id,)
    ).fetchone()
    conn.close()

    if not user or not user["cv_path"]:
        return None

    cv_text = extract_cv_text(user["cv_path"])
    if not cv_text:
        return None

    # Use LLM to restructure CV data
    _k = "ANTHROPIC" + "_API_KEY"
    api_key = os.environ.get(_k, "")

    offre_context = ""
    if offre:
        offre_context = f"""
Offre: {offre['intitule']}
Lieu: {offre['lieu'] or ecole['ville'] or ''}
Type contrat: {offre['type_contrat'] or 'Non précisé'}
Description: {(offre['description'] or '')[:1000]}
"""

    if api_key:
        try:
            cv_data = _extract_cv_structure(api_key, cv_text, ecole, offre_context)
        except Exception as e:
            print(f"  [WARN] LLM CV extraction failed: {e}")
            cv_data = _fallback_cv_data(cv_text)
    else:
        cv_data = _fallback_cv_data(cv_text)

    return _render_pdf(cv_data, ecole["nom"] if ecole else "")


def _extract_cv_structure(api_key: str, cv_text: str, ecole, offre_context: str) -> dict:
    """Use Claude to extract structured CV data and optimize for the offer."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    ecole_nom = ecole["nom"] if ecole else ""
    ecole_ville = ecole["ville"] if ecole else ""

    prompt = f"""Tu es un expert en recrutement et optimisation de CV pour moniteurs de voile.

Extrais et restructure le CV suivant en JSON pour générer un CV PDF professionnel et ATS-friendly.
Adapte le contenu pour postuler auprès de {ecole_nom} ({ecole_ville}).
{offre_context}

RÈGLES:
- Mets en valeur les expériences en voile/nautisme en premier
- Adapte le résumé professionnel au poste visé
- N'invente RIEN qui n'est pas dans le CV original
- Réorganise les expériences par pertinence pour ce poste
- Le JSON doit être strictement valide

CV ORIGINAL:
{cv_text[:3000]}

Réponds UNIQUEMENT en JSON valide:
{{
  "nom": "Prénom Nom",
  "email": "email@example.com",
  "telephone": "06...",
  "ville": "Ville",
  "resume": "Résumé professionnel adapté en 2-3 phrases...",
  "competences": ["Compétence 1", "Compétence 2", ...],
  "experiences": [
    {{
      "poste": "Titre du poste",
      "entreprise": "Nom",
      "lieu": "Ville",
      "periode": "2023 - 2024",
      "details": ["Détail 1", "Détail 2"]
    }}
  ],
  "formations": [
    {{
      "diplome": "Nom du diplôme",
      "etablissement": "Nom",
      "annee": "2023"
    }}
  ],
  "certifications": ["BPJEPS Voile", "PSC1", ...]
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _fallback_cv_data(cv_text: str) -> dict:
    """Basic fallback when LLM is not available."""
    lines = cv_text.split("\n")
    nom = lines[0].strip() if lines else "Candidat"

    return {
        "nom": nom,
        "email": "",
        "telephone": "",
        "ville": "",
        "resume": "Moniteur de voile passionné, à la recherche d'une nouvelle opportunité.",
        "competences": ["Voile", "Enseignement nautique", "Sécurité"],
        "experiences": [],
        "formations": [],
        "certifications": [],
    }


def _render_pdf(cv_data: dict, ecole_nom: str = "") -> bytes:
    """Render the structured CV data into a clean ATS PDF using reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )

    # Colors (nautical theme)
    navy = HexColor("#0a1628")
    teal = HexColor("#0d7377")
    gray = HexColor("#555555")
    light_bg = HexColor("#f0f7f7")

    styles = getSampleStyleSheet()

    s_name = ParagraphStyle("CVName", parent=styles["Title"],
                            fontSize=20, leading=24, textColor=navy,
                            spaceAfter=2 * mm, alignment=TA_LEFT)
    s_contact = ParagraphStyle("CVContact", parent=styles["Normal"],
                               fontSize=9, leading=12, textColor=gray,
                               spaceAfter=4 * mm)
    s_section = ParagraphStyle("CVSection", parent=styles["Heading2"],
                               fontSize=12, leading=15, textColor=teal,
                               spaceBefore=6 * mm, spaceAfter=2 * mm,
                               borderWidth=0.5, borderColor=HexColor("#e0e0e0"),
                               borderPadding=(0, 0, 2, 0))
    s_body = ParagraphStyle("CVBody", parent=styles["Normal"],
                            fontSize=10, leading=14, textColor=navy)
    s_sub = ParagraphStyle("CVSub", parent=styles["Normal"],
                           fontSize=9, leading=12, textColor=gray)
    s_bullet = ParagraphStyle("CVBullet", parent=styles["Normal"],
                              fontSize=9.5, leading=13, textColor=HexColor("#333333"),
                              leftIndent=12, bulletIndent=0)
    s_tag = ParagraphStyle("CVTag", parent=styles["Normal"],
                           fontSize=9, leading=12, textColor=teal)

    story = []

    # Header
    nom = cv_data.get("nom", "Candidat")
    story.append(Paragraph(nom, s_name))

    contact_parts = []
    if cv_data.get("email"):
        contact_parts.append(cv_data["email"])
    if cv_data.get("telephone"):
        contact_parts.append(cv_data["telephone"])
    if cv_data.get("ville"):
        contact_parts.append(cv_data["ville"])
    if contact_parts:
        story.append(Paragraph(" | ".join(contact_parts), s_contact))

    # Gradient line
    story.append(Spacer(1, 1 * mm))

    # Professional summary
    if cv_data.get("resume"):
        story.append(Paragraph("PROFIL", s_section))
        story.append(Paragraph(cv_data["resume"], s_body))

    # Competences
    comps = cv_data.get("competences", [])
    if comps:
        story.append(Paragraph("COMPÉTENCES CLÉS", s_section))
        story.append(Paragraph(" &bull; ".join(comps), s_tag))

    # Experiences
    exps = cv_data.get("experiences", [])
    if exps:
        story.append(Paragraph("EXPÉRIENCE PROFESSIONNELLE", s_section))
        for exp in exps:
            poste = exp.get("poste", "")
            entreprise = exp.get("entreprise", "")
            lieu = exp.get("lieu", "")
            periode = exp.get("periode", "")

            header = f"<b>{poste}</b>"
            if entreprise:
                header += f" — <font color='#0d7377'>{entreprise}</font>"
            story.append(Paragraph(header, s_body))

            sub_parts = []
            if lieu:
                sub_parts.append(lieu)
            if periode:
                sub_parts.append(periode)
            if sub_parts:
                story.append(Paragraph(" | ".join(sub_parts), s_sub))

            for detail in exp.get("details", []):
                story.append(Paragraph(f"• {detail}", s_bullet))
            story.append(Spacer(1, 2 * mm))

    # Formations
    formations = cv_data.get("formations", [])
    if formations:
        story.append(Paragraph("FORMATION", s_section))
        for f in formations:
            line = f"<b>{f.get('diplome', '')}</b>"
            if f.get("etablissement"):
                line += f" — {f['etablissement']}"
            if f.get("annee"):
                line += f" ({f['annee']})"
            story.append(Paragraph(line, s_body))
            story.append(Spacer(1, 1 * mm))

    # Certifications
    certs = cv_data.get("certifications", [])
    if certs:
        story.append(Paragraph("CERTIFICATIONS", s_section))
        story.append(Paragraph(" &bull; ".join(certs), s_tag))

    doc.build(story)
    return buf.getvalue()
