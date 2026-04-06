"""Generate personalized cover letters for each school/offer."""


def generate_cover_letter(user_email: str, ecole_nom: str, ecole_ville: str = None,
                          offre_intitule: str = None, has_diploma: bool = False,
                          has_user_letter: bool = False) -> str:
    """Generate a cover letter adapted to the school and offer.

    In production, this calls an LLM API. For now, uses a quality template
    that personalizes based on available data.
    """
    lieu = f" à {ecole_ville}" if ecole_ville else ""

    # Opening — reference the offer if one exists
    if offre_intitule:
        opening = (
            f"J'ai pris connaissance de votre offre \"{offre_intitule}\" "
            f"publiée sur le site de la FFVoile et je souhaite vous faire part "
            f"de ma candidature pour rejoindre {ecole_nom}{lieu}."
        )
    else:
        opening = (
            f"Passionné(e) de voile, je me permets de vous adresser ma candidature "
            f"spontanée pour un poste au sein de {ecole_nom}{lieu}."
        )

    # Qualifications paragraph — adapt if diploma is attached
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

    # Closing — mention user letter if attached
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

Cordialement,
Candidature via VoileCV"""

    return letter
