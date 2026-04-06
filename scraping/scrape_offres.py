"""Scrape job offers from FFVoile emploi page."""

import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from scraping.database import get_connection, init_db, upsert_ecole, upsert_offre

BASE_URL = "https://www.ffvoile.fr/ffv/web/services/emploi/annonces"
LIST_URL = f"{BASE_URL}/liste_offre.asp?type=employeur&num_page={{page}}"
DETAIL_URL = f"{BASE_URL}/display.asp?id_annonce={{id}}&type=employeur"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_page(url, retries=3):
    for i in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.RequestException as e:
            if i == retries - 1:
                print(f"  [ERROR] Failed to fetch {url}: {e}")
                return None
            time.sleep(2 ** i)


def parse_listing_page(html):
    """Parse the listing page and extract offer summaries."""
    soup = BeautifulSoup(html, "lxml")
    offers = []

    # Find all links to offer detail pages
    for link in soup.find_all("a", href=re.compile(r"display\.asp\?id_annonce=\d+")):
        href = link.get("href", "")
        match = re.search(r"id_annonce=(\d+)", href)
        if not match:
            continue

        ffvoile_id = int(match.group(1))
        title = link.get_text(strip=True)

        # Navigate up to find the row/container with all fields
        row = link.find_parent("tr") or link.find_parent("div")
        cells = []
        if row:
            cells = row.find_all("td") or row.find_all("span")

        # Try to extract employer, region, date from sibling cells
        nom_structure = None
        region = None
        date_pub = None

        if len(cells) >= 4:
            nom_structure = cells[1].get_text(strip=True) if cells[1] else None
            region = cells[2].get_text(strip=True) if cells[2] else None
            date_pub = cells[3].get_text(strip=True) if cells[3] else None
        elif len(cells) >= 2:
            # Fallback: try to get text from adjacent elements
            texts = [c.get_text(strip=True) for c in cells]
            for t in texts:
                if re.match(r"\d{4}-\d{2}-\d{2}", t):
                    date_pub = t
                elif t != title and not nom_structure:
                    nom_structure = t

        offers.append({
            "ffvoile_id": ffvoile_id,
            "intitule": title,
            "nom_structure": nom_structure,
            "region": region,
            "date_publication": date_pub,
            "url_offre": f"{BASE_URL}/display.asp?id_annonce={ffvoile_id}&type=employeur",
        })

    return offers


def _get_field_after_label(soup, label_pattern):
    """Find a <strong> tag matching label_pattern and return the text that follows it."""
    tag = soup.find("strong", string=re.compile(label_pattern, re.IGNORECASE))
    if not tag:
        return None
    # Get the next sibling text or the parent's remaining text
    parent = tag.parent
    if parent:
        full = parent.get_text(" ", strip=True)
        # Remove the label part
        label_text = tag.get_text(strip=True)
        after = full.split(label_text, 1)[-1].strip().lstrip(":").strip()
        # Clean up: stop at next label-like pattern or excessive whitespace
        after = re.split(r"\s{3,}", after)[0]
        return after if after else None
    return None


def _clean_city(city):
    """Clean up city name: remove trailing single letter, junk words, extra spaces."""
    city = re.split(r"\b(?:Téléphone|Liens|Référence|Emploi|Espace)\b", city)[0].strip()
    # Remove trailing single letter (artifact from FFVoile addresses like "DAMGAN L")
    city = re.sub(r"\s+[A-Z]$", "", city)
    return city.strip()


