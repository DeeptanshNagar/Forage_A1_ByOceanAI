"""Synthesize the two demo document sets into demos/sources/.

Default: render the committed prose in demos/synthesis_prompts/content/ (produced from the *.prompt.md prompts) to the
target formats and generate the catalogue CSV deterministically (seed 7).
--llm  : regenerate the prose with the configured local model from the same prompts first.
"""
from __future__ import annotations

import argparse
import csv
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "demos" / "synthesis_prompts"
CONTENT = PROMPTS / "content"
OUT_HR = ROOT / "demos" / "sources" / "hr"
OUT_PROC = ROOT / "demos" / "sources" / "procurement"

TARGETS = [  # (content file, prompt file, output path, format)
    ("leave_policy.md", "hr_leave_policy.prompt.md", OUT_HR / "leave_policy.pdf", "pdf"),
    ("code_of_conduct_travel_expenses.md", "hr_conduct_travel.prompt.md", OUT_HR / "code_of_conduct_travel_expenses.md", "md"),
    ("grievance_disciplinary.md", "hr_grievance.prompt.md", OUT_HR / "grievance_disciplinary.docx", "docx"),
    ("supplier_terms.md", "supplier_terms.prompt.md", OUT_PROC / "supplier_terms.pdf", "pdf"),
    ("delivery_warranty.md", "delivery_warranty.prompt.md", OUT_PROC / "delivery_warranty.pdf", "pdf"),
]


def _blocks(md: str):
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            yield ("blank", "")
        elif s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            yield (f"h{level}", s.lstrip("#").strip())
        elif s.lstrip().startswith(("- ", "* ")):
            yield ("bullet", s.lstrip()[2:])
        else:
            yield ("p", s)


def render_pdf(md: str, out: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    story, bullets = [], []

    def flush():
        if bullets:
            story.append(ListFlowable([ListItem(Paragraph(b, styles["BodyText"])) for b in bullets], bulletType="bullet"))
            bullets.clear()

    for kind, text in _blocks(md):
        text = text.replace("&", "&amp;").replace("<", "&lt;")
        if kind == "bullet":
            bullets.append(text)
            continue
        flush()
        if kind == "h1":
            story.append(Paragraph(text, styles["Title"]))
        elif kind in ("h2", "h3"):
            story.append(Paragraph(text, styles["Heading2"]))
        elif kind == "p":
            story.append(Paragraph(text, styles["BodyText"]))
        else:
            story.append(Spacer(1, 4))
    flush()
    out.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(out), pagesize=A4, title=out.stem).build(story)


def render_docx(md: str, out: Path) -> None:
    import docx

    d = docx.Document()
    for kind, text in _blocks(md):
        if kind.startswith("h"):
            d.add_heading(text, level=min(int(kind[1]), 3) - 1 if kind == "h1" else min(int(kind[1]) - 1, 3))
        elif kind == "bullet":
            d.add_paragraph(text, style="List Bullet")
        elif kind == "p":
            d.add_paragraph(text)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))


CATEGORIES = {  # prefix, price range, lead time range, moq choices, description stems
    "Engine": ("ENG", (120, 9500), (14, 60), [1, 1, 2], ["cylinder liner", "piston ring set", "fuel injector", "exhaust valve",
                                                         "turbocharger cartridge", "cylinder head gasket", "connecting rod bearing",
                                                         "governor actuator"]),
    "Pumps": ("PMP", (300, 7200), (10, 45), [1, 1, 2], ["centrifugal pump impeller", "mechanical seal kit", "ballast pump shaft",
                                                       "fuel transfer pump", "bilge pump motor", "pump casing wear ring"]),
    "Electrical": ("ELE", (25, 3800), (5, 30), [1, 2, 5, 10], ["circuit breaker 63A", "generator AVR", "cable gland set", "motor starter",
                                                              "LED floodlight", "switchboard relay", "battery charger 24V"]),
    "Navigation": ("NAV", (400, 15000), (20, 75), [1], ["radar magnetron", "GPS antenna", "gyro compass sensor", "ECDIS display unit",
                                                       "AIS transponder", "echo sounder transducer"]),
    "Safety": ("SAF", (30, 2600), (3, 21), [1, 2, 10], ["lifejacket SOLAS", "immersion suit", "fire extinguisher CO2 5kg", "EEBD set",
                                                       "SCBA cylinder", "lifebuoy light", "fire hose 20m"]),
    "Deck Machinery": ("DEK", (200, 12000), (21, 90), [1, 2], ["windlass brake lining", "mooring winch gearbox", "hydraulic hose assembly",
                                                              "crane slewing bearing", "capstan motor"]),
    "HVAC": ("HVA", (60, 5400), (7, 40), [1, 2, 4], ["compressor valve plate", "condenser fan motor", "expansion valve",
                                                    "air handling unit belt", "refrigerant dryer"]),
    "Filters": ("FIL", (8, 650), (2, 14), [5, 10, 20], ["lube oil filter element", "fuel oil filter cartridge", "air intake filter",
                                                       "separator strainer", "hydraulic return filter"]),
}
VESSEL_CLASSES = ["Bulk Carrier", "Container Ship", "Tanker", "Offshore Supply Vessel"]
SUPPLIERS = ["Marisupply GmbH", "Oceanic Parts Co", "Baltic Marine Spares", "Kestrel Engineering", "Harbour Tech Ltd"]


def make_catalogue(out: Path, n: int = 168, seed: int = 7) -> None:
    rng = random.Random(seed)
    rows = []
    counters = {c: 1000 for c in CATEGORIES}
    cats = list(CATEGORIES)
    for i in range(n):
        cat = cats[i % len(cats)]
        prefix, (lo, hi), (lt_lo, lt_hi), moqs, stems = CATEGORIES[cat]
        counters[cat] += rng.randint(1, 7)
        stem = rng.choice(stems)
        vc = rng.choice(VESSEL_CLASSES)
        rows.append({
            "part_no": f"{prefix}-{counters[cat]}",
            "description": f"{stem.capitalize()} for {vc.lower()}s",
            "category": cat, "vessel_class": vc, "supplier": rng.choice(SUPPLIERS),
            "unit_price": f"{round(rng.uniform(lo, hi), 2):.2f}",
            "lead_time_days": rng.randint(lt_lo, lt_hi),
            "min_order_qty": rng.choice(moqs),
            "stock": 0 if rng.random() < 0.15 else rng.randint(1, 60),
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def regenerate_with_llm() -> None:
    sys.path.insert(0, str(ROOT))
    from forge.config import load_settings
    from forge.llm import LLM

    llm = LLM(load_settings())
    for content, prompt, _, _ in TARGETS:
        p = (PROMPTS / prompt).read_text(encoding="utf-8")
        text = llm.chat([{"role": "user", "content": p + "\n\nWrite the document in markdown now."}], role="factory",
                        max_tokens=2500)
        (CONTENT / content).write_text(re.sub(r"^```\w*\n|```$", "", text.strip()), encoding="utf-8")
        print("regenerated", content)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="regenerate prose with the configured model first")
    args = ap.parse_args()
    if args.llm:
        regenerate_with_llm()
    for content, _, out, fmt in TARGETS:
        md = (CONTENT / content).read_text(encoding="utf-8")
        if fmt == "pdf":
            render_pdf(md, out)
        elif fmt == "docx":
            render_docx(md, out)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
        print("wrote", out.relative_to(ROOT))
    make_catalogue(OUT_PROC / "spares_catalogue.csv")
    print("wrote", (OUT_PROC / "spares_catalogue.csv").relative_to(ROOT))


if __name__ == "__main__":
    main()
