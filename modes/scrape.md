# Mode: scrape — Mise à jour de la base de données

## Quand utiliser
Quand l'utilisateur demande de mettre à jour les offres, rafraîchir la base, ou vérifier les nouvelles offres.

## Actions
1. Lancer `scrape_all_offers()` depuis `scraping/scrape_offres.py`
2. Vérifier les résultats (nombre d'offres, nombre d'écoles)
3. Reporter les éventuelles erreurs de parsing
4. Mettre à jour la date de dernière mise à jour

## Points d'attention
- Le scraping respecte un délai de 0.5s entre chaque requête
- Les offres existantes sont mises à jour (upsert via ffvoile_id)
- Les écoles sont dédupliquées par (nom, ville)
- Le endpoint `/api/cron-refresh?key=CRON_KEY` permet le refresh externe
- En cas d'erreur réseau, réessayer jusqu'à 3 fois

## Vérification post-scrape
```python
from scraping.database import get_connection
conn = get_connection()
offres = conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
ecoles = conn.execute("SELECT COUNT(*) FROM ecoles").fetchone()[0]
print(f"Base: {offres} offres, {ecoles} écoles")
conn.close()
```
