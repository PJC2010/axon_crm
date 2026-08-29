"""
Visualize the data + enrichment pipeline for a ZIP.

Pulls a handful of properties for a ZIP from the database and renders a step-by-step
report showing what each enrichment stage contributed to each home. Inspects current
DB data only — it makes no API calls and incurs no cost.

The pipeline (see run_pipeline.py) runs 8 stages, each of which stamps a provenance
key into the `enrichment_flags` JSONB column and fills a known set of columns. This
tool reconstructs that flow per property from the flags + each step's owned columns.

Attribution is best-effort: later steps only fill columns left NULL by earlier ones
and flags are merged, so a filled value is attributed to the *earliest* step that
owns it and whose flag is present.

Usage:
    python tools/visualize_pipeline.py --zip 77044 --limit 5         # -> report_77044.html
    python tools/visualize_pipeline.py --zip 77044 --format md       # markdown instead
    python tools/visualize_pipeline.py --zip 77044 --out report.html # custom path
    python tools/visualize_pipeline.py --demo                        # no DB; sample data
"""
import argparse
import html
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure repo root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DEFAULT_WEIGHTS, VERTICAL_WEIGHTS
from pipeline import regional
from pipeline.profiles import resolve_profile
from pipeline.scoring import describe_vertical, explain_score, score_property

# Columns whose fill rate is worth tracking. Mirrors pipeline.coverage.TRACKED_FIELDS;
# used as a fallback when that module (which imports psycopg2) can't be loaded, e.g. in
# --demo mode on a machine without the DB driver installed.
_TRACKED_FIELDS_FALLBACK = [
    "latitude", "longitude", "year_built", "square_footage", "garage_spaces",
    "garage_type", "lot_size", "property_type", "estimated_value",
    "estimated_equity", "last_sale_date", "last_sale_price", "owner_name",
    "owner_occupied", "ownership_years", "zip_median_income", "permit_count_24mo",
    "has_pool", "has_cracked_slab", "contact_name", "contact_phone",
    "contact_email", "lead_score",
]


def coverage(rows: list[dict]) -> dict:
    """Per-field fill rates. Reuses pipeline.coverage when importable; otherwise
    computes the same thing inline (keeps --demo working without psycopg2)."""
    try:
        from pipeline.coverage import TRACKED_FIELDS, compute_fill_rates
        return compute_fill_rates(rows, TRACKED_FIELDS)
    except ImportError:
        total = len(rows)
        return {
            f: {
                "filled": (n := sum(1 for r in rows if r.get(f) is not None)),
                "total": total,
                "pct": round(100 * n / total, 1) if total else 0.0,
            }
            for f in _TRACKED_FIELDS_FALLBACK
        }


# ── Pipeline step definitions ─────────────────────────────────────────────────
# Ordered to match run_pipeline.py. `flag_keys` are the enrichment_flags keys a step
# stamps; `source` is a human label; `fields` are the property columns it owns.
STEP_SPEC = [
    {
        "key": "seed", "num": "1", "label": "Seed",
        "flag_keys": ["seed"], "source": "RentCast / CSV",
        "fields": ["address", "city", "state", "zip", "property_type",
                   "year_built", "square_footage", "garage_spaces", "garage_type"],
    },
    {
        "key": "census", "num": "2", "label": "Census",
        "flag_keys": ["census"], "source": "US Census ACS5",
        "fields": ["zip_median_income"],
    },
    {
        "key": "geocode", "num": "3", "label": "Geocode",
        "flag_keys": ["geocode"], "source": "Google Maps",
        "fields": ["latitude", "longitude", "geohash"],
    },
    {
        "key": "hcad", "num": "4", "label": "HCAD (free)",
        "flag_keys": ["hcad"], "source": "Harris CAD assessor",
        "fields": ["year_built", "square_footage", "lot_size", "estimated_value",
                   "last_sale_date", "owner_name", "owner_occupied", "ownership_years",
                   "has_pool", "has_cracked_slab", "garage_spaces"],
    },
    {
        "key": "property", "num": "5", "label": "Property detail",
        "flag_keys": ["property"], "source": "RentCast",
        "fields": ["year_built", "square_footage", "lot_size", "estimated_value",
                   "estimated_equity", "last_sale_date", "last_sale_price",
                   "owner_name", "owner_occupied", "ownership_years",
                   "garage_spaces", "garage_type"],
    },
    {
        "key": "permits", "num": "6", "label": "Permits",
        "flag_keys": ["permits"], "source": "Harris CAD permits",
        "fields": ["permit_count_24mo"],
    },
    {
        "key": "scored", "num": "7", "label": "Score",
        "flag_keys": ["scored"], "source": "scoring engine",
        "fields": ["lead_score", "score_grade", "vertical", "score_updated_at"],
    },
    {
        "key": "contact", "num": "8", "label": "Contact (skip-trace)",
        "flag_keys": ["contact"], "source": "skip-trace provider",
        "fields": ["contact_name", "contact_phone", "contact_email"],
    },
]

