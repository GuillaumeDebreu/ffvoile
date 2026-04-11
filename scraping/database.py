"""SQLite database schema and helpers for VoileCV."""

import sqlite3
from pathlib import Path
from datetime import datetime

import os
_data_dir = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")
if _data_dir:
    DB_PATH = Path(_data_dir) / "voilecv.db"
else:
    DB_PATH = Path(__file__).parent.parent / "voilecv.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ecoles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            email TEXT,
            ville TEXT,
            departement TEXT,
            url_site TEXT,
            source TEXT NOT NULL,
            date_scrape TEXT NOT NULL,
            UNIQUE(nom, ville)
        );

        CREATE TABLE IF NOT EXISTS offres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ecole_id INTEGER REFERENCES ecoles(id),
            ffvoile_id INTEGER UNIQUE,
            intitule TEXT NOT NULL,
            nom_structure TEXT,
            lieu TEXT,
            departement TEXT,
            type_contrat TEXT,
            date_publication TEXT,
            url_offre TEXT,
            region TEXT,
            salaire TEXT,
            contact_nom TEXT,
            contact_email TEXT,
            contact_tel TEXT,
            description TEXT,
            date_scrape TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ecoles_nom ON ecoles(nom);
        CREATE INDEX IF NOT EXISTS idx_ecoles_departement ON ecoles(departement);
        CREATE INDEX IF NOT EXISTS idx_offres_ecole_id ON offres(ecole_id);
        CREATE INDEX IF NOT EXISTS idx_offres_ffvoile_id ON offres(ffvoile_id);
    """)
    conn.commit()
    conn.close()


def upsert_ecole(conn, nom, email=None, ville=None, departement=None,
                 url_site=None, source="ffvoile_offres"):
    now = datetime.now().isoformat()
    try:
        conn.execute("""
            INSERT INTO ecoles (nom, email, ville, departement, url_site, source, date_scrape)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nom, ville) DO UPDATE SET
                email = COALESCE(excluded.email, ecoles.email),
                departement = COALESCE(excluded.departement, ecoles.departement),
                url_site = COALESCE(excluded.url_site, ecoles.url_site),
                date_scrape = excluded.date_scrape
        """, (nom, email, ville, departement, url_site, source, now))
        return conn.execute(
            "SELECT id FROM ecoles WHERE nom = ? AND ville IS ?", (nom, ville)
        ).fetchone()["id"]
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT id FROM ecoles WHERE nom = ?", (nom,)
        ).fetchone()
        return row["id"] if row else None


def upsert_offre(conn, ffvoile_id, intitule, nom_structure=None, lieu=None,
                 departement=None, type_contrat=None, date_publication=None,
                 url_offre=None, region=None, salaire=None,
                 contact_nom=None, contact_email=None, contact_tel=None,
                 description=None, ecole_id=None):
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO offres (ffvoile_id, ecole_id, intitule, nom_structure, lieu,
            departement, type_contrat, date_publication, url_offre, region,
            salaire, contact_nom, contact_email, contact_tel, description, date_scrape)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ffvoile_id) DO UPDATE SET
            intitule = excluded.intitule,
            nom_structure = excluded.nom_structure,
            lieu = excluded.lieu,
            departement = excluded.departement,
            type_contrat = excluded.type_contrat,
            date_publication = excluded.date_publication,
            url_offre = excluded.url_offre,
            region = excluded.region,
            salaire = excluded.salaire,
            contact_nom = excluded.contact_nom,
            contact_email = excluded.contact_email,
            contact_tel = excluded.contact_tel,
            description = excluded.description,
            ecole_id = COALESCE(excluded.ecole_id, offres.ecole_id),
            date_scrape = excluded.date_scrape
    """, (ffvoile_id, ecole_id, intitule, nom_structure, lieu, departement,
          type_contrat, date_publication, url_offre, region, salaire,
          contact_nom, contact_email, contact_tel, description, now))
