#!/usr/bin/env python3
"""Seed sample map data for a user's account, to demo/verify the map feature.

Creates ~60 geocoded, scored properties clustered in three Humble/Atascocita
(77396/77346) neighborhoods, plus recent intent signal_events on about half of
them, so both map endpoints have data to serve:
  GET /api/map/cells       — geohash-6 choropleth aggregates
  GET /api/map/properties  — viewport pins (with the signals array)

Idempotent per address: reruns skip rows that already exist for the account
(ON CONFLICT on the (account_id, address, zip) uniqueness key).

Usage:
    DATABASE_URL=postgresql://... python scripts/seed_map_sample_data.py \
        --username pc_home_services_owner_test
"""
import argparse
import os
import random
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geohash2  # noqa: E402  (required by requirements.txt; used by the pipeline too)

CLUSTERS = [
    # (neighborhood name, center lat, center lng, zip, property count)
    ("Fall Creek", 29.9705, -95.1930, "77396", 25),
    ("Atascocita South", 29.9910, -95.1650, "77346", 20),
    ("Park Lakes", 29.9530, -95.2100, "77396", 15),
]
STREETS = ["Maple Bend Dr", "Cypress Trail Ln", "Redwood Shores Dr", "Wild Iris Way",
           "Auburn Terrace Ln", "Emerald Mist Ct", "Golden Cove Dr", "Sunrise Pines Dr"]
STATUSES = ["new", "new", "new", "contacted", "contacted", "quoted", "won", "lost"]
SIGNALS = ["storm_hail", "roof_permit", "pool_permit", "recent_sale", "home_improvement"]


def grade(score: float) -> str:
    return "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D"


def seed(conn, account_id: int, vertical: str) -> tuple[int, int]:
    n_props = n_signals = 0
    house_no = 1200
    with conn.cursor() as cur:
        for name, clat, clng, zipc, n in CLUSTERS:
            for _ in range(n):
                lat = clat + random.uniform(-0.006, 0.006)
                lng = clng + random.uniform(-0.006, 0.006)
                score = round(random.uniform(30, 98), 1)
                house_no += random.randint(3, 17)
                cur.execute(
                    """INSERT INTO properties
                           (account_id, address, zip, latitude, longitude, geohash,
                            lead_score, score_grade, status, vertical, estimated_value,
                            hcad_neighborhood_name, contact_name, year_built)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (account_id, address, zip) DO NOTHING
                       RETURNING id""",
                    (account_id, f"{house_no} {random.choice(STREETS)}", zipc,
                     lat, lng, geohash2.encode(lat, lng, precision=7),
                     score, grade(score), random.choice(STATUSES), vertical,
                     random.randint(220_000, 520_000), name,
                     f"Sample Owner {n_props + 1}", random.randint(1995, 2018)),
                )
                row = cur.fetchone()
                if not row:
                    continue
                n_props += 1
                # roughly half the properties get 1-2 recent intent signals
                if random.random() < 0.5:
                    for sig in random.sample(SIGNALS, k=random.randint(1, 2)):
                        cur.execute(
                            """INSERT INTO signal_events
                                   (property_id, account_id, signal_type, details, detected_at)
                               VALUES (%s,%s,%s,%s, NOW() - (%s * INTERVAL '1 day'))""",
                            (row[0], account_id, sig,
                             '{"source": "sample_seed"}', random.randint(1, 80)),
                        )
                        n_signals += 1
    return n_props, n_signals


def main():
    parser = argparse.ArgumentParser(description="Seed sample map data for a user's account")
    parser.add_argument("--username", required=True, help="Existing username whose account gets the data")
    parser.add_argument("--vertical", default="roofing", help="Vertical tag for the sample leads")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (reproducible data)")
    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        parser.error("DATABASE_URL environment variable is not set")

    random.seed(args.seed)
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT account_id FROM users WHERE username = %s", (args.username,))
            row = cur.fetchone()
        if not row:
            print(f"Error: user '{args.username}' not found", file=sys.stderr)
            sys.exit(1)
        n_props, n_signals = seed(conn, row[0], args.vertical)
        conn.commit()
        print(f"✓ account_id={row[0]}: inserted {n_props} properties, {n_signals} signal events")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