GRADE_COLORS = {"A": "#16a34a", "B": "#2563eb", "C": "#d97706", "D": "#dc2626"}


# ── Data access ────────────────────────────────────────────────────────────────

def fetch_properties(zip_code: str, limit: int) -> list[dict]:
    """Pull up to `limit` properties for a ZIP, best leads first."""
    import psycopg2.extras

    from pipeline.db import get_conn

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM properties WHERE zip = %s "
                "ORDER BY lead_score DESC NULLS LAST, id LIMIT %s",
                (zip_code, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── Step trace reconstruction ──────────────────────────────────────────────────

def step_ran(step: dict, flags: dict) -> tuple[bool, str | None]:
    """Did this step run? Returns (ran, source_value) from enrichment_flags."""
    for fk in step["flag_keys"]:
        if fk in (flags or {}):
            return True, flags[fk]
    return False, None


def attributed_step_key(field: str, flags: dict) -> str | None:
    """Earliest step (by STEP_SPEC order) that owns `field` and whose flag is present."""
    for step in STEP_SPEC:
        if field in step["fields"] and step_ran(step, flags)[0]:
            return step["key"]
    return None


def build_trace(row: dict) -> list[dict]:
    """Build the ordered per-step trace for one property row."""
    flags = row.get("enrichment_flags") or {}
    trace = []
    for step in STEP_SPEC:
        ran, source = step_ran(step, flags)
        fields = []
        for f in step["fields"]:
            val = row.get(f)
            fields.append({
                "name": f,
                "value": val,
                "filled": val is not None,
                "attributed": attributed_step_key(f, flags) == step["key"] and val is not None,
            })
        trace.append({**step, "ran": ran, "source": source, "field_rows": fields})
    return trace


def score_breakdown(row: dict, vertical_override: str | None) -> dict:
    """Per-factor scoring breakdown for the Score step (reuses production math).

    Resolved through the profile registry so the breakdown matches the market
    the row actually scores in — a Houston row explained against the national
    weights would reconcile with nothing production ever wrote.
    """
    vertical = vertical_override or row.get("vertical")
    profile = resolve_profile(
        vertical, regional.resolve_region(row.get("zip"), row.get("state")))
    explained = explain_score(row, profile.weights, profile=profile)
    explained["profile"] = describe_vertical(vertical, profile)
    explained["profile"]["region_label"] = profile.region_label
    return explained


# ── Value formatting ───────────────────────────────────────────────────────────

_CURRENCY = {"estimated_value", "estimated_equity", "last_sale_price", "zip_median_income"}


def fmt_value(field: str, val) -> str:
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "yes" if val else "no"
    if field in _CURRENCY and isinstance(val, (int, float)):
        return f"${val:,.0f}"
    if isinstance(val, (date, datetime)):
        return str(val)[:10]
    if field == "lead_score" and isinstance(val, (int, float)):
        return f"{val:.1f}"
    return str(val)


# ── HTML rendering ─────────────────────────────────────────────────────────────

CSS = """
:root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
body { margin: 0; background: #f4f5f7; color: #1f2933; }
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
.sub { color: #6b7280; margin: 0 0 24px; font-size: 14px; }
.note { background: #eef2ff; border-left: 3px solid #6366f1; padding: 10px 14px;
        border-radius: 6px; font-size: 13px; color: #3730a3; margin: 0 0 28px; }
.card { background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08);
        padding: 22px 24px; margin: 0 0 24px; }
.card h2 { font-size: 18px; margin: 0 0 2px; }
.card .addr-sub { color: #6b7280; font-size: 13px; margin: 0 0 18px; }
.badge { display: inline-block; color: #fff; font-weight: 700; border-radius: 999px;
         padding: 3px 12px; font-size: 13px; vertical-align: middle; margin-left: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 5px 10px; border-bottom: 1px solid #eef0f2; }
th { color: #6b7280; font-weight: 600; }
.cov td.pct { font-variant-numeric: tabular-nums; }
.step { display: flex; gap: 14px; padding: 14px 0; border-top: 1px solid #f0f1f3; }
.step:first-child { border-top: none; }
.step .num { flex: 0 0 30px; height: 30px; border-radius: 50%; display: flex;
             align-items: center; justify-content: center; font-weight: 700;
             font-size: 13px; color: #fff; background: #9ca3af; }
.step.ran .num { background: #4f46e5; }
.step .body { flex: 1; min-width: 0; }
.step .title { font-weight: 600; font-size: 14px; }
.pill { font-size: 11px; padding: 2px 8px; border-radius: 999px; margin-left: 8px; }
.pill.ran { background: #dcfce7; color: #166534; }
.pill.skip { background: #f3f4f6; color: #6b7280; }
.fields { margin-top: 8px; }
.fields td:first-child { color: #6b7280; width: 200px; }
.dot { color: #4f46e5; font-weight: 700; }   /* attributed to this step */
.dim td { color: #b0b6bd; }
.bar { display: inline-block; height: 9px; border-radius: 3px; background: #4f46e5;
       vertical-align: middle; }
.bartrack { display: inline-block; width: 120px; height: 9px; border-radius: 3px;
            background: #eef0f2; vertical-align: middle; margin-right: 8px; }
.factor td { font-variant-numeric: tabular-nums; }
"""


def _grade_badge(grade: str | None, score) -> str:
    if not grade:
        return ""
    color = GRADE_COLORS.get(grade, "#6b7280")
    s = f" {score:.1f}" if isinstance(score, (int, float)) else ""
    return f'<span class="badge" style="background:{color}">{html.escape(grade)}{s}</span>'


def _coverage_html(rates: dict, total: int) -> str:
    rows = ""
    for field, r in sorted(rates.items(), key=lambda kv: kv[1]["pct"]):
        rows += (f'<tr><td>{html.escape(field)}</td>'
                 f'<td class="pct">{r["filled"]}/{r["total"]}</td>'
                 f'<td class="pct">{r["pct"]:.0f}%</td></tr>')
    return (f'<div class="card cov"><h2>Coverage across {total} properties</h2>'
            f'<p class="addr-sub">Fill rate per enrichment-owned column (lowest first).</p>'
            f'<table><tr><th>field</th><th>filled</th><th>%</th></tr>{rows}</table></div>')


def _factor_html(breakdown: dict) -> str:
    prof = breakdown["profile"]
    vlabel = (prof.get("vertical") or "default") + (" (default weights)" if prof["is_default"] else "")
    if prof.get("region_label") and prof["region_label"] != "national":
        vlabel += f" — {prof['region_label']}"
    rows = ""
    for f in breakdown["factors"]:
        w = int(round(f["signal"] * 120))
        rows += (
            f'<tr class="factor"><td>{html.escape(f["label"])}</td>'
            f'<td><span class="bartrack"><span class="bar" style="width:{w}px"></span></span>'
            f'{f["signal"]:.2f}</td>'
            f'<td>{f["weight"]:.0%}</td>'
            f'<td>+{f["contribution"]:.1f}</td></tr>'
        )
    return (
        f'<div class="addr-sub" style="margin:8px 0 4px">Scoring profile: '
        f'<b>{html.escape(vlabel)}</b> &middot; total <b>{breakdown["score"]:.1f}</b> '
        f'(grade {html.escape(breakdown["grade"])})</div>'
        f'<table class="fields"><tr><th>factor</th><th>signal</th>'
        f'<th>weight</th><th>points</th></tr>{rows}</table>'
    )


def _step_html(step: dict, breakdown: dict | None) -> str:
    pill = ('<span class="pill ran">ran &middot; ' + html.escape(str(step["source"])) + '</span>'
            if step["ran"] else '<span class="pill skip">no data</span>')
    cls = "step ran" if step["ran"] else "step"

    if step["key"] == "scored" and step["ran"] and breakdown:
        body_extra = _factor_html(breakdown)
    else:
        frows = ""
        for fr in step["field_rows"]:
            dot = '<span class="dot">●</span> ' if fr["attributed"] else ""
            rowcls = "" if fr["filled"] else ' class="dim"'
            frows += (f'<tr{rowcls}><td>{dot}{html.escape(fr["name"])}</td>'
                      f'<td>{html.escape(fmt_value(fr["name"], fr["value"]))}</td></tr>')
        body_extra = f'<table class="fields">{frows}</table>'

    return (
        f'<div class="{cls}"><div class="num">{step["num"]}</div>'
        f'<div class="body"><span class="title">{html.escape(step["label"])}</span>{pill}'
        f'{body_extra}</div></div>'
    )


def render_html(zip_code: str, rows: list[dict], vertical_override: str | None) -> str:
    rates = coverage(rows)
    cards = [_coverage_html(rates, len(rows))]

    for row in rows:
        trace = build_trace(row)
        breakdown = score_breakdown(row, vertical_override)
        addr = html.escape(row.get("address") or "(unknown address)")
        loc = ", ".join(p for p in [row.get("city"), row.get("state"), row.get("zip")] if p)
        badge = _grade_badge(row.get("score_grade"), row.get("lead_score"))
        label = row.get("_label")
        sub = (html.escape(label) + " &middot; " if label else "") + html.escape(loc)
        steps = "".join(_step_html(s, breakdown) for s in trace)
        cards.append(f'<div class="card"><h2>{addr}{badge}</h2>'
                     f'<p class="addr-sub">{sub}</p>{steps}</div>')

    note = ('Attribution is best-effort: later steps only fill columns left NULL by '
            'earlier ones, and provenance flags are merged, so each value is attributed '
            '(<span class="dot">●</span>) to the earliest step that owns it and ran.')
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<title>Enrichment pipeline — ZIP {html.escape(zip_code)}</title>'
        f'<style>{CSS}</style></head><body><div class="wrap">'
        f'<h1>Enrichment pipeline &middot; ZIP {html.escape(zip_code)}</h1>'
        f'<p class="sub">{len(rows)} properties &middot; generated {generated}</p>'
        f'<div class="note">{note}</div>'
        f'{"".join(cards)}</div></body></html>'
    )


