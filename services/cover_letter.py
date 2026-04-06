"""Generate personalized cover letters for each school/offer."""

import os


def generate_cover_letter(user_email: str, ecole_nom: str, ecole_ville: str = None,
                          offre_intitule: str = None, cv_text: str = None) -> str:
    """Generate a cover letter adapted to the school and offer.

    In production, this calls an LLM API. For now, uses a quality template
    that personalizes based on available data.
    """
    # Build context parts
    lieu = f" à {ecole_ville}" if ecole_ville else ""
    offre_ref = ""
    if offre_intitule:
        offre_ref = (
            f"\n\nJ'ai pris connaissance de votre offre \"{offre_intitule}\" "
            f"publiée sur le site de la FFVoile et je souhaite vous faire part "
            f"de ma candidature."
        )

    letter = f"""Madame, Monsieur,

Passionné(e) de voile et titulaire des qualifications requises, je me permets de vous adresser ma candidature pour un poste au sein de {ecole_nom}{lieu}.{offre_ref}

Mon expérience m'a permis de développer des compétences solides en enseignement de la voile, en gestion de la sécurité nautique et en animation de groupes de tous niveaux. Je suis reconnu(e) pour mon sens pédagogique, mon enthousiasme communicatif et ma capacité à m'adapter à chaque public.

Je serais ravi(e) de mettre mes compétences et ma passion au service de votre structure. Vous trouverez ci-joint mon CV détaillant mon parcours.

Je me tiens à votre disposition pour un entretien à votre convenance.

Cordialement,
Candidature via VoileCV"""

    return letter
