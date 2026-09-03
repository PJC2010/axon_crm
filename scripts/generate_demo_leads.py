#!/usr/bin/env python3
"""Generate a synthetic lead CSV for an Axon product demo.

Emits the exact generic headers api/import_logic.py auto-detects, so the file
maps 100% on the import preview with no manual column matching:

    name, phone, email, owner, address, city, state, zip,
    estimated_value, vertical, status

Every address sits in a real Harris County ZIP with a street name that belongs
to that part of the county, so the map, ZIP filters and territory views look
like a real book of business. Contact details are deliberately fake: phone
numbers use the reserved 555-01xx fictional block and emails use RFC 2606
reserved domains, so nothing in a demo can reach a real person.

The importer writes only these eleven columns, so a lead created from this file
has no year built, floor area, sale history or storm exposure and every account
grades C/D. Run scripts/enrich_demo_leads.py after importing to fill those in
and get a real A-D spread.

Usage:
    python scripts/generate_demo_leads.py --rows 250 --vertical roofing \
        --out demo_leads.csv

    # spread across every trade instead of one
    python scripts/generate_demo_leads.py --mixed-verticals

    # widen past the default 12-ZIP territory
    python scripts/generate_demo_leads.py --territory wide --rows 600
"""
from __future__ import annotations

import argparse
import csv
import random
import sys

# Headers the importer recognizes with zero manual mapping
# (api/import_logic.py::GENERIC_ALIASES, matching the /imports/contacts/template).
HEADERS = ["name", "phone", "email", "owner", "address", "city", "state", "zip",
           "estimated_value", "vertical", "status"]

# config.py::VERTICAL_WEIGHTS — the only keys the scorer has weights for.
VERTICALS = ["roofing", "hvac", "solar", "epoxy_flooring", "pool_maintenance",
             "fencing", "landscaping", "pressure_washing"]

# The default board columns (db/migrations/0011_custom_stages.sql), weighted like
# a real pipeline (fat top of funnel).
#
# Deliberately NOT the whole of api/models.py::ALLOWED_STATUSES: 'converted' is
# an accepted status with no default pipeline_stages row, so a lead carrying it
# imports cleanly and then belongs to no Kanban column at all — invisible on the
# board it was generated for. An account that has added its own stages can use
# those keys here instead; the importer validates against both sets.
STATUS_WEIGHTS = [
    ("new", 42), ("contacted", 20), ("qualified", 13), ("quote_sent", 11),
    ("won", 6), ("lost", 5), ("not_interested", 3),
]

