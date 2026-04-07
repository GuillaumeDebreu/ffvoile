"""Scoring/matching system: candidat <-> ecole/offre.

Inspired by career-ops oferta.md evaluation, adapted for sailing instructors.

Uses Claude API when available, otherwise a rule-based fallback.
Criteria:
- Location match (candidate preference vs school location)
- Sailing supports (catamaran, deriveur, planche, habitable)
- Contract type match (saisonnier, CDI, CDD)
- Active offer vs candidature spontanee
- Experience level match
"""

import os
import json
import re

from scraping.database import get_connection


def compute_score(user_id: str, ecole_id: int) -> dict:
    """Compute a compatibility score between a candidate and a school.

    Returns: {
        "score": float (0-5),
        "grade": str (A-F),
        "details": { criterion: { score: float, reason: str } }
    }
    """
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    ecole = conn.execute("SELECT * FROM ecoles WHERE id = ?", (ecole_id,)).fetchone()
    offre = conn.execute(
        "SELECT * FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
        (ecole_id,)
    ).fetchone()
    conn.close()

    if not user or not ecole:
        return {"score": 0, "grade": "F", "details": {}}

    # Try LLM scoring if API key available and we have CV text
    _k = "ANTHROPIC" + "_API_KEY"
    api_key = os.environ.get(_k, "")
    cv_text = ""
    if user["cv_path"]:
        try:
            from services.cover_letter import extract_cv_text
            cv_text = extract_cv_text(user["cv_path"])
        except Exception:
            pass

    if api_key and cv_text and offre:
        try:
            return _score_with_llm(api_key, cv_text, ecole, offre)
        except Exception as e:
            print(f"  [WARN] LLM scoring failed: {e}")

    return _score_rule_based(ecole, offre, cv_text)


def _score_with_llm(api_key: str, cv_text: str, ecole, offre) -> dict:
    """Use Claude to analyze candidate-school match."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    offre_desc = offre["description"][:1500] if offre["description"] else ""
    offre_info = f"""
Offre: {offre['intitule']}
Structure: {offre['nom_structure'] or ecole['nom']}
Lieu: {offre['lieu'] or ecole['ville'] or 'Non précisé'}
Département: {offre['departement'] or ecole['departement'] or 'Non précisé'}
Type de contrat: {offre['type_contrat'] or 'Non précisé'}
Salaire: {offre['salaire'] or 'Non précisé'}
Description: {offre_desc}
"""

    prompt = f"""Tu es un expert en recrutement de moniteurs de voile en France.

Évalue la compatibilité entre ce candidat et cette offre/école de voile.

CV DU CANDIDAT:
{cv_text[:2500]}

ÉCOLE / OFFRE:
{offre_info}

Évalue selon ces 5 critères (note sur 5 chacun):

1. **experience_voile**: Expérience en voile/nautisme du candidat (diplômes BPJEPS/CQP, saisons, types de supports)
2. **adequation_poste**: Adéquation entre le profil et ce que l'offre demande
3. **localisation**: Cohérence géographique (le candidat semble-t-il mobile/intéressé par cette zone ?)
4. **supports_nautiques**: Match entre les supports maîtrisés et ceux de l'école (catamaran, dériveur, planche, habitable, paddle)
5. **type_contrat**: Adéquation avec le type de contrat proposé (saisonnier, CDI, CDD)

Réponds UNIQUEMENT en JSON valide, sans markdown, sans commentaire :
{{
  "experience_voile": {{"score": X.X, "reason": "..."}},
  "adequation_poste": {{"score": X.X, "reason": "..."}},
  "localisation": {{"score": X.X, "reason": "..."}},
  "supports_nautiques": {{"score": X.X, "reason": "..."}},
  "type_contrat": {{"score": X.X, "reason": "..."}}
}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Extract JSON from potential markdown wrapper
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    details = json.loads(raw)

    scores = [v["score"] for v in details.values()]
    avg = sum(scores) / len(scores) if scores else 0

    return {
        "score": round(avg, 1),
        "grade": _score_to_grade(avg),
        "details": details,
    }


def _score_rule_based(ecole, offre, cv_text: str = "") -> dict:
    """Fallback scoring without LLM — uses simple heuristics."""
    details = {}
    cv_lower = cv_text.lower() if cv_text else ""

    # 1. Active offer bonus
    if offre:
        details["offre_active"] = {"score": 4.0, "reason": "Offre d'emploi active"}
    else:
        details["offre_active"] = {"score": 2.0, "reason": "Candidature spontanée (pas d'offre active)"}

    # 2. Email available (can actually send)
    if ecole["email"]:
        details["contact"] = {"score": 5.0, "reason": "Email de contact disponible"}
    else:
        details["contact"] = {"score": 1.0, "reason": "Pas d'email de contact"}

    # 3. CV sailing keywords
    sailing_keywords = [
        "bpjeps", "cqp", "moniteur", "voile", "catamaran", "dériveur",
        "planche", "habitable", "nautique", "régate", "skipper",
        "paddle", "kayak", "navigation", "vent", "sécurité nautique",
    ]
    matches = sum(1 for kw in sailing_keywords if kw in cv_lower)
    if cv_lower:
        kw_score = min(5.0, 1.0 + matches * 0.5)
        details["experience_voile"] = {
            "score": kw_score,
            "reason": f"{matches} mot(s)-clé(s) voile trouvé(s) dans le CV"
        }
    else:
        details["experience_voile"] = {"score": 2.5, "reason": "CV non analysable"}

    # 4. Contract type detection
    if offre and offre["type_contrat"]:
        details["type_contrat"] = {"score": 3.5, "reason": f"Contrat : {offre['type_contrat']}"}
    else:
        details["type_contrat"] = {"score": 3.0, "reason": "Type de contrat non précisé"}

    # 5. Location info
    if ecole["ville"]:
        details["localisation"] = {"score": 3.5, "reason": f"Localisation : {ecole['ville']}"}
    else:
        details["localisation"] = {"score": 2.5, "reason": "Ville non renseignée"}

    scores = [v["score"] for v in details.values()]
    avg = sum(scores) / len(scores) if scores else 0

    return {
        "score": round(avg, 1),
        "grade": _score_to_grade(avg),
        "details": details,
    }


def _score_to_grade(score: float) -> str:
    if score >= 4.5:
        return "A"
    elif score >= 3.5:
        return "B"
    elif score >= 2.5:
        return "C"
    elif score >= 1.5:
        return "D"
    else:
        return "F"


def compute_scores_batch(user_id: str, ecole_ids: list[int]) -> dict[int, dict]:
    """Compute scores for multiple schools using RULE-BASED scoring only.

    LLM scoring is too slow for batch (100+ schools). Use compute_score()
    for individual detailed scoring with LLM.
    Returns {ecole_id: score_dict}.
    """
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return {}

    cv_text = ""
    if user["cv_path"]:
        try:
            from services.cover_letter import extract_cv_text
            cv_text = extract_cv_text(user["cv_path"])
        except Exception:
            pass

    results = {}
    for ecole_id in ecole_ids:
        ecole = conn.execute("SELECT * FROM ecoles WHERE id = ?", (ecole_id,)).fetchone()
        offre = conn.execute(
            "SELECT * FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
            (ecole_id,)
        ).fetchone()
        if ecole:
            results[ecole_id] = _score_rule_based(ecole, offre, cv_text)

    conn.close()
    return results
