# Mode: report — Génération des rapports

## Quand utiliser
Quand l'utilisateur demande un rapport récapitulatif, des statistiques, ou un export PDF.

## Rapports disponibles

### 1. Rapport PDF candidatures
- Endpoint: `/api/report?token=TOKEN`
- Contenu: tableau récap de toutes les candidatures avec statut, dates
- Généré via reportlab

### 2. CV adapté par école
- Endpoint: `/api/cv-adapte?token=TOKEN&ecole_id=ID`
- Contenu: CV restructuré et optimisé ATS pour une école spécifique
- Utilise Claude API pour adapter le contenu au poste

### 3. Données dashboard
- Nombre total d'écoles et offres actives
- Date de dernière mise à jour
- Scores de matching par école

## Métriques clés à suivre
- Taux d'envoi (sent / total sélectionné)
- Taux d'ouverture (opened / sent)
- Taux de réponse (replied / sent)
- Score moyen des écoles ciblées