def parse_detail_page(html):
    """Parse a detail page using the <strong> label structure."""
    soup = BeautifulSoup(html, "lxml")
    data = {}

    # Club name: "Club : NAME (CODE)"
    club_tag = soup.find("strong", string=re.compile(r"Club\s*:", re.IGNORECASE))
    if not club_tag:
        # Sometimes it's a link containing "Club :"
        for tag in soup.find_all(["a", "h3", "b", "strong"]):
            text = tag.get_text(strip=True)
            match = re.match(r"Club\s*:\s*(.+?)(?:\s*\(\d+\))?$", text)
            if match:
                data["nom_structure"] = match.group(1).strip()
                break
    else:
        parent = club_tag.parent or club_tag
        text = parent.get_text(strip=True)
        match = re.search(r"Club\s*:\s*(.+?)(?:\s*\(\d+\))?$", text)
        if match:
            data["nom_structure"] = match.group(1).strip()

    # Region
    region = _get_field_after_label(soup, r"R[eé]gion")
    if region:
        data["region"] = region

    # Address: extract postal code and city
    addr = _get_field_after_label(soup, r"Adresse")
    if addr:
        addr_match = re.search(r"(\d{5})\s+([A-ZÀ-Üa-zà-ü][A-ZÀ-Üa-zà-ü\s'-]+)", addr)
        if addr_match:
            data["departement"] = addr_match.group(1)[:2]
            data["lieu"] = _clean_city(addr_match.group(2).strip())

    # If no address field found, try postal code in full text
    if "lieu" not in data:
        text = soup.get_text(" ", strip=True)
        addr_match = re.search(r"(\d{5})\s+([A-ZÀ-Ü][A-ZÀ-Ü\s'-]{2,30})", text)
        if addr_match:
            data["departement"] = addr_match.group(1)[:2]
            city = _clean_city(addr_match.group(2).strip())
            if len(city) > 2:
                data["lieu"] = city

    # Salary
    salaire = _get_field_after_label(soup, r"Salaire")
    if salaire:
        data["salaire"] = salaire[:100]

    # Period (as contract type info)
    periode = _get_field_after_label(soup, r"P[eé]riode")
    if periode:
        data["type_contrat"] = periode[:100]

    # Contact name
    contact = _get_field_after_label(soup, r"Contact")
    if contact:
        data["contact_nom"] = contact[:100]

    # Phone
    tel = _get_field_after_label(soup, r"Tel")
    if tel:
        data["contact_tel"] = re.sub(r"[^\d\s.+()-]", "", tel)[:30]

    # Email - find mailto link
    mailto = soup.find("a", href=re.compile(r"mailto:"))
    if mailto:
        email = mailto.get("href", "").replace("mailto:", "").strip()
        if "@" in email:
            data["contact_email"] = email

    # Fallback email from text
    if "contact_email" not in data:
        text = soup.get_text(" ", strip=True)
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_match:
            data["contact_email"] = email_match.group(0)

    # Description from "Annonce" section
    annonce = _get_field_after_label(soup, r"Annonce")
    if annonce:
        data["description"] = annonce[:1000]
    else:
        blockquote = soup.find("blockquote")
        if blockquote:
            data["description"] = blockquote.get_text(" ", strip=True)[:1000]

    return data


