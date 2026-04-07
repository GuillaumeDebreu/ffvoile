# Mode: adapt — Personnalisation CV et lettre par école

## Quand utiliser
Quand l'utilisateur veut personnaliser sa candidature pour une école spécifique.

## Processus de personnalisation

### Lettre de motivation
1. Extraire le texte du CV (PyPDF2)
2. Récupérer les détails de l'offre et de l'école
3. Appeler Claude API avec le prompt de personnalisation
4. Règles :
   - Ne PAS reprendre le titre exact de l'offre
   - Matcher les expériences voile du CV avec les besoins de l'offre
   - Ton professionnel mais passionné
   - 150-250 mots max
   - Ne RIEN inventer qui n'est pas dans le CV

### CV adapté (PDF ATS)
1. Extraire et structurer les données du CV via Claude API
2. Réorganiser les expériences par pertinence pour le poste
3. Adapter le résumé professionnel
4. Générer un PDF clean avec reportlab
5. Format ATS-friendly : pas d'images, pas de colonnes complexes

### Scoring
Critères de matching (note sur 5 chacun) :
1. **experience_voile** — Diplômes, saisons, types de supports
2. **adequation_poste** — Match profil / offre
3. **localisation** — Cohérence géographique
4. **supports_nautiques** — Match supports (catamaran, dériveur, planche, habitable)
5. **type_contrat** — Adéquation saisonnier/CDI/CDD

Grade final : A (>= 4.5), B (>= 3.5), C (>= 2.5), D (>= 1.5), F (< 1.5)
