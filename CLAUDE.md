# VoileCV - Trouve ton job de moniteur de voile en 1 clic

## Projet

Plateforme qui aide les moniteurs de voile à envoyer des candidatures personnalisées aux 100+ écoles de voile en France. Le système scrape les offres FFVoile, génère des CV et lettres de motivation adaptés par IA, et envoie les candidatures par email.

## Stack

- **Backend**: Python (FastAPI), SQLite, Jinja2
- **Scraping**: BeautifulSoup + lxml (FFVoile)
- **IA**: Anthropic Claude API (lettre de motivation, scoring, CV adapté)
- **Email**: Resend API
- **PDF**: reportlab
- **Deploy**: Railway (Nixpacks)
- **Cron**: cron-job.org (refresh offres toutes les 6h)

## Structure

```
ffvoile/
├── app.py                    # FastAPI backend (routes, API endpoints)
├── scraping/
│   ├── database.py           # SQLite schema, helpers (ecoles, offres, users, candidatures)
│   └── scrape_offres.py      # FFVoile job offer scraper
├── services/
│   ├── cover_letter.py       # Génération lettre de motivation (LLM + fallback template)
│   ├── cv_generator.py       # Génération CV PDF ATS-optimisé par école
│   ├── email_sender.py       # Envoi emails via Resend API
│   ├── scoring.py            # Scoring candidat <-> école (LLM + fallback heuristique)
│   ├── pdf_report.py         # Rapport PDF récapitulatif des candidatures
│   ├── cron_refresh.py       # Script de refresh des offres
│   └── integrity.py          # Vérification intégrité pipeline
├── templates/
│   ├── landing.html          # Landing page (upload CV, email)
│   └── dashboard.html        # Dashboard candidat (tableau, filtres, preview, envoi)
├── static/
│   ├── style.css             # Design system nautique
│   └── app.js                # Frontend logic (upload, drag & drop)
├── modes/                    # Claude Code skill modes
│   ├── scrape.md             # Mode: mise à jour base de données
│   ├── send.md               # Mode: envoi des candidatures
│   ├── report.md             # Mode: génération des rapports
│   └── adapt.md              # Mode: personnalisation CV par école
├── CLAUDE.md                 # Ce fichier
├── requirements.txt
├── Procfile
├── railway.json
└── runtime.txt
```

## Modes (Skills Claude Code)

| Commande | Mode | Description |
|----------|------|-------------|
| "scrape les offres" | `scrape` | Relance le scraping FFVoile, MAJ base |
| "envoie les CV" | `send` | Gère l'envoi des candidatures |
| "génère un rapport" | `report` | Génère le PDF récap |
| "adapte le CV" | `adapt` | Personnalise CV pour une école |

## Base de données SQLite

### Tables
- **ecoles**: id, nom, email, ville, departement, url_site, source, date_scrape
- **offres**: id, ecole_id, ffvoile_id, intitule, nom_structure, lieu, departement, type_contrat, date_publication, url_offre, region, salaire, contact_nom, contact_email, contact_tel, description, date_scrape
- **users**: id, email, token, cv_path, diploma_path, letter_path, stripe_session_id, paid, created_at
- **candidatures**: id, user_id, ecole_id, status, custom_letter, sent_at, opened_at, replied_at, created_at

### Statuts candidature (canoniques)
| Statut | Quand |
|--------|-------|
| `draft` | Lettre sauvegardée mais pas envoyée |
| `pending` | En attente d'envoi |
| `sent` | Email envoyé |
| `send_failed` | Échec d'envoi |
| `opened` | Email ouvert (pixel tracking) |
| `replied` | Réponse reçue |

## Variables d'environnement (runtime)

- `ANTHROPIC_API_KEY` - Clé API Claude pour IA
- `RESEND_API_KEY` - Clé API Resend pour emails
- `RESEND_FROM` - Adresse d'envoi (ex: `VoileCV <contact@voilecv.fr>`)
- `BASE_URL` - URL publique de l'app
- `CRON_KEY` - Clé secrète pour l'endpoint cron
- `STRIPE_SECRET_KEY` - (inactif pour le moment)
- `STRIPE_PUBLISHABLE_KEY` - (inactif pour le moment)
- `STRIPE_WEBHOOK_SECRET` - (inactif pour le moment)

## Conventions

- Les noms de variables env sont concaténés dans le code (`"ANTHROPIC" + "_API_KEY"`) pour éviter que Railpack les détecte comme secrets de build
- Toujours utiliser `os.environ.get()` via le helper `_env()` dans app.py
- Le scraping respecte un délai de 0.5s entre chaque requête
- Les emails utilisent un pixel de tracking 1x1 transparent pour détecter l'ouverture
- Le scoring retourne une note A-F (A >= 4.5, B >= 3.5, C >= 2.5, D >= 1.5, F < 1.5)

## Règles

- Ne JAMAIS envoyer d'email sans que l'utilisateur ait explicitement cliqué "Envoyer"
- Le CV original uploadé n'est jamais modifié
- Les lettres personnalisées sont sauvegardées et modifiables avant envoi
- Le diplôme est joint automatiquement si uploadé
- Les candidatures déjà envoyées ne peuvent pas être renvoyées (protection anti-doublon)
