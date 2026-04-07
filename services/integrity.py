"""Pipeline integrity checks for VoileCV.

Inspired by career-ops verify-pipeline.mjs, dedup-tracker.mjs,
normalize-statuses.mjs. Adapted for our SQLite-based pipeline.

Checks:
1. Duplicate candidatures (same user + same school)
2. Status normalization (canonical statuses only)
3. Orphaned candidatures (missing user or school)
4. Schools without email (can't send)
5. Offers without school link
6. Overall pipeline health
"""

from scraping.database import get_connection

CANONICAL_STATUSES = {"draft", "pending", "sent", "send_failed", "opened", "replied"}

STATUS_ALIASES = {
    "envoyé": "sent",
    "ouvert": "opened",
    "échoué": "send_failed",
    "echec": "send_failed",
    "brouillon": "draft",
    "en_attente": "pending",
    "reponse": "replied",
}


def verify_pipeline() -> dict:
    """Run all pipeline integrity checks.

    Returns: {
        "status": "clean" | "warnings" | "errors",
        "checks": [
            {"name": "...", "status": "ok" | "warn" | "error", "message": "...", "count": int}
        ],
        "summary": {"errors": int, "warnings": int, "ok": int}
    }
    """
    conn = get_connection()
    checks = []

    # 1. Duplicate candidatures
    dupes = conn.execute("""
        SELECT user_id, ecole_id, COUNT(*) as cnt
        FROM candidatures
        GROUP BY user_id, ecole_id
        HAVING cnt > 1
    """).fetchall()

    if dupes:
        checks.append({
            "name": "Doublons de candidatures",
            "status": "error",
            "message": f"{len(dupes)} doublon(s) détecté(s)",
            "count": len(dupes),
        })
    else:
        checks.append({
            "name": "Doublons de candidatures",
            "status": "ok",
            "message": "Aucun doublon",
            "count": 0,
        })

    # 2. Status normalization check
    bad_statuses = conn.execute("""
        SELECT id, status FROM candidatures
        WHERE status NOT IN ('draft', 'pending', 'sent', 'send_failed', 'opened', 'replied')
    """).fetchall()

    if bad_statuses:
        checks.append({
            "name": "Statuts non canoniques",
            "status": "warn",
            "message": f"{len(bad_statuses)} candidature(s) avec statut non standard",
            "count": len(bad_statuses),
        })
    else:
        checks.append({
            "name": "Statuts canoniques",
            "status": "ok",
            "message": "Tous les statuts sont valides",
            "count": 0,
        })

    # 3. Orphaned candidatures
    orphaned_users = conn.execute("""
        SELECT c.id FROM candidatures c
        LEFT JOIN users u ON c.user_id = u.id
        WHERE u.id IS NULL
    """).fetchall()

    orphaned_ecoles = conn.execute("""
        SELECT c.id FROM candidatures c
        LEFT JOIN ecoles e ON c.ecole_id = e.id
        WHERE e.id IS NULL
    """).fetchall()

    orphan_count = len(orphaned_users) + len(orphaned_ecoles)
    if orphan_count:
        checks.append({
            "name": "Candidatures orphelines",
            "status": "error",
            "message": f"{orphan_count} candidature(s) sans utilisateur ou école valide",
            "count": orphan_count,
        })
    else:
        checks.append({
            "name": "Candidatures orphelines",
            "status": "ok",
            "message": "Aucune candidature orpheline",
            "count": 0,
        })

    # 4. Schools without email
    no_email = conn.execute("""
        SELECT COUNT(*) FROM ecoles WHERE email IS NULL OR email = ''
    """).fetchone()[0]
    total_ecoles = conn.execute("SELECT COUNT(*) FROM ecoles").fetchone()[0]

    if no_email > 0:
        pct = round(no_email / total_ecoles * 100) if total_ecoles else 0
        checks.append({
            "name": "Écoles sans email",
            "status": "warn",
            "message": f"{no_email}/{total_ecoles} écoles sans email ({pct}%)",
            "count": no_email,
        })
    else:
        checks.append({
            "name": "Écoles sans email",
            "status": "ok",
            "message": "Toutes les écoles ont un email",
            "count": 0,
        })

    # 5. Offers without school link
    orphan_offres = conn.execute("""
        SELECT COUNT(*) FROM offres WHERE ecole_id IS NULL
    """).fetchone()[0]

    if orphan_offres:
        checks.append({
            "name": "Offres sans école liée",
            "status": "warn",
            "message": f"{orphan_offres} offre(s) non rattachée(s) à une école",
            "count": orphan_offres,
        })
    else:
        checks.append({
            "name": "Offres liées",
            "status": "ok",
            "message": "Toutes les offres sont liées à une école",
            "count": 0,
        })

    # 6. Pipeline stats
    stats = conn.execute("""
        SELECT status, COUNT(*) as cnt
        FROM candidatures
        GROUP BY status
    """).fetchall()

    pipeline_stats = {r["status"]: r["cnt"] for r in stats}
    total_cand = sum(pipeline_stats.values())

    checks.append({
        "name": "Pipeline global",
        "status": "ok",
        "message": f"{total_cand} candidatures au total",
        "count": total_cand,
        "breakdown": pipeline_stats,
    })

    conn.close()

    errors = sum(1 for c in checks if c["status"] == "error")
    warnings = sum(1 for c in checks if c["status"] == "warn")
    oks = sum(1 for c in checks if c["status"] == "ok")

    if errors > 0:
        overall = "errors"
    elif warnings > 0:
        overall = "warnings"
    else:
        overall = "clean"

    return {
        "status": overall,
        "checks": checks,
        "summary": {"errors": errors, "warnings": warnings, "ok": oks},
    }


def normalize_statuses() -> int:
    """Fix non-canonical statuses. Returns number of fixes applied."""
    conn = get_connection()
    fixed = 0

    bad = conn.execute("""
        SELECT id, status FROM candidatures
        WHERE status NOT IN ('draft', 'pending', 'sent', 'send_failed', 'opened', 'replied')
    """).fetchall()

    for row in bad:
        canonical = STATUS_ALIASES.get(row["status"].lower().strip())
        if canonical:
            conn.execute(
                "UPDATE candidatures SET status = ? WHERE id = ?",
                (canonical, row["id"])
            )
            fixed += 1

    conn.commit()
    conn.close()
    return fixed


def dedup_candidatures() -> int:
    """Remove duplicate candidatures (keep the most recent). Returns count removed."""
    conn = get_connection()

    dupes = conn.execute("""
        SELECT user_id, ecole_id, COUNT(*) as cnt
        FROM candidatures
        GROUP BY user_id, ecole_id
        HAVING cnt > 1
    """).fetchall()

    removed = 0
    for dupe in dupes:
        # Keep the one with the latest created_at or highest status
        rows = conn.execute("""
            SELECT id FROM candidatures
            WHERE user_id = ? AND ecole_id = ?
            ORDER BY
                CASE status
                    WHEN 'replied' THEN 6
                    WHEN 'opened' THEN 5
                    WHEN 'sent' THEN 4
                    WHEN 'pending' THEN 3
                    WHEN 'draft' THEN 2
                    WHEN 'send_failed' THEN 1
                    ELSE 0
                END DESC,
                created_at DESC
        """, (dupe["user_id"], dupe["ecole_id"])).fetchall()

        # Delete all but the first (best) one
        for row in rows[1:]:
            conn.execute("DELETE FROM candidatures WHERE id = ?", (row["id"],))
            removed += 1

    conn.commit()
    conn.close()
    return removed
