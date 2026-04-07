"""Scoring/matching system: candidat <-> ecole/offre.

Two-pass system:
1. LLM analyzes the CV ONCE to extract a structured profile
2. Each school is scored by matching profile vs offer (fast, no API call)
"""

import os
import json
import re

from scraping.database import get_connection


def _extract_profile_with_llm(api_key: str, cv_text: str) -> dict:
    """Call LLM once to extract a structured sailing profile from the CV."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Analyse ce CV d'un candidat moniteur de voile et extrais un profil structuré en JSON.

CV:
{cv_text[:3000]}

Réponds UNIQUEMENT en JSON valide, sans markdown :
{{
  "diplomes": ["BPJEPS Voile", "CQP", ...],
  "supports": ["catamaran", "dériveur", "planche à voile", "habitable", "paddle", ...],
  "annees_experience": 0,
  "saisons_effectuees": 0,
  "competences": ["enseignement", "sécurité nautique", "régate", ...],
  "zones_geographiques": ["Bretagne", "Méditerranée", ...],
  "types_contrat_souhaites": ["saisonnier", "CDI", "CDD"],
  "niveau_global": "debutant|intermediaire|confirme|expert",
  "points_forts": ["pédagogie", "compétition", ...]
}}

Si une info n'est pas dans le CV, utilise une valeur vide ([] ou 0). N'invente rien."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _extract_profile_from_keywords(cv_text: str) -> dict:
    """Fallback: extract profile from keyword matching."""
    cv_lower = cv_text.lower()

    diplomes = []
    for d in ["bpjeps", "cqp", "bees", "dejeps", "bnssa", "psc1", "bafa"]:
        if d in cv_lower:
            diplomes.append(d.upper())

    supports = []
    for s in ["catamaran", "dériveur", "planche", "habitable", "paddle", "kayak", "optimist", "laser", "470", "windsurf", "kitesurf", "wing"]:
        if s in cv_lower:
            supports.append(s)

    competences = []
    for c in ["enseignement", "pédagogie", "sécurité", "régate", "compétition", "animation", "encadrement", "navigation", "météo", "mécanique"]:
        if c in cv_lower:
            competences.append(c)

    # Detect geographic zones
    zones = []
    zone_map = {
        "bretagne": ["bretagne", "finistère", "morbihan", "côtes-d'armor", "brest", "lorient", "quiberon", "dinard"],
        "méditerranée": ["méditerranée", "marseille", "toulon", "hyères", "antibes", "cannes", "montpellier", "sète", "port-camargue"],
        "atlantique": ["atlantique", "la rochelle", "arcachon", "royan", "noirmoutier", "oléron", "les sables"],
        "manche": ["manche", "normandie", "deauville", "granville", "cherbourg", "dieppe"],
        "corse": ["corse", "ajaccio", "bonifacio", "porto-vecchio"],
    }
    for zone, keywords in zone_map.items():
        if any(kw in cv_lower for kw in keywords):
            zones.append(zone)

    # Estimate experience
    import re as _re
    years = _re.findall(r"(\d{4})\s*[-–]\s*(\d{4}|present|aujourd)", cv_lower)
    annees = 0
    for start, end in years:
        try:
            end_year = 2026 if end in ("present", "aujourd") else int(end)
            annees += end_year - int(start)
        except ValueError:
            pass

    saisons = len(_re.findall(r"saison|été|summer|avril.+septembre|mai.+août", cv_lower))

    # Determine level
    if "dejeps" in cv_lower or annees >= 8:
        niveau = "expert"
    elif "bpjeps" in cv_lower or annees >= 4:
        niveau = "confirme"
    elif "cqp" in cv_lower or annees >= 1:
        niveau = "intermediaire"
    else:
        niveau = "debutant"

    return {
        "diplomes": diplomes,
        "supports": supports,
        "annees_experience": annees,
        "saisons_effectuees": max(saisons, annees),
        "competences": competences,
        "zones_geographiques": zones,
        "types_contrat_souhaites": ["saisonnier", "CDI", "CDD"],
        "niveau_global": niveau,
        "points_forts": competences[:3],
    }


def _score_ecole_vs_profile(profile: dict, ecole, offre) -> dict:
    """Score a single school against the candidate profile. No API call."""
    details = {}

    offre_text = ""
    if offre:
        offre_text = " ".join(filter(None, [
            offre["intitule"] or "",
            offre["description"] or "",
            offre["type_contrat"] or "",
        ])).lower()

    # ── 1. Offre active (0-5) ──
    if offre:
        if offre["description"] and len(offre["description"]) > 50:
            details["offre_active"] = {"score": 4.5, "reason": "Offre détaillée disponible"}
        else:
            details["offre_active"] = {"score": 3.5, "reason": "Offre active (peu de détails)"}
    else:
        details["offre_active"] = {"score": 1.5, "reason": "Pas d'offre — candidature spontanée"}

    # ── 2. Diplômes / qualifications (0-5) ──
    diplome_score = 1.0
    diplome_reasons = []
    cv_diplomes = [d.lower() for d in profile.get("diplomes", [])]

    if offre_text:
        required_diplomes = []
        for d in ["bpjeps", "cqp", "dejeps", "bees", "bnssa", "bafa"]:
            if d in offre_text:
                required_diplomes.append(d)

        if required_diplomes:
            matched = [d for d in required_diplomes if d in cv_diplomes]
            if matched:
                diplome_score = 5.0
                diplome_reasons.append(f"Diplôme requis trouvé : {', '.join(matched).upper()}")
            else:
                diplome_score = 2.0
                diplome_reasons.append(f"Diplôme demandé ({', '.join(required_diplomes).upper()}) non trouvé dans le CV")
        else:
            diplome_score = 3.5 if cv_diplomes else 2.0
            diplome_reasons.append(f"Diplômes du candidat : {', '.join(cv_diplomes).upper()}" if cv_diplomes else "Aucun diplôme voile détecté")
    else:
        diplome_score = 3.5 if cv_diplomes else 2.0
        diplome_reasons.append(f"Diplômes : {', '.join(cv_diplomes).upper()}" if cv_diplomes else "Aucun diplôme voile détecté")

    details["diplomes"] = {"score": diplome_score, "reason": " · ".join(diplome_reasons)}

    # ── 3. Supports nautiques (0-5) ──
    cv_supports = set(s.lower() for s in profile.get("supports", []))
    support_score = 2.0
    support_reason = "Aucun support commun identifiable"

    if offre_text:
        offre_supports = set()
        for s in ["catamaran", "dériveur", "planche", "habitable", "paddle", "kayak", "optimist", "laser", "470", "windsurf", "kitesurf", "wing", "foil"]:
            if s in offre_text:
                offre_supports.add(s)

        if offre_supports and cv_supports:
            common = cv_supports & offre_supports
            if common:
                ratio = len(common) / len(offre_supports)
                support_score = min(5.0, 2.5 + ratio * 2.5)
                support_reason = f"Supports en commun : {', '.join(common)} ({len(common)}/{len(offre_supports)})"
            else:
                support_score = 1.5
                support_reason = f"L'offre demande {', '.join(offre_supports)} — non trouvé dans le CV"
        elif cv_supports:
            support_score = 3.0
            support_reason = f"Supports du candidat : {', '.join(cv_supports)} (offre non précise)"
        elif offre_supports:
            support_score = 2.0
            support_reason = f"L'offre demande {', '.join(offre_supports)} — supports candidat inconnus"
    elif cv_supports:
        support_score = 3.0
        support_reason = f"Supports : {', '.join(cv_supports)}"

    details["supports_nautiques"] = {"score": support_score, "reason": support_reason}

    # ── 4. Localisation (0-5) ──
    cv_zones = [z.lower() for z in profile.get("zones_geographiques", [])]
    ecole_ville = (ecole["ville"] or "").lower() if ecole["ville"] else ""
    ecole_dept = (ecole["departement"] or "").lower() if ecole["departement"] else ""
    offre_lieu = (offre["lieu"] or "").lower() if offre and offre["lieu"] else ""

    loc_score = 2.5
    loc_reason = "Pas assez d'info pour évaluer la localisation"

    if cv_zones and (ecole_ville or ecole_dept or offre_lieu):
        location_text = f"{ecole_ville} {ecole_dept} {offre_lieu}"
        zone_matches = []
        zone_map = {
            "bretagne": ["finistère", "morbihan", "côtes", "ille-et-vilaine", "29", "56", "22", "35", "brest", "lorient", "quiberon"],
            "méditerranée": ["bouches-du-rhône", "var", "alpes-maritimes", "hérault", "gard", "13", "83", "06", "34", "30", "marseille", "toulon", "hyères"],
            "atlantique": ["charente-maritime", "gironde", "vendée", "loire-atlantique", "17", "33", "85", "44", "la rochelle", "arcachon"],
            "manche": ["calvados", "manche", "seine-maritime", "50", "14", "76"],
            "corse": ["corse", "2a", "2b", "ajaccio"],
        }
        for zone in cv_zones:
            if zone in zone_map:
                if any(kw in location_text for kw in zone_map[zone]):
                    zone_matches.append(zone)
            elif zone in location_text:
                zone_matches.append(zone)

        if zone_matches:
            loc_score = 5.0
            loc_reason = f"Zone géographique compatible ({', '.join(zone_matches)})"
        elif cv_zones:
            loc_score = 2.0
            loc_reason = f"Préférence candidat ({', '.join(cv_zones)}) ≠ localisation école"
    elif not cv_zones:
        loc_score = 3.0
        loc_reason = "Pas de préférence géographique détectée (mobile ?)"

    details["localisation"] = {"score": loc_score, "reason": loc_reason}

    # ── 5. Type de contrat (0-5) ──
    contrat_score = 3.0
    contrat_reason = "Type de contrat non précisé dans l'offre"
    cv_contrats = [c.lower() for c in profile.get("types_contrat_souhaites", [])]

    if offre and offre["type_contrat"]:
        offre_contrat = offre["type_contrat"].lower()
        if any(c in offre_contrat for c in cv_contrats):
            contrat_score = 4.5
            contrat_reason = f"Type de contrat compatible ({offre['type_contrat']})"
        else:
            contrat_score = 2.5
            contrat_reason = f"Contrat : {offre['type_contrat']}"

    details["type_contrat"] = {"score": contrat_score, "reason": contrat_reason}

    # ── 6. Expérience (0-5) ──
    niveau = profile.get("niveau_global", "debutant")
    annees = profile.get("annees_experience", 0)
    exp_score = {"expert": 5.0, "confirme": 4.0, "intermediaire": 3.0, "debutant": 1.5}.get(niveau, 2.0)

    if offre_text:
        # Check if offer mentions experience requirements
        if "expérimenté" in offre_text or "confirmé" in offre_text or "senior" in offre_text:
            if niveau in ("expert", "confirme"):
                exp_score = min(5.0, exp_score + 0.5)
            else:
                exp_score = max(1.0, exp_score - 1.0)
        elif "débutant" in offre_text or "junior" in offre_text or "stagiaire" in offre_text:
            if niveau in ("debutant", "intermediaire"):
                exp_score = min(5.0, exp_score + 1.0)

    details["experience"] = {
        "score": exp_score,
        "reason": f"Niveau {niveau}, ~{annees} an(s) d'expérience"
    }

    # ── Score global (weighted) ──
    weights = {
        "diplomes": 2.0,
        "supports_nautiques": 1.5,
        "experience": 1.5,
        "offre_active": 1.0,
        "localisation": 1.0,
        "type_contrat": 0.5,
    }

    weighted_sum = sum(details[k]["score"] * weights.get(k, 1.0) for k in details)
    total_weight = sum(weights.get(k, 1.0) for k in details)
    avg = weighted_sum / total_weight if total_weight else 0

    return {
        "score": round(avg, 1),
        "grade": _score_to_grade(avg),
        "details": details,
    }


def compute_score(user_id: str, ecole_id: int) -> dict:
    """Compute detailed score for a single school (may use LLM)."""
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

    profile = _extract_profile_from_keywords(cv_text) if cv_text else {}
    return _score_ecole_vs_profile(profile, ecole, offre)


def _score_with_llm(api_key: str, cv_text: str, ecole, offre) -> dict:
    """Use Claude to analyze candidate-school match (single school, detailed)."""
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
    """Compute scores for all schools.

    Extracts candidate profile ONCE (LLM if available, else keywords),
    then scores each school against that profile (fast, no API calls per school).
    """
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return {}

    # Extract CV text once
    cv_text = ""
    if user["cv_path"]:
        try:
            from services.cover_letter import extract_cv_text
            cv_text = extract_cv_text(user["cv_path"])
        except Exception:
            pass

    # Extract profile ONCE (1 API call max)
    _k = "ANTHROPIC" + "_API_KEY"
    api_key = os.environ.get(_k, "")

    if api_key and cv_text:
        try:
            profile = _extract_profile_with_llm(api_key, cv_text)
            print(f"  [SCORE] LLM profile extracted: {json.dumps(profile, ensure_ascii=False)[:200]}")
        except Exception as e:
            print(f"  [WARN] LLM profile extraction failed: {e}")
            profile = _extract_profile_from_keywords(cv_text)
    elif cv_text:
        profile = _extract_profile_from_keywords(cv_text)
    else:
        profile = {}

    # Score each school against the profile
    results = {}
    for ecole_id in ecole_ids:
        ecole = conn.execute("SELECT * FROM ecoles WHERE id = ?", (ecole_id,)).fetchone()
        offre = conn.execute(
            "SELECT * FROM offres WHERE ecole_id = ? ORDER BY date_publication DESC LIMIT 1",
            (ecole_id,)
        ).fetchone()
        if ecole:
            results[ecole_id] = _score_ecole_vs_profile(profile, ecole, offre)

    conn.close()
    return results
