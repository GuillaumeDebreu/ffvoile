"""Generate PDF recap report for a user's candidatures."""

import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from scraping.database import get_connection


def generate_report(user_id: str) -> bytes:
    """Generate a PDF report of all candidatures for a user."""
    conn = get_connection()

    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        raise ValueError("User not found")

    candidatures = conn.execute("""
        SELECT c.*, e.nom as ecole_nom, e.ville, e.departement, e.email as ecole_email,
               o.intitule as offre_intitule
        FROM candidatures c
        JOIN ecoles e ON c.ecole_id = e.id
        LEFT JOIN offres o ON o.ecole_id = e.id
        ORDER BY c.sent_at DESC
    """).fetchall()

    conn.close()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title_style = ParagraphStyle('Title', parent=styles['Title'],
                                  fontSize=18, textColor=colors.HexColor('#0a1628'))
    elements.append(Paragraph("VoileCV - Rapport de candidatures", title_style))
    elements.append(Spacer(1, 8*mm))

    # Summary
    elements.append(Paragraph(f"<b>Candidat :</b> {user['email']}", styles['Normal']))
    elements.append(Paragraph(
        f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 4*mm))

    status_labels = {
        'pending': 'En attente', 'sent': 'Envoyé', 'send_failed': 'Échec',
        'opened': 'Ouvert', 'replied': 'Réponse reçue',
    }

    total = len(candidatures)
    sent = sum(1 for c in candidatures if c['status'] in ('sent', 'opened', 'replied'))
    opened = sum(1 for c in candidatures if c['status'] == 'opened')
    replied = sum(1 for c in candidatures if c['status'] == 'replied')

    elements.append(Paragraph(
        f"<b>Total :</b> {total} | <b>Envoyées :</b> {sent} | "
        f"<b>Ouvertes :</b> {opened} | <b>Réponses :</b> {replied}",
        styles['Normal']))
    elements.append(Spacer(1, 6*mm))

    if not candidatures:
        elements.append(Paragraph(
            "<i>Aucune candidature envoyée pour le moment.</i>", styles['Normal']))
        doc.build(elements)
        return buf.getvalue()

    # Table
    header = ['École', 'Ville', 'Dept', 'Offre', 'Statut']
    data = [header]
    for c in candidatures:
        data.append([
            (c['ecole_nom'] or '')[:30],
            (c['ville'] or '')[:20],
            (c['departement'] or '')[:5],
            (c['offre_intitule'] or '—')[:25],
            status_labels.get(c['status'], c['status']),
        ])

    table = Table(data, colWidths=[55*mm, 35*mm, 15*mm, 45*mm, 25*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a1628')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    return buf.getvalue()
