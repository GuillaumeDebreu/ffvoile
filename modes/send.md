# Mode: send — Envoi des candidatures

## Quand utiliser
Quand l'utilisateur demande d'envoyer des CV, de vérifier les envois, ou de diagnostiquer des problèmes d'email.

## Pipeline d'envoi
1. L'utilisateur sélectionne les écoles sur le dashboard
2. Pour chaque école, le système vérifie :
   - Email de contact disponible
   - Candidature non déjà envoyée (protection doublon)
3. Génère la lettre de motivation (utilise la lettre custom si sauvegardée)
4. Envoie via Resend API avec :
   - CV en pièce jointe
   - Diplôme en pièce jointe (si uploadé)
   - Pixel de tracking pour ouverture
   - Reply-To vers l'email du candidat
5. Met à jour le statut : pending → sent (ou send_failed)

## Statuts
- `draft` → lettre sauvegardée, pas encore envoyé
- `pending` → en cours d'envoi
- `sent` → email envoyé avec succès
- `send_failed` → erreur d'envoi
- `opened` → l'école a ouvert l'email (pixel tracking)
- `replied` → réponse reçue (manuel)

## Diagnostics courants
- "RESEND_API_KEY not set" → Ajouter la variable d'environnement
- Envoi uniquement vers son propre email → Domaine non vérifié dans Resend, utilise onboarding@resend.dev
- Email bounce → Vérifier l'adresse dans la table ecoles
