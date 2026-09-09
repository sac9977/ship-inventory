#!/usr/bin/env python3
"""
prepare_impa_csv.py — Build a Stores-import CSV from the OCR'd IMPA guide.

Reads the extracted IMPA Marine Stores CSV (pdf_page, half, impa_code,
product_name, description, full_description, unit, ocr_conf), cleans it into
store-item rows, and writes an import-ready CSV.

Rows kept: pdf_page >= MIN_PAGE (skips front-matter false codes).
Cleaning:
  - canonical IMPA code: strip dots/spaces, zero-pad to 7 digits
  - junk headings (page furniture like "QUALITY SAVES COSTS...") rejected,
    paragraph (full_description) used as name instead
  - dedupe by canonical code: best row wins (has heading > has paragraph >
    higher ocr_conf > higher page)
  - category via keyword rules on heading+paragraph text
"""
import csv
import re
import sys
from collections import Counter, defaultdict

MIN_PAGE = 50

# ── Junk-heading patterns: page furniture, not product names ──
FURNITURE_RE = re.compile(
    r"qualit|saves|cost|professional|purchas|associat|international|"
    r"gaorra|«ave|triste|trssr|tiaz|sea\b|ism\b", re.I)

# ── Category keyword rules, checked in order ──
CATEGORY_RULES = [
    ("Paints",       r"paint|primer|thinner|varnish|lacquer|enamel|epoxy coat|anticorros|antifoul"),
    ("Chemicals",    r"chemical|cleaner|degreas|detergent|descal|disinfect|solvent|acid|alkali|emulsif"),
    ("Safety",       r"life jacket|lifeboat|life raft|immersion|life buoy|lifebuoy|flotation|"
                     r"pyrotechn|distress|smoke signal|helmet|goggles|safety harness|"
                     r"breathing|respirator|gas detect|fall arrest|safety belt|safety net|"
                     r"first aid|fire blanket|safety"),
    ("Fire Fighting", r"fire ?(extinguish|hose|hydrant|nozzle|pump|foam|detector|alarm|"
                      r"damper|door|flap|box|blanket)|fireman|fire man|firesafe|sprinkler"),
    ("Mooring & Anchoring", r"mooring|rope|hawser|winch|anchor|chain cable|shackle|"
                            r"wire rope|toggle|bowline|sling|tackle|turnbuckle|swivel"),
    ("Lifting Gear", r"hook|lifting|crane|hoist|pulley|sheave|eyebolt|eye bolt|"
                     r"eye nut|d?shackle|load bind"),
    ("Rigging & Hardware", r"shackle|turnbuckle|thimble|swivel|link|clamp|grip|"
                           r"wire clip|snatch block|tackle"),
    ("Hand Tools",   r"wrench|spanner|screwdriver|plier|hammer|chisel|file|"
                     r"drill|saw|socket|torque|allen|allenkey|vise|vice grip|"
                     r"tong|tongs|scraper|pick|punch|reamer|tap\b|die\b|measur"),
    ("Cutting Tools", r"cutter|cutting|knife|blade|shear|snip|hacksaw|abrasive|"
                      r"grinding|cut-off|carbide"),
    ("Electrical",   r"lamp|bulb|light|battery|cable|wire\b|fuse|switch|socket|"
                     r"connector|extension|insulat|motor|transformer|conduct|led\b|"
                     r"fluoresc|torch|flashlight|lantern"),
    ("Piping & Valves", r"valve|pipe|pipe ?fitting|elbow|tee\b|coupling|flange|"
                        r"gasket|clamp\s?\(|hose\b|nipple|union\b|bushing|strainer"),
    ("Fasteners",    r"screw|bolt|nut\b|washer|rivet|pin\b|stud\b|thread|insert"),
    ("Tableware",    r"cutlery|plate|bowl|cup|mug|glass|tray|spoon|fork|knife|"
                     r"saucer|dish|crockery"),
    ("Galley",       r"galley|kitchen|cook|oven|fry|grill|toaster|kettle|percolator|"
                     r"utensil|saucepan|pot\b|pan\b|dishwash|refrigerat|freezer|"
                     r"microwave|blender|mixer|coffee|churn|steak|catering"),
    ("Provisions",   r"food|provision|flour|sugar|rice|salt|sauce|jam|honey|"
                     r"milk|tea|coffee\b|biscuit|canned|tinned|grocer|sundries"),
    ("Cabin & Cleaning", r"mop|broom|brush|bucket|dustpan|garbage|bin\b|linen|"
                         r"towel|blanket|pillow|curtain|carpet|mattress|sheet\b|"
                         r"cabin|laundry|detergent dispens|air freshen|soap"),
    ("Measuring",    r"thermometer|hygrometer|barometer|clock|watch|stopwatch|"
                     r"rules?\b|tape\b|caliper|micrometer|level\b|scale\b"),
    ("Insulation",   r"insulat|asbestos|ceramic fiber|mineral wool"),
    ("Welding",      r"weld|electrode|nozzle tip|cutting tip|torch tip|"
                     r"welding (rod|wire|mask|glove|helmet)"),
    ("Medical",      r"medical|medicine|surgical|bandage|dressing|splint|"
                     r"stretcher|ambulance|clinical|oxygen"),
]