# ZIP -> (city, value tier, street names actually found in that part of the county)
ZIPS: dict[str, tuple[str, str, list[str]]] = {
    # --- Northeast: Humble / Atascocita / Kingwood ---
    "77396": ("Humble", "mid", ["Maple Bend Dr", "Sunset Ridge Ln", "Mesa Springs Dr",
                                "Wild Iris Way", "Golden Cove Dr", "Emerald Mist Ct"]),
    "77346": ("Humble", "mid", ["Timber Forest Dr", "Pinehurst Trail Dr", "Atascocita Shores Dr",
                                "Silver Sand Ln", "Bristol Bend Ln", "Canyon Falls Dr"]),
    "77338": ("Humble", "low", ["Will Clayton Pkwy", "Deerbrook Glen Dr", "Rankin Rd",
                                "Treaschwig Rd", "Northshire Dr"]),
    "77339": ("Kingwood", "upper", ["Kingwood Dr", "Woodland Hills Dr", "Northpark Dr",
                                    "Hidden Pines Dr", "Forest Garden Dr"]),
    "77345": ("Kingwood", "upper", ["Mills Branch Dr", "W Lake Houston Pkwy",
                                    "Kings Mill Ln", "Deer Ridge Estates Blvd"]),
    # --- North: Spring / Tomball ---
    "77373": ("Spring", "low", ["Spring Stuebner Rd", "Aldine Westfield Rd",
                                "Holzwarth Rd", "Rayford Rd"]),
    "77379": ("Spring", "mid", ["Louetta Rd", "Champion Forest Dr", "Gosling Rd",
                                "Theiss Mail Route Rd", "Coral Gables Dr"]),
    "77388": ("Spring", "mid", ["Cypresswood Dr", "Kuykendahl Rd", "Ella Blvd",
                                "Brooklet Creek Dr"]),
    "77389": ("Spring", "upper", ["Gosling Rd", "Northcrest Dr", "Auburn Bend Dr",
                                  "Springwood Lake Dr"]),
    "77375": ("Tomball", "mid", ["Hufsmith Kohrville Rd", "Zion Rd", "Willow Creek Dr",
                                 "Alice Rd"]),
    "77377": ("Tomball", "mid", ["Boudreaux Rd", "Rocky Creek Dr", "Mahaffey Rd",
                                 "Lakewood Crossing Dr"]),
    "77070": ("Houston", "mid", ["Cypresswood Dr", "Perry Rd", "Champion Villa Dr",
                                 "Bammel North Houston Rd"]),
    "77090": ("Houston", "low", ["Cypress Station Dr", "Fallbrook Dr", "Bammel Rd"]),
    # --- Northwest: Cypress / Copperfield / Jersey Village ---
    "77433": ("Cypress", "upper", ["Bridgeland Creek Pkwy", "Cypress Rosehill Rd",
                                   "Fairway Crossing Dr", "Shadow Bay Dr", "Tuckerton Rd"]),
    "77095": ("Houston", "mid", ["Queenston Blvd", "Longenbaugh Dr", "West Rd",
                                 "Copper Village Dr", "Stone Mill Dr"]),
    "77065": ("Houston", "mid", ["Huffmeister Rd", "Mills Rd", "Yorktown Colony Dr"]),
    "77064": ("Houston", "mid", ["Steepletop Dr", "Windfern Forest Dr", "Jones Rd"]),
    "77040": ("Houston", "low", ["Fairbanks North Houston Rd", "Windfern Rd", "Senate Ave"]),
    "77447": ("Hockley", "mid", ["Becker Rd", "Warren Ranch Rd", "Grand Pine Dr"]),
    # --- West: Katy / Energy Corridor ---
    "77449": ("Katy", "low", ["Franz Rd", "Morton Ranch Rd", "Westgreen Blvd",
                              "Silver Green Dr", "Fern Bluff Ln"]),
    "77450": ("Katy", "upper", ["Kingsland Blvd", "Westheimer Pkwy", "Fry Rd",
                                "Nottingham Country Dr", "Cimarron Pkwy"]),
    "77493": ("Katy", "mid", ["Katy Hockley Cut Off Rd", "Pitts Rd", "Porter Rd",
                              "Elyson Falls Dr"]),
    "77084": ("Houston", "low", ["Barker Cypress Rd", "Mason Rd", "Clay Rd",
                                 "Greenhouse Rd", "Saums Rd"]),
    "77094": ("Houston", "upper", ["Park Row Dr", "Peek Rd", "Green Trails Dr"]),
    "77079": ("Houston", "upper", ["Kimberley Ln", "Wilcrest Dr", "Memorial Dr",
                                   "Attingham Dr", "Saint Marys Ln"]),
    "77077": ("Houston", "mid", ["Eldridge Pkwy", "Briar Forest Dr", "Kirkwood Rd",
                                 "Ashford Point Dr"]),
    # --- Inner loop / close-in ---
    "77005": ("Houston", "high", ["Rice Blvd", "Tangley St", "Wakeforest Ave",
                                  "Sunset Blvd", "Werlein Ave"]),
    "77401": ("Bellaire", "high", ["Holly St", "Maple St", "Cedar St", "Locust St",
                                   "Mimosa Dr"]),
    "77024": ("Houston", "high", ["Bunker Hill Rd", "Beinhorn Rd", "Piney Point Rd",
                                  "Attingham Dr", "Timberwilde Ln"]),
    "77027": ("Houston", "high", ["Fountain View Dr", "Weslayan St", "Post Oak Ln",
                                  "Chevy Chase Dr"]),
    "77056": ("Houston", "high", ["San Felipe St", "Woodway Dr", "Augusta Dr", "Sage Rd"]),
    "77098": ("Houston", "high", ["Greenbriar Dr", "Norfolk St", "Colquitt St",
                                  "Vassar St"]),
    "77008": ("Houston", "upper", ["Yale St", "Nicholson St", "Arlington St",
                                   "Rutland St", "Ashland St"]),
    "77007": ("Houston", "upper", ["Blossom St", "Feagan St", "Detering St",
                                   "Center St", "Bonner St"]),
    "77009": ("Houston", "mid", ["Norhill Blvd", "Pecore St", "Beauchamp St",
                                 "Studewood St"]),
    "77096": ("Houston", "mid", ["Rutherglenn Dr", "Braesvalley Dr", "Loch Lomond Dr",
                                 "Wigton Dr"]),
    "77035": ("Houston", "mid", ["Braesheather Dr", "Willowbend Blvd", "Fondren Rd",
                                 "Grape St"]),
    "77025": ("Houston", "upper", ["Blue Bonnet Blvd", "Underwood St", "Cason St",
                                   "Bushy Tail Dr"]),
    "77055": ("Houston", "low", ["Long Point Rd", "Wirt Rd", "Bingle Rd", "Wickersham Ln"]),
    "77080": ("Houston", "low", ["Blalock Rd", "Pech Rd", "Neuens Rd", "Wedgewood Dr"]),
    "77043": ("Houston", "mid", ["Campbell Rd", "Kempwood Dr", "Hammerly Blvd",
                                 "Shadyvilla Ln"]),
    "77082": ("Houston", "low", ["Synott Rd", "Ashford Grove Dr", "Rocky Knoll Dr"]),
    "77099": ("Houston", "low", ["Dairy Ashford Rd", "Turtlewood Dr", "Chasewood Dr"]),
    # --- Southeast: Clear Lake / Pasadena / Bay Area ---
    "77058": ("Houston", "mid", ["Middlebrook Dr", "El Camino Real", "Pineloch Dr"]),
    "77059": ("Houston", "upper", ["Space Center Blvd", "Diana Ln", "Falling Star Dr",
                                   "Blue Fox Dr"]),
    "77062": ("Houston", "mid", ["Camino South", "Reseda Dr", "Sea Lark Rd",
                                 "Fairwind Rd"]),
    "77598": ("Webster", "low", ["Bay Area Blvd", "Magnolia Ave", "Pinelakes Blvd"]),
    "77546": ("Friendswood", "upper", ["Sunset Dr", "Whispering Pines Ave", "Skyview Dr"]),
    "77089": ("Houston", "low", ["Scarsdale Blvd", "Kirkfair Dr", "Hughes Rd",
                                 "Sagemeadow Ln"]),
    "77034": ("Houston", "low", ["Beamer Rd", "Blackhawk Blvd", "Sagedowne Ln"]),
    "77504": ("Pasadena", "low", ["Fairmont Pkwy", "Burke Rd", "Bell Ave", "Vista Rd"]),
    "77505": ("Pasadena", "mid", ["Spencer Hwy", "Center St", "Kirby Blvd"]),
    "77571": ("La Porte", "low", ["Underwood Rd", "W Main St", "Bay Colony Dr"]),
    "77536": ("Deer Park", "mid", ["San Augustine Ave", "Center St", "Luella Ave"]),
    "77521": ("Baytown", "low", ["Rollingbrook Dr", "Baker Rd", "Barkuloo Rd"]),
    "77530": ("Channelview", "low", ["Sheldon Rd", "Woodforest Blvd", "Dell Dale St"]),
    "77532": ("Crosby", "mid", ["Kennings Rd", "Foley Rd", "Krenek Rd"]),
}