def scrape_all_offers(max_detail_pages=None):
    """Scrape all offers from FFVoile. Optionally limit detail page fetches."""
    init_db()
    conn = get_connection()

    print("Fetching listing page...")
    # Try multiple pages in case of pagination
    all_offers = []
    seen_ids = set()

    for page in range(1, 10):
        html = fetch_page(LIST_URL.format(page=page))
        if not html:
            break

        offers = parse_listing_page(html)
        new_offers = [o for o in offers if o["ffvoile_id"] not in seen_ids]

        if not new_offers:
            break

        for o in new_offers:
            seen_ids.add(o["ffvoile_id"])
        all_offers.extend(new_offers)
        print(f"  Page {page}: {len(new_offers)} new offers (total: {len(all_offers)})")

        if len(new_offers) < 10:
            break

    print(f"\nTotal offers from listing: {len(all_offers)}")

    # Fetch detail pages for enrichment
    detail_count = 0
    limit = max_detail_pages or len(all_offers)

    for i, offer in enumerate(all_offers[:limit]):
        print(f"  [{i+1}/{min(limit, len(all_offers))}] Fetching detail for: {offer['intitule'][:50]}...")
        detail_html = fetch_page(DETAIL_URL.format(id=offer["ffvoile_id"]))

        if detail_html:
            details = parse_detail_page(detail_html)
            offer.update({k: v for k, v in details.items() if v and not offer.get(k)})
            detail_count += 1

        time.sleep(0.5)  # Be polite

    print(f"\nEnriched {detail_count} offers with detail data")

    # Store in database
    print("\nStoring in database...")
    for offer in all_offers:
        # Create/update ecole from offer data
        ecole_id = None
        if offer.get("nom_structure"):
            ecole_id = upsert_ecole(
                conn,
                nom=offer["nom_structure"],
                email=offer.get("contact_email"),
                ville=offer.get("lieu"),
                departement=offer.get("departement"),
                source="ffvoile_offres",
            )

        upsert_offre(
            conn,
            ffvoile_id=offer["ffvoile_id"],
            intitule=offer["intitule"],
            nom_structure=offer.get("nom_structure"),
            lieu=offer.get("lieu"),
            departement=offer.get("departement"),
            type_contrat=offer.get("type_contrat"),
            date_publication=offer.get("date_publication"),
            url_offre=offer.get("url_offre"),
            region=offer.get("region"),
            salaire=offer.get("salaire"),
            contact_nom=offer.get("contact_nom"),
            contact_email=offer.get("contact_email"),
            contact_tel=offer.get("contact_tel"),
            description=offer.get("description"),
            ecole_id=ecole_id,
        )

    conn.commit()

    # Print summary
    ecole_count = conn.execute("SELECT COUNT(*) FROM ecoles").fetchone()[0]
    offre_count = conn.execute("SELECT COUNT(*) FROM offres").fetchone()[0]
    print(f"\nDatabase now contains: {ecole_count} écoles, {offre_count} offres")

    conn.close()
    return all_offers


def print_sample():
    """Print a sample of schools and offers from the database."""
    conn = get_connection()

    print("\n" + "=" * 80)
    print("SAMPLE: 20 ÉCOLES")
    print("=" * 80)
    rows = conn.execute("""
        SELECT e.id, e.nom, e.email, e.ville, e.departement, e.source,
               COUNT(o.id) as nb_offres
        FROM ecoles e
        LEFT JOIN offres o ON o.ecole_id = e.id
        GROUP BY e.id
        ORDER BY nb_offres DESC, e.nom
        LIMIT 20
    """).fetchall()

    print(f"{'ID':<4} {'Nom':<40} {'Ville':<25} {'Dept':<5} {'Email':<30} {'Offres':<6}")
    print("-" * 110)
    for r in rows:
        print(f"{r['id']:<4} {(r['nom'] or '')[:39]:<40} {(r['ville'] or '')[:24]:<25} "
              f"{(r['departement'] or ''):<5} {(r['email'] or '')[:29]:<30} {r['nb_offres']:<6}")

    print("\n" + "=" * 80)
    print("SAMPLE: 10 OFFRES (les plus récentes)")
    print("=" * 80)
    rows = conn.execute("""
        SELECT o.ffvoile_id, o.intitule, o.nom_structure, o.lieu, o.departement,
               o.region, o.date_publication, o.contact_email, e.nom as ecole_nom
        FROM offres o
        LEFT JOIN ecoles e ON o.ecole_id = e.id
        ORDER BY o.date_publication DESC
        LIMIT 10
    """).fetchall()

    for r in rows:
        print(f"\n  [{r['ffvoile_id']}] {r['intitule']}")
        print(f"    Structure: {r['nom_structure'] or '?'} | Lieu: {r['lieu'] or '?'} ({r['departement'] or '?'})")
        print(f"    Région: {r['region'] or '?'} | Publié: {r['date_publication'] or '?'}")
        print(f"    Contact: {r['contact_email'] or '?'}")
        print(f"    Lié à école: {'Oui (#' + str(r['ecole_nom']) + ')' if r['ecole_nom'] else 'Non'}")

    conn.close()


if __name__ == "__main__":
    scrape_all_offers(max_detail_pages=15)
    print_sample()