# ── Markdown rendering ─────────────────────────────────────────────────────────

def render_md(zip_code: str, rows: list[dict], vertical_override: str | None) -> str:
    out = [f"# Enrichment pipeline — ZIP {zip_code}",
           f"\n_{len(rows)} properties · generated {datetime.now():%Y-%m-%d %H:%M}_\n",
           "> Attribution is best-effort: values are marked (●) under the earliest step "
           "that owns the column and ran.\n"]

    rates = coverage(rows)
    out.append(f"## Coverage across {len(rows)} properties\n")
    out.append("| field | filled | % |\n|---|---|---|")
    for field, r in sorted(rates.items(), key=lambda kv: kv[1]["pct"]):
        out.append(f"| {field} | {r['filled']}/{r['total']} | {r['pct']:.0f}% |")
    out.append("")

    for row in rows:
        trace = build_trace(row)
        breakdown = score_breakdown(row, vertical_override)
        head = row.get("address") or "(unknown address)"
        loc = ", ".join(p for p in [row.get("city"), row.get("state"), row.get("zip")] if p)
        grade = row.get("score_grade")
        gtxt = f" — grade {grade} ({fmt_value('lead_score', row.get('lead_score'))})" if grade else ""
        out.append(f"\n## {head}{gtxt}\n\n_{loc}_\n")

        for step in trace:
            status = f"✅ ran ({step['source']})" if step["ran"] else "▫️ no data"
            out.append(f"**{step['num']}. {step['label']}** — {status}")
            if step["key"] == "scored" and step["ran"]:
                prof = breakdown["profile"]
                vlabel = (prof.get("vertical") or "default") + (" (default)" if prof["is_default"] else "")
                out.append(f"\n_profile: {vlabel} · total {breakdown['score']:.1f}_\n")
                out.append("| factor | signal | weight | points |\n|---|---|---|---|")
                for f in breakdown["factors"]:
                    out.append(f"| {f['label']} | {f['signal']:.2f} | "
                               f"{f['weight']:.0%} | +{f['contribution']:.1f} |")
            else:
                out.append("\n| field | value |\n|---|---|")
                for fr in step["field_rows"]:
                    dot = "● " if fr["attributed"] else ""
                    out.append(f"| {dot}{fr['name']} | {fmt_value(fr['name'], fr['value'])} |")
            out.append("")
    return "\n".join(out)