# A real service business works a territory, not a whole county.
TERRITORY_NORTHEAST = ["77396", "77346", "77338", "77339", "77345", "77373",
                       "77379", "77388", "77389", "77375", "77377", "77070"]
TERRITORY_WEST = ["77449", "77450", "77493", "77084", "77094", "77079", "77077",
                  "77095", "77433", "77065", "77064", "77447"]
TERRITORY_INNER = ["77005", "77401", "77024", "77027", "77056", "77098", "77008",
                   "77007", "77009", "77096", "77035", "77025"]
TERRITORIES = {
    "northeast": TERRITORY_NORTHEAST,
    "west": TERRITORY_WEST,
    "inner": TERRITORY_INNER,
    "wide": sorted(ZIPS),
}

# Assessed-value bands by tier (low, high) — roughly what HCAD carries for these
# parts of the county, so a demo's totals and grade spread stay believable.
VALUE_BANDS = {
    "low":   (145_000, 290_000),
    "mid":   (235_000, 470_000),
    "upper": (360_000, 780_000),
    "high":  (620_000, 1_850_000),
}

FIRST_NAMES = [
    "Maria", "Jose", "Carlos", "Ana", "Luis", "Rosa", "Miguel", "Elena", "Javier", "Sofia",
    "James", "Robert", "Linda", "Susan", "Michael", "Karen", "David", "Nancy", "Brian", "Amy",
    "Marcus", "Andre", "Jasmine", "Tyrone", "Kendra", "Darnell", "Latoya", "Terrell",
    "Nguyen", "Thanh", "Linh", "Minh", "Hoa", "Duc", "Priya", "Rahul", "Anjali", "Vikram",
    "Chris", "Megan", "Jonathan", "Rachel", "Derek", "Holly", "Travis", "Courtney",
]
LAST_NAMES = [
    "Garcia", "Martinez", "Rodriguez", "Hernandez", "Lopez", "Gonzalez", "Perez", "Ramirez",
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson", "Moore",
    "Washington", "Jefferson", "Coleman", "Baker", "Freeman", "Dixon",
    "Nguyen", "Tran", "Pham", "Le", "Vo", "Patel", "Shah", "Desai", "Chen", "Kim",
    "Kowalski", "Novak", "Fitzgerald", "Odom", "Whitfield", "Barrera", "Sandoval", "Tovar",
]
# Houston-area codes; the 555-01xx block is reserved for fiction (NANP / RFC-style).
AREA_CODES = ["713", "281", "832", "346"]
# RFC 2606 reserved — can never route to a real person.
EMAIL_DOMAINS = ["example.com", "example.net", "example.org"]

