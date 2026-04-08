"""Generate personalized cover letters based on CV content and job offer."""

import os
import re


def extract_cv_text(cv_path: str) -> str:
    """Extract text from a PDF CV. Returns empty string on failure."""
    if not cv_path:
        return ""
    try:
        import PyPDF2
        text_parts = []
        with open(cv_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts).strip()
    except Exception as e:
        print(f"  [WARN] Could not extract CV text: {e}")
        return ""


def generate_cover_letter(user_email: str, ecole_nom: str, ecole_ville: str = None,
                          offre_intitule: str = None, offre_description: str = None,
                          has_diploma: bool = False, has_user_letter: bool = False,
                          cv_path: str = None) -> str:
    """Generate a personalized cover letter using LLM if available, else template.

    Uses the candidate's CV text and the job offer details to create a
    truly personalized letter that matches experiences to the offer.
    """
    _k = "ANTHROPIC" + "_API_KEY"
    api_key = os.environ.get(_k, "")
    cv_text = extract_cv_text(cv_path) if cv_path else ""

    if api_key and cv_text:
        try:
            return _generate_with_llm(
                api_key=api_key,
                cv_text=cv_text,
                ecole_nom=ecole_nom,
                ecole_ville=ecole_ville,
                offre_intitule=offre_intitule,
                offre_description=offre_description,
                has_diploma=has_diploma,
                has_user_letter=has_user_letter,
            )
        except Exception as e:
            print(f"  [WARN] LLM generation failed, using template: {e}")

    return _generate_template(
        ecole_nom=ecole_nom,
        ecole_ville=ecole_ville,
        offre_intitule=offre_intitule,
        has_diploma=has_diploma,
        has_user_letter=has_user_letter,
    )


def _generate_with_llm(api_key: str, cv_text: str, ecole_nom: str,
                        ecole_ville: str = None, offre_intitule: str = None,
                        offre_description: str = None, has_diploma: bool = False,
                        has_user_letter: bool = False) -> str:
    """Call Anthropic Claude API to generate a personalized cover letter."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Build context about what's attached
    attachments_info = "Le CV est joint à l'email."
    if has_diploma:
        attachments_info += " Le diplôme du candidat est également joint."
    if has_user_letter:
        attachments_info += " Une lettre de motivation personnelle est également jointe."

    # Build offer context
    offer_context = ""
    if offre_intitule:
        offer_context = f"\n\nOffre d'emploi à laquelle le candidat postule :\n- Intitulé : {offre_intitule}"
        if offre_description:
            # Truncate description to avoid token waste
            desc = offre_description[:1500]
            offer_context += f"\n- Description : {desc}"
    else:
        offer_context = "\n\nIl n'y a pas d'offre d'emploi spécifique — c'est une candidature spontanée."

    lieu = f" à {ecole_ville}" if ecole_ville else ""

    prompt = f"""Tu es un rédacteur expert en lettres de motivation pour des moniteurs de voile.

Rédige une lettre de motivation personnalisée pour postuler auprès de {ecole_nom}{lieu}.

RÈGLES IMPORTANTES :
- Ne reprends PAS le titre exact de l'offre d'emploi. Intègre le contenu de l'offre de manière fluide et naturelle dans la lettre.
- Analyse le CV du candidat et identifie ses expériences pertinentes en voile, nautisme, enseignement ou animation.
- Fais matcher les compétences et expériences du CV avec les besoins de l'offre.
- Si le candidat a des expériences spécifiques (clubs, compétitions, diplômes, saisons), mentionne-les naturellement.
- Le ton doit être professionnel mais passionné, authentique et humain.
- La lettre doit faire 150-250 mots maximum.
- Commence directement par "Madame, Monsieur," sans objet ni en-tête.
- Termine par "Cordialement," suivi du prénom/nom si trouvé dans le CV, sinon juste "Cordialement,".
- {attachments_info}
- N'invente AUCUNE information qui n'est pas dans le CV.

CV du candidat :
{cv_text[:3000]}
{offer_context}

Rédige la lettre de motivation :"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )

    letter = message.content[0].text.strip()

    # Clean up any markdown formatting the LLM might add
    letter = re.sub(r"^```\w*\n?", "", letter)
    letter = re.sub(r"\n?```$", "", letter)
    letter = letter.strip()

    return letter


def _generate_template(ecole_nom: str, ecole_ville: str = None,
                        offre_intitule: str = None, has_diploma: bool = False,
                        has_user_letter: bool = False) -> str:
    """Fallback template-based cover letter when LLM is not available."""
    lieu = f" à {ecole_ville}" if ecole_ville else ""

    if offre_intitule:
        opening = (
            f"Ayant consulté les opportunités proposées par votre structure sur le site "
            f"de la FFVoile, je souhaite vous faire part de ma candidature pour "
            f"rejoindre {ecole_nom}{lieu}."
        )
    else:
        opening = (
            f"Passionné(e) de voile, je me permets de vous adresser ma candidature "
            f"spontanée pour un poste au sein de {ecole_nom}{lieu}."
        )

    if has_diploma:
        qualif = (
            "Vous trouverez ci-joint mon diplôme attestant de mes qualifications. "
            "Mon expérience m'a permis de développer des compétences solides en "
            "enseignement de la voile, en gestion de la sécurité nautique et en "
            "animation de groupes de tous niveaux."
        )
    else:
        qualif = (
            "Titulaire des qualifications requises, mon expérience m'a permis de "
            "développer des compétences solides en enseignement de la voile, en "
            "gestion de la sécurité nautique et en animation de groupes de tous niveaux."
        )

    attachments = "Vous trouverez ci-joint mon CV détaillant mon parcours"
    if has_user_letter:
        attachments += " ainsi que ma lettre de motivation personnelle"
    if has_diploma:
        attachments += " et mon diplôme"
    attachments += "."

    letter = f"""Madame, Monsieur,

{opening}

{qualif} Je suis reconnu(e) pour mon sens pédagogique, mon enthousiasme communicatif et ma capacité à m'adapter à chaque public.

Je serais ravi(e) de mettre mes compétences et ma passion au service de votre structure. {attachments}

Je me tiens à votre disposition pour un entretien à votre convenance.

Cordialement"""

    return letter