# ── Demo data (no DB) ──────────────────────────────────────────────────────────

def demo_rows() -> list[dict]:
    """Synthesize a few enriched rows so the report renders without a database."""
    from tools.score_demo import SAMPLE_LEADS

    today = date.today()
    rows = []
    for i, lead in enumerate(SAMPLE_LEADS[:5]):
        row = dict(lead)
        row["zip"] = "77044"
        # Simulate which steps touched this row via merged flags.
        flags = {"seed": "rentcast", "census": "acs5_2022", "scored": "default"}
        if row.get("year_built") is not None:        # this lead has property data
            flags["geocode"] = "google"
            flags["hcad"] = "assessor"
            flags["property"] = "rentcast"
            flags["permits"] = "hcad"
            row.update({
                "latitude": 29.85 + i * 0.01, "longitude": -95.18 - i * 0.01,
                "geohash": f"9vk1{i}x", "lot_size": 7000 + i * 250,
                "last_sale_price": (row.get("estimated_value") or 0) - 40_000 or None,
                "owner_occupied": i % 2 == 0,
                "ownership_years": (today - row["last_sale_date"]).days // 365
                                   if row.get("last_sale_date") else None,
                "has_pool": i == 0, "has_cracked_slab": i in (0, 2),
            })
        if i < 2:                                    # only top rows skip-traced
            flags["contact"] = "batchdata"
            row.update({"contact_name": row.get("owner_name"),
                        "contact_phone": f"(281) 555-0{100 + i}",
                        "contact_email": "owner@example.com"})
        score, grade = score_property(row, DEFAULT_WEIGHTS)
        row.update({"lead_score": round(score, 2), "score_grade": grade,
                    "vertical": None, "score_updated_at": datetime.now(),
                    "enrichment_flags": flags})
        rows.append(row)
    rows.sort(key=lambda r: r.get("lead_score") or 0, reverse=True)
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Visualize the enrichment pipeline for a ZIP.")
    ap.add_argument("--zip", default="77044", help="ZIP code to visualize (default 77044)")
    ap.add_argument("--limit", type=int, default=5, help="Number of properties (default 5)")
    ap.add_argument("--format", choices=["html", "md"], default="html", help="Output format")
    ap.add_argument("--out", default=None, help="Output path (default report_<zip>.<ext>)")
    ap.add_argument("--vertical", default=None,
                    help="Override scoring vertical for the score breakdown")
    ap.add_argument("--demo", action="store_true",
                    help="Use built-in sample data instead of the database")
    args = ap.parse_args()

    if args.demo:
        rows = demo_rows()
        zip_code = rows[0]["zip"] if rows else args.zip
    else:
        rows = fetch_properties(args.zip, args.limit)
        zip_code = args.zip
        if not rows:
            print(f"No properties found for ZIP {zip_code}. "
                  f"Run the pipeline first: python run_pipeline.py --zip {zip_code}")
            sys.exit(1)

    if args.format == "md":
        content = render_md(zip_code, rows, args.vertical)
        ext = "md"
    else:
        content = render_html(zip_code, rows, args.vertical)
        ext = "html"

    out = Path(args.out) if args.out else Path(f"report_{zip_code}.{ext}")
    out.write_text(content, encoding="utf-8")
    print(f"Wrote {args.format.upper()} report for {len(rows)} properties → {out}")


if __name__ == "__main__":
    main()