JUNK_DESC_LEAD = re.compile(
    r"^(breaking|making|strength|kn\b| colour|\(colour|code\b|mm\b|size\b|type\b|"
    r"limit|grade|unit|part\b|no\.?\b)", re.I)


def canon_code(raw):
    """Normalize OCR'd IMPA code: '33.0140'/'330140' -> '3301400' (7 digits)."""
    digits = re.sub(r"\D", "", raw or "")
    if not (5 <= len(digits) <= 7):
        return ""
    return digits.zfill(7)


def is_junk_heading(name):
    if not name:
        return True
    return bool(FURNITURE_RE.search(name))


def clean_text(s):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s


def pick_paragraph(r):
    """Paragraph text or empty; drop rows that lead with table-header junk."""
    p = clean_text(r.get("full_description", ""))
    if p and JUNK_DESC_LEAD.match(p):
        return ""
    return p


def classify(text):
    t = text.lower()
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, t):
            return cat
    return "General"


def best(r):
    """Sort key: prefer rows with a real heading, then paragraph, conf, page."""
    conf = float(r.get("ocr_conf") or 0)
    page = int(r.get("pdf_page") or 0)
    return (not is_junk_heading(r["product_name"]),
            bool(pick_paragraph(r)), conf, page)


def apply_prefix_votes(out_rows):
    """IMPA code prefixes are meaningful (17=provisions, 25=paints, ...).
    Let confidently-classified rows vote per 2-digit prefix, then apply the
    winning category to rows still in General under that prefix."""
    votes = defaultdict(Counter)
    for row in out_rows:
        if row["category"] != "General":
            votes[row["impa_code"][:2]][row["category"]] += 1
    strong = {}
    for prefix, c in votes.items():
        top, n = c.most_common(1)[0]
        classified = sum(c.values())
        if n >= 5 and n / classified >= 0.5:
            strong[prefix] = top
    reassigned = 0
    for row in out_rows:
        p = row["impa_code"][:2]
        if row["category"] == "General" and p in strong:
            row["category"] = strong[p]
            reassigned += 1
    return reassigned


def main():
    src, dst = sys.argv[1], sys.argv[2]
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))

    by_code = defaultdict(list)
    for r in rows:
        if int(r["pdf_page"] or 0) < MIN_PAGE:
            continue
        code = canon_code(r["impa_code"])
        if not code:
            continue
        by_code[code].append(r)

    out_rows = []
    for code, group in by_code.items():
        g = sorted(group, key=best, reverse=True)
        r = g[0]
        para = pick_paragraph(r)
        heading = clean_text(r["product_name"])
        if is_junk_heading(heading):
            name = (para.split(". ")[0].strip(" .;-")[:80] or code)
            desc = para
        else:
            name = heading[:80]
            desc = para or clean_text(r["description"])[:160]
        unit = (r.get("unit") or "").strip() or "pcs"
        out_rows.append({
            "impa_code": code,
            "name": name or code,
            "description": desc[:200],
            "category": classify(f"{heading} {para}"),
            "quantity": "0",
            "unit": unit[:20],
            "min_stock": "0",
            "location": "",
        })

    reassigned = apply_prefix_votes(out_rows)

    out_rows.sort(key=lambda x: x["impa_code"])
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["impa_code", "name", "description",
                                          "category", "quantity", "unit",
                                          "min_stock", "location"])
        w.writeheader()
        w.writerows(out_rows)

    cats = Counter(r["category"] for r in out_rows)
    print(f"rows in: {len(rows)}, kept codes: {len(out_rows)}, "
          f"prefix-reassigned: {reassigned}, written: {dst}")
    for cat, n in cats.most_common():
        print(f"  {n:6d}  {cat}")


if __name__ == "__main__":
    main()