# Absentee / entity owners: ~1 in 8 leads, where owner_name != contact_name.
ENTITY_SUFFIXES = ["FAMILY TRUST", "PROPERTIES LLC", "HOLDINGS LP", "REVOCABLE TRUST"]


def weighted_choice(rng: random.Random, pairs: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in pairs)
    roll = rng.uniform(0, total)
    upto = 0.0
    for value, weight in pairs:
        upto += weight
        if roll <= upto:
            return value
    return pairs[-1][0]


def make_value(rng: random.Random, tier: str) -> int:
    lo, hi = VALUE_BANDS[tier]
    # Skew toward the low end of the band — assessed values are right-tailed.
    raw = lo + (hi - lo) * (rng.random() ** 1.6)
    return int(round(raw, -3))


def make_row(rng: random.Random, zip_code: str, vertical: str,
             email_domain: str | None) -> dict:
    city, tier, streets = ZIPS[zip_code]
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    contact_name = f"{first} {last}"

    # HCAD writes owner names LAST-FIRST; mirror that so the demo matches what
    # the county-seeded rows next to it look like (pipeline/owner.py).
    if rng.random() < 0.12:
        owner_name = f"{last.upper()} {rng.choice(ENTITY_SUFFIXES)}"
    else:
        owner_name = f"{last.upper()} {first.upper()}"

    house_no = rng.choice([rng.randint(102, 998), rng.randint(1002, 9998),
                           rng.randint(10002, 24998)])
    address = f"{house_no} {rng.choice(streets)}"

    domain = email_domain or rng.choice(EMAIL_DOMAINS)
    email = f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@{domain}"
    phone = f"({rng.choice(AREA_CODES)}) 555-{rng.randint(100, 199):04d}"

    return {
        "name": contact_name,
        "phone": phone,
        "email": email,
        "owner": owner_name,
        "address": address,
        "city": city,
        "state": "TX",
        "zip": zip_code,
        "estimated_value": f"{make_value(rng, tier):,}",
        "vertical": vertical,
        "status": weighted_choice(rng, STATUS_WEIGHTS),
    }


def generate(rows: int, zips: list[str], vertical: str | None, mixed: bool,
             seed: int, email_domain: str | None) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()   # (address, zip) — the property uniqueness key
    attempts = 0
    while len(out) < rows and attempts < rows * 40:
        attempts += 1
        zip_code = rng.choice(zips)
        v = rng.choice(VERTICALS) if mixed else (vertical or "roofing")
        row = make_row(rng, zip_code, v, email_domain)
        key = (row["address"].upper(), row["zip"])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rows", type=int, default=250, help="how many leads (default 250)")
    p.add_argument("--out", default="demo_leads.csv", help="output CSV path")
    p.add_argument("--vertical", default="roofing", choices=VERTICALS,
                   help="single trade for the whole file (default roofing)")
    p.add_argument("--mixed-verticals", action="store_true",
                   help="spread rows across every vertical instead of one")
    p.add_argument("--territory", default="northeast",
                   choices=sorted(TERRITORIES), help="which Harris County ZIP set to use")
    p.add_argument("--zips", help="comma-separated ZIPs, overriding --territory")
    p.add_argument("--email-domain",
                   help="email domain to use (default: rotate RFC 2606 example.* domains)")
    p.add_argument("--seed", type=int, default=20260903, help="RNG seed (reproducible)")
    args = p.parse_args()

    if args.zips:
        zips = [z.strip() for z in args.zips.split(",") if z.strip()]
        unknown = [z for z in zips if z not in ZIPS]
        if unknown:
            print(f"Unknown ZIP(s) — not in the Harris County table: {', '.join(unknown)}",
                  file=sys.stderr)
            return 1
    else:
        zips = TERRITORIES[args.territory]

    rows = generate(args.rows, zips, args.vertical, args.mixed_verticals,
                    args.seed, args.email_domain)

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)

    by_zip: dict[str, int] = {}
    for r in rows:
        by_zip[r["zip"]] = by_zip.get(r["zip"], 0) + 1
    print(f"Wrote {len(rows)} leads to {args.out}")
    print("ZIPs: " + ", ".join(f"{z}×{n}" for z, n in sorted(by_zip.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
