#!/usr/bin/env python3
"""Prototype v2 of the learning site: a view of what the nightly attacks have taught us.

Reads the project folder (default /home/box/learning, override with LEARNING_ROOT) and writes
ONLY into docs/v2/ next to this script. It never touches the rest of docs/ (built by build.py).

Data used, all from the project folder:
  claims/, ledgers/, links.tsv, sources.tsv, sources/*/METADATA.md, open-questions.md,
  candidates/README.md, wisdom/rules.md (draft practical rules and diagram labels), and
  archive/old-sites/*.bundle (the published history of the old learning-graph site, used to
  recover earlier claim wordings; nothing is inferred beyond what those snapshots contain).
No local filesystem paths are ever written to the output.
"""
from __future__ import annotations
import csv, difflib, html, json, os, re, shutil, subprocess, sys, tempfile, unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("LEARNING_ROOT", "/home/box/learning"))
OUT = Path(__file__).resolve().parent / "docs" / "v2"
TZ = ZoneInfo("Europe/Stockholm")
TODAY = datetime.now(TZ).date()
SITE = "Learning, under fire"
QUESTIONS = {"Q1": "What is optimal learning?",
             "Q2": "How do we achieve it when AI and screens are everywhere?"}
VERDICT_WORD = {"survived": "survived", "weakened": "narrowed", "killed": "killed"}
PATH_RE = re.compile(r"(/home/box|/workspace)[^\s<>\"')]*")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

# ------------------------------------------------------------------ small helpers
def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)

def inline(s: str) -> str:
    """Escape, then render markdown **bold**, *em* and `code`."""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def nice_date(d: str | date) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"

def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

def norm(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip().rstrip(".").strip()

def verdict_word(e: dict) -> str:
    v = (e.get("Verdict") or "").split()
    return VERDICT_WORD.get(v[0], v[0]) if v else "unknown"

def plural(n: int, w: str, pl: str | None = None) -> str:
    return f"{n} {w if n == 1 else (pl or w + 's')}"

# ------------------------------------------------------------------ load project data
def parse_fields(text: str) -> dict:
    f = {}
    for line in text.splitlines():
        if re.fullmatch(r"[CK]\d+", line.strip()):
            f["id"] = line.strip(); continue
        if line.startswith("Sources allowed"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            f.setdefault(k.strip(), v.strip())
    return f

def parse_ledger(text: str) -> list[dict]:
    entries, cur = [], None
    for ln in text.splitlines():
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ln.strip()):
            cur = {"date": ln.strip()}; entries.append(cur); continue
        if cur is not None and ":" in ln:
            k, _, v = ln.partition(":"); cur.setdefault(k.strip(), v.strip())
    return entries

claims: dict[str, dict] = {}
for p in sorted((ROOT / "claims").glob("C*.md"), key=lambda p: int(re.match(r"C(\d+)", p.stem).group(1))):
    f = parse_fields(read(p))
    led = ROOT / "ledgers" / p.name
    f["ledger"] = parse_ledger(read(led)) if led.exists() else []
    for i, e in enumerate(f["ledger"], 1):
        e["n"] = i; e["claim"] = f["id"]
    claims[f["id"]] = f

def author_year_from_meta(d: str, meta: dict, year: str) -> str:
    au = meta.get("Författare", "")
    y = (re.search(r"\d{4}", year or "") or re.search(r"\d{4}", d))
    y = y.group(0) if y else ""
    if au.startswith("OECD"):
        names = ["OECD"]
    else:
        names = []
        for a in [x.strip() for x in au.split(";") if x.strip()]:
            a = re.sub(r"\(.*?\)", "", a).strip()
            names.append(a.split(",")[0].strip() if "," in a else a.split()[-1])
    if not names:
        names = [d.split("-")[0].capitalize()]
    if len(names) == 1:
        s = names[0]
    elif len(names) == 2:
        s = f"{names[0]} & {names[1]}"
    else:
        s = f"{names[0]} et al."
    return f"{s} {y}".strip()

sources: dict[str, dict] = {}
with open(ROOT / "sources.tsv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh, delimiter="\t"):
        d = r["dir"]; meta = {}
        mp = ROOT / "sources" / d / "METADATA.md"
        if mp.exists():
            for ln in read(mp).splitlines():
                if ":" in ln and not ln.startswith("#"):
                    k, _, v = ln.partition(":"); meta.setdefault(k.strip().strip("*").strip(), v.strip())
        r["ay"] = author_year_from_meta(d, meta, r.get("year", ""))
        sources[d] = r

links = []
with open(ROOT / "links.tsv", encoding="utf-8") as fh:
    links = [r for r in csv.DictReader(fh, delimiter="\t")]
links_by_claim = defaultdict(list)
for l in links:
    links_by_claim[l["claim"]].append(l)

def resolve_source(label: str) -> str | None:
    """'Roediger & Karpicke 2006' -> source folder name, if one matches first author + year."""
    m = re.search(r"([A-Za-zÀ-ÿ\-]+).*?(\d{4})", label)
    if not m:
        return None
    first, year = fold(m.group(1)), m.group(2)
    hits = [d for d in sources if fold(d).startswith(first + "-") and f"-{year}" in d]
    return hits[0] if len(hits) == 1 else (sorted(hits)[0] if hits else None)

def source_label(e: dict) -> str:
    """Public citation for a ledger entry: author-year only, never paths."""
    parts = [p.strip() for p in (e.get("Source") or "").split("|")]
    named = [p for p in parts if p and p != "apprentice" and "/" not in p and not p.lower().startswith(("path", "doi"))]
    return "; ".join(named) if named else "no named source (attacker's own inference)"

# rules file
RULES_FILE = ROOT / "wisdom" / "rules.md"
rules, labels, rules_status = [], {}, ""
if RULES_FILE.exists():
    cur = None; section = "rules"
    for ln in read(RULES_FILE).splitlines():
        if ln.startswith("# ") and "label" in ln.lower():
            section = "labels"; cur = None; continue
        if ln.startswith("Status:") and not rules_status:
            rules_status = ln.partition(":")[2].strip(); continue
        m = re.match(r"## (\S+)", ln)
        if m:
            cur = {"id": m.group(1)}
            (rules.append(cur) if section == "rules" else labels.__setitem__(m.group(1), cur)); continue
        if cur is not None and ":" in ln:
            k, _, v = ln.partition(":"); cur[k.strip()] = v.strip()
rules = [r for r in rules if r.get("Rule") and r.get("Claim") in claims]

open_q = read(ROOT / "open-questions.md") if (ROOT / "open-questions.md").exists() else ""
promoted = {}
cr = ROOT / "candidates" / "README.md"
if cr.exists():
    for sent in re.findall(r"[^.\n]*promoted on \d{4}-\d{2}-\d{2}[^.\n]*", read(cr)):
        dm = re.search(r"\d{4}-\d{2}-\d{2}", sent).group(0)
        for c in re.findall(r"\bC\d+\b", sent):
            promoted[c] = dm

def serves(c: dict) -> list[str]:
    return re.findall(r"Q\d", (c.get("Serves", "").split("(")[0]))

edges = []
for cid, c in claims.items():
    for fld, kind in (("Depends on", "depends-on"), ("Relates to", "relates-to")):
        for a, t, b in re.findall(r"(C\d+) (depends-on|relates-to) (C\d+)", c.get(fld, "")):
            if a == cid and (a, t, b) not in edges:
                edges.append((a, t, b))

# ------------------------------------------------------------------ published history (old site bundles)
def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()

def parse_snapshot(h: str) -> dict:
    out, cur = {}, None
    body = h.split("<body", 1)[-1]
    parts = re.split(r"<h2>(.*?)</h2>", body)
    for i in range(1, len(parts), 2):
        title, content = strip_tags(parts[i]), parts[i + 1]
        m = re.search(r'<article class="claim">(.*?)</article>', content, re.S)
        if m:
            a = m.group(1)
            idm = re.search(r'class="claim-id">\s*(C\d+)', a)
            if not idm:
                continue
            cur = idm.group(1)
            b = re.search(r"<dt>Bounds</dt>\s*<dd>(.*?)</dd>", a, re.S)
            bounds = strip_tags(b.group(1)) if b else ""
            out[cur] = {"claim": strip_tags(re.search(r"<p>(.*?)</p>", a, re.S).group(1)),
                        "bounds": "" if bounds in ("—", "-") else bounds, "ledger": []}
        elif title.startswith("Ledger"):
            mm = re.search(r"(C\d+)", title); cid = mm.group(1) if mm else cur
            for blk in re.findall(r'<pre class="ledger-block">(.*?)</pre>', content, re.S):
                e = {}
                for line in html.unescape(blk).split("\n"):
                    if ":" in line:
                        k, _, v = line.partition(":"); e.setdefault(k.strip(), v.strip())
                if cid in out:
                    out[cid]["ledger"].append(e)
    return out

snapshots = []  # list of {"time": datetime, "claims": {...}}
bundle_dir = ROOT / "archive" / "old-sites"
if bundle_dir.exists():
    for bundle in sorted(bundle_dir.glob("*.bundle")):
        with tempfile.TemporaryDirectory() as tmp:
            rp = subprocess.run(["git", "-c", "init.defaultBranch=main", "clone", "-q", str(bundle), tmp + "/r"],
                                capture_output=True, text=True)
            if rp.returncode:
                continue
            g = lambda *a: subprocess.run(["git", "-C", tmp + "/r", *a], capture_output=True, text=True).stdout
            head = g("show", "HEAD:docs/index.html")
            if 'class="claim-id"' not in head or "ledger-block" not in head:
                continue
            for c in g("rev-list", "--reverse", "HEAD").split():
                h = g("show", f"{c}:docs/index.html")
                if not h:
                    continue
                t = datetime.fromisoformat(g("log", "-1", "--format=%aI", c).strip()).astimezone(TZ)
                snapshots.append({"time": t, "claims": parse_snapshot(h)})
snapshots.sort(key=lambda s: s["time"])

def akey(s: str) -> str:
    return norm(s or "")[:90]

# ------------------------------------------------------------------ history reconstruction
def tokens(s: str) -> list[str]:
    return re.findall(r"\s+|[\w’'~\-–./%≈−]+|[^\w\s]", s)

def _regions(ta: list[str], tb: list[str], gap_words: int) -> list[list[int]]:
    ops = difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes()
    regions = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        if regions:
            between = "".join(ta[regions[-1][1]:i1])
            if len(between.split()) <= gap_words and not re.search(r"[.;:—]", between):
                regions[-1][1], regions[-1][3] = i2, j2
                continue
        regions.append([i1, i2, j1, j2])
    return regions

def diff_html(a: str, b: str, gap_words: int = 2) -> tuple[str, bool]:
    """Word diff; nearby changes are merged into one block so the result stays readable."""
    ta, tb = tokens(a), tokens(b)
    regions = _regions(ta, tb, gap_words)
    out, pi = [], 0
    for i1, i2, j1, j2 in regions:
        out.append(inline("".join(ta[pi:i1])))
        old, new = "".join(ta[i1:i2]), "".join(tb[j1:j2])
        lead = re.match(r"\s*", new).group(0)
        trail = new[len(new.rstrip()):]
        if old.strip():
            out.append(f"<del>{esc(old.strip())}</del>")
            out.append(old[len(old.rstrip()):] if not new.strip() else " ")
        if new.strip():
            out.append(("" if old.strip() else lead) + f"<ins>{esc(new.strip())}</ins>" + trail)
        pi = i2
    out.append(inline("".join(ta[pi:])))
    return re.sub(r"  +", " ", "".join(out)), bool(regions)

def diff_regions(a: str, b: str, gap_words: int = 3) -> list[tuple[str, str]]:
    """Changed regions, merging changes separated by at most `gap_words` unchanged words."""
    ta, tb = tokens(a), tokens(b)
    ops = difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes()
    regions = []
    for op, i1, i2, j1, j2 in ops:
        if op == "equal":
            continue
        if regions:
            pi2, pj2 = regions[-1][1], regions[-1][3]
            between = "".join(ta[pi2:i1])
            if len(between.split()) <= gap_words and not re.search(r"[.;:—]", between):
                regions[-1][1], regions[-1][3] = i2, j2
                continue
        regions.append([i1, i2, j1, j2])
    # extend each region by one following unchanged word, so phrases read naturally
    for r in regions:
        i, j, taken = r[1], r[3], 0
        while i < len(ta) and j < len(tb) and ta[i] == tb[j] and taken < 1:
            if re.match(r"\w", ta[i]):
                taken += 1
            elif not ta[i].isspace():
                break
            i += 1; j += 1
        if taken:
            r[1], r[3] = i, j
    pairs = [("".join(ta[r[0]:r[1]]).strip(" ,."), "".join(tb[r[2]:r[3]]).strip(" ,.")) for r in regions]
    return [p for p in pairs if p[0] or p[1]]

def diff_phrases(a: str, b: str) -> tuple[list[str], list[str]]:
    ta, tb = tokens(a), tokens(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    dels, ins = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            if i2 > i1 and "".join(ta[i1:i2]).strip():
                dels.append("".join(ta[i1:i2]).strip())
            if j2 > j1 and "".join(tb[j1:j2]).strip():
                ins.append("".join(tb[j1:j2]).strip())
    return dels, ins

def build_history(cid: str) -> dict:
    c = claims[cid]
    led = c["ledger"]
    snaps = [(s["time"], s["claims"][cid]) for s in snapshots if cid in s["claims"]]
    info = {"snaps": snaps, "steps": [], "first_seen": {}, "note": []}
    if not snaps:
        info["start"] = None
        return info
    keys = {akey(e.get("Attack")): e for e in led}
    first_final, first_any = {}, {}
    for si, (t, sc) in enumerate(snaps):
        for se in sc["ledger"]:
            e = keys.get(akey(se.get("Attack")))
            if not e:
                continue
            first_any.setdefault(e["n"], si)
            if (se.get("Verdict") or "").split()[:1] == (e.get("Verdict") or "").split()[:1]:
                first_final.setdefault(e["n"], si)
    info["first_seen"] = first_final
    info["start"] = {"time": snaps[0][0], "claim": snaps[0][1]["claim"], "bounds": snaps[0][1]["bounds"]}
    prev_claim, prev_bounds = snaps[0][1]["claim"], snaps[0][1]["bounds"]
    steps = []
    for si in range(len(snaps)):
        t, sc = snaps[si]
        new = [e for e in led if first_final.get(e["n"]) == si]
        changed = norm(sc["claim"]) != norm(prev_claim) or norm(sc["bounds"]) != norm(prev_bounds)
        if si == 0 and not new:
            continue
        surv = [e for e in new if verdict_word(e) != "narrowed"]
        narr = [e for e in new if verdict_word(e) == "narrowed"]
        for e in surv:
            steps.append({"entries": [e], "time": t, "claim": prev_claim, "bounds": prev_bounds,
                          "prev_claim": prev_claim, "prev_bounds": prev_bounds, "kind": "unchanged"})
        if narr or changed:
            st = {"entries": narr, "time": t, "claim": sc["claim"], "bounds": sc["bounds"],
                  "prev_claim": prev_claim, "prev_bounds": prev_bounds,
                  "kind": "merged" if len(narr) > 1 else ("changed" if narr else "unattributed")}
            for e in narr:
                if first_any.get(e["n"], si) < si:
                    st.setdefault("relogged", []).append((e, snaps[first_any[e["n"]]][0]))
            steps.append(st)
        prev_claim, prev_bounds = sc["claim"], sc["bounds"]
    # attacks logged after the archived record ends
    post = [e for e in led if e["n"] not in first_final]
    cur_claim, cur_bounds = c.get("Claim", ""), c.get("Bounds", "")
    if post or norm(cur_claim) != norm(prev_claim) or norm(cur_bounds) != norm(prev_bounds):
        for e in [e for e in post if verdict_word(e) != "narrowed"]:
            steps.append({"entries": [e], "time": None, "claim": None, "bounds": None, "prev_claim": prev_claim,
                          "prev_bounds": prev_bounds, "kind": "post-unknown"})
        narr = [e for e in post if verdict_word(e) == "narrowed"]
        if narr or norm(cur_claim) != norm(prev_claim) or norm(cur_bounds) != norm(prev_bounds):
            steps.append({"entries": narr, "time": None, "claim": cur_claim, "bounds": cur_bounds,
                          "prev_claim": prev_claim, "prev_bounds": prev_bounds, "kind": "post"})
    info["steps"] = steps
    info["current_matches_archive"] = norm(cur_claim) == norm(prev_claim)
    return info

history = {cid: build_history(cid) for cid in claims}

# ------------------------------------------------------------------ bounds and carve-outs
ABBR = ["et al.", "e.g.", "i.e.", "Exp.", "vs.", "cf.", "No.", "approx.", "m.fl."]

def split_sentences(s: str) -> list[str]:
    t = s
    for a in ABBR:
        t = t.replace(a, a.replace(".", "§"))
    parts = re.split(r"(?:(?<=[.!?])|(?<=[.!?][”\"’)]))\s+(?=[A-Z“\"(])", t)
    return [p.replace("§", ".").strip() for p in parts if p.strip()]

def split_clauses(sentence: str) -> list[str]:
    out, depth, buf = [], 0, ""
    i = 0
    while i < len(sentence):
        ch = sentence[i]
        depth += ch == "("; depth -= ch == ")"
        if ch == ";" and depth == 0:
            out.append(buf.strip()); buf = ""; i += 1; continue
        buf += ch; i += 1
    if buf.strip():
        out.append(buf.strip())
    merged = []
    for cl in out:
        if merged and re.match(r"(C\d+\b|it |this |that |they )", cl):
            merged[-1] = merged[-1] + "; " + cl
        else:
            merged.append(cl)
    return merged

def bound_items(c: dict) -> list[dict]:
    items = []
    fine = bool(history[c["id"]]["snaps"])  # split at semicolons only where history can attribute the parts
    for s in split_sentences(c.get("Bounds", "")):
        for cl in (split_clauses(s) if fine else [s]):
            items.append({"text": cl[:1].upper() + cl[1:], "match": cl, "field": "Bounds"})
    m = re.search(r"does not hold when (.+?)\.(?:\s|$)", c.get("Claim", ""))
    if m:
        for part in re.split(r",\s*(?:or\s+)?when\s+|\s+or\s+when\s+", m.group(1)):
            if part.strip():
                items.append({"text": "Does not hold when " + part.strip().rstrip(","), "match": part.strip(), "field": "Claim"})
    dnt = split_sentences(c.get("Does-not-transfer-to", ""))
    if dnt:
        items.append({"text": "Does not transfer to: " + dnt[0], "match": dnt[0], "detail": " ".join(dnt[1:]), "field": "Does-not-transfer-to"})
    return items

def overlap_score(text: str, e: dict) -> float:
    w = lambda s: {x for x in re.findall(r"[a-z][a-z\-]{3,}", fold(s))}
    a = w(text); b = w(" ".join([e.get("Attack", ""), e.get("Steelmans to", ""), e.get("Why", "")]))
    return len(a & b) / (len(a) or 1)

def attribute(cid: str, it: dict) -> dict:
    h = history[cid]; c = claims[cid]
    snaps = h["snaps"]; led = c["ledger"]
    needle = norm(it.get("match", it["text"]))
    def present(si):
        sc = snaps[si][1]
        return needle.lower() in norm(sc["claim"] + " " + sc["bounds"]).lower()
    if not snaps:
        when = promoted.get(cid) or c.get("Last change", "")
        return {"kind": "creation", "date": when, "entries": []}
    first = next((si for si in range(len(snaps)) if present(si)), None)
    def candidates(si):
        return [e for e in led if h["first_seen"].get(e["n"]) == si and verdict_word(e) == "narrowed"]
    def pick(cands, text):
        if len(cands) <= 1:
            return cands, False
        by_name = [e for e in cands if any(fold(n) in fold(text) for n in re.findall(r"[A-Z][a-zà-ÿ]+", source_label(e)) if len(n) > 3)]
        if len(by_name) == 1:
            return by_name, "name"
        sc = sorted(((overlap_score(text, e), e) for e in cands), key=lambda x: -x[0])
        if sc[0][0] > 0 and sc[0][0] >= 1.5 * sc[1][0]:
            return [sc[0][1]], "wording"
        return cands, False
    if first is None:
        post = [e for e in led if e["n"] not in h["first_seen"] and verdict_word(e) == "narrowed"]
        ents, by_word = pick(post, it["text"])
        return {"kind": "post" if ents else "unknown", "entries": ents, "by_wording": by_word, "date": c.get("Last change", "")}
    if first == 0:
        return {"kind": "original", "date": snaps[0][0].date().isoformat(), "entries": []}
    ents, by_word = pick(candidates(first), it["text"])
    res = {"kind": "attack" if ents else "unattributed", "entries": ents, "by_wording": by_word,
           "date": snaps[first][0].date().isoformat(), "time": snaps[first][0]}
    # earlier, differently worded form of the same bound?
    prev = snaps[first - 1][1]
    best, best_cl = 0.0, None
    for s in split_sentences(prev["bounds"]):
        for cl in split_clauses(s):
            r = difflib.SequenceMatcher(None, norm(cl).lower(), needle.lower()).ratio()
            if r > best:
                best, best_cl = r, cl
    if best >= 0.55 and best_cl and norm(best_cl).lower() not in norm(snaps[first][1]["bounds"]).lower():
        sub = attribute(cid, {"text": best_cl})
        res["earlier"] = {"text": best_cl, "attr": sub}
    return res

# ------------------------------------------------------------------ html pieces
def dots_svg(entries: list[dict], r: float = 6, gap: float = 5, label: bool = True, x0: float = 0, y0: float = 0,
             standalone: bool = True) -> str:
    if not entries:
        return ""
    step = 2 * r + gap
    parts = []
    for i, e in enumerate(entries):
        cx, cy = x0 + r + 1.5 + i * step, y0 + r + 1.5
        vw = verdict_word(e)
        tip = f"Attack {e['n']} on {e['claim']}, {e['date']}: {vw} ({source_label(e)})"
        if vw == "survived":
            shape = f'<circle cx="{cx}" cy="{cy}" r="{r}" class="d-surv"/>'
        elif vw == "narrowed":
            shape = (f'<circle cx="{cx}" cy="{cy}" r="{r - 1}" class="d-narr"/>'
                     f'<path d="M{cx},{cy - r + 1} A{r - 1},{r - 1} 0 0 0 {cx},{cy + r - 1} Z" class="d-narr-h"/>')
        else:
            shape = (f'<line x1="{cx - r}" y1="{cy - r}" x2="{cx + r}" y2="{cy + r}" class="d-kill"/>'
                     f'<line x1="{cx - r}" y1="{cy + r}" x2="{cx + r}" y2="{cy - r}" class="d-kill"/>')
        parts.append(f"<g><title>{esc(tip)}</title>{shape}</g>")
    if not standalone:
        return "".join(parts)
    cnt = Counter(verdict_word(e) for e in entries)
    aria = (f"Attack record: {plural(len(entries), 'attack')} in chronological order, "
            + ", ".join(f"{cnt[w]} {w}" for w in ("survived", "narrowed", "killed") if cnt[w]) + ". Sequence: "
            + ", ".join(verdict_word(e) for e in entries) + ".")
    w = len(entries) * step - gap + 3
    return (f'<svg class="dots" width="{w:.0f}" height="{2 * r + 3:.0f}" viewBox="0 0 {w:.0f} {2 * r + 3:.0f}" role="img" '
            f'aria-label="{esc(aria)}">{"".join(parts)}</svg>')

def record_text(c: dict) -> str:
    led = c["ledger"]
    if not led:
        return "No attacks yet"
    cnt = Counter(verdict_word(e) for e in led)
    return f"{plural(len(led), 'attack')}: " + ", ".join(f"{cnt[w]} {w}" for w in ("survived", "narrowed", "killed") if cnt[w])

def status_pill(c: dict) -> str:
    st = (c.get("Status") or "").split()[0].lower()
    word = {"weakened": "narrowed", "alive": "alive", "killed": "killed"}.get(st, st)
    return f'<span class="pill st-{esc(st)}" title="Status in the claim file: {esc(st)}">{esc(word)}</span>'

def untested_badge(c: dict) -> str:
    return '<span class="pill untested">Untested: no attacks yet</span>' if not c["ledger"] else ""

def label_of(cid: str) -> str:
    return labels.get(cid, {}).get("Label") or claims[cid].get("Slug", cid).replace("-", " ").capitalize()

def src_link(d: str | None, text: str, depth: int) -> str:
    if d and d in sources:
        return f'<a href="{"../" * (depth + 1)}sources/{esc(d)}.html">{esc(text)}</a>'
    return esc(text)

def entry_source_html(e: dict, depth: int) -> str:
    lab = source_label(e)
    if lab.startswith("no named"):
        return f'<span class="muted">{esc(lab)}</span>'
    return "; ".join(src_link(resolve_source(p), p.strip(), depth) for p in lab.split(";"))

NAV = [("index.html", "Tonight"), ("claims/C0.html", "Claims"), ("weakest.html", "Where it's weakest")]

def page(path: str, title: str, body: str, desc: str = "") -> None:
    depth = path.count("/")
    rel = "../" * depth
    claim_links = " ".join(f'<a href="{rel}claims/{cid}.html">{cid}</a>' for cid in claims)
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(SITE)}</title>
<meta name="description" content="{esc(desc or 'What the nightly attacks on a few claims about learning have taught us.')}">
<link rel="stylesheet" href="{rel}assets/v2.css"></head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap bar">
<a class="brand" href="{rel}index.html"><span class="mark" aria-hidden="true"></span>{esc(SITE)} <span class="proto">prototype</span></a>
<nav aria-label="Main"><a href="{rel}index.html">Tonight</a><span class="claimnav">Claims: {claim_links}</span><a href="{rel}weakest.html">Where it's weakest</a><a class="lib" href="{rel}../index.html">Evidence library ↗</a></nav>
</div></header>
<main id="main" class="wrap">{body}</main>
<footer class="wrap foot">
<p>A prototype view of an evidence project on learning. A few plain-language claims are attacked on purpose; this site shows what survived, what had to be narrowed, and what that means in practice. There are no numeric confidence or validity scores: strength is shown only by status, bounds and the attack record (counts and dots). Practical rules are <strong>draft wording, pending Jonatan's review</strong>. All source-to-claim links are a first-pass draft, pending human review.</p>
<p>The full evidence library (sources, notes in Swedish, candidates, method) stays at <a href="{rel}../index.html">the main site</a>. Built {nice_date(TODAY)}.</p>
</footer>
<script src="{rel}assets/v2.js" defer></script>
</body></html>"""
    doc, n = PATH_RE.subn("[local path removed]", doc)
    if n:
        print(f"warning: scrubbed {n} local path(s) from {path}", file=sys.stderr)
    out = OUT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")

LEGEND = ('<p class="legend" aria-hidden="true"><span><svg width="14" height="14"><circle cx="7" cy="7" r="6" class="d-surv"/></svg> survived</span>'
          '<span><svg width="14" height="14"><circle cx="7" cy="7" r="5" class="d-narr"/><path d="M7,2 A5,5 0 0 0 7,12 Z" class="d-narr-h"/></svg> narrowed</span>'
          '<span class="muted">one dot per attack, oldest first</span></p>')

# ------------------------------------------------------------------ claim map
def claim_map(depth: int = 0) -> str:
    rel = "../" * depth
    depended = {b for a, t, b in edges if t == "depends-on"}
    W, NW, NH = 800, 224, 100
    row1 = [cid for cid in claims if cid not in depended]
    row2 = [cid for cid in claims if cid in depended]
    row1.sort(key=lambda c: (serves(claims[c])[:1] or ["Q9"], int(c[1:])))
    pos = {}
    for i, cid in enumerate(row1):
        pos[cid] = ((i + 0.5) * W / max(len(row1), 1), 200)
    for i, cid in enumerate(row2):
        deps = [pos[a][0] for a, t, b in edges if b == cid and t == "depends-on" and a in pos]
        x = sum(deps) / len(deps) if deps else (i + 0.5) * W / max(len(row2), 1)
        pos[cid] = (x, 370)
    qs = list(QUESTIONS)
    qpos = {q: ((i + 0.5) * W / len(qs), 46) for i, q in enumerate(qs)}
    H = 440
    s = [f'<div class="mapbox"><svg class="map" viewBox="0 0 {W} {H}" role="group" aria-labelledby="map-t map-d">',
         '<title id="map-t">Claim map</title>',
         '<desc id="map-d">The two guiding questions, the claims that serve them, and how the claims depend on or relate to each other. A text version follows the diagram.</desc>',
         '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>']
    for cid, c in claims.items():
        for q in serves(c):
            (x1, y1), (x2, y2) = qpos[q], pos[cid]
            s.append(f'<path d="M{x1:.0f},{y1 + 28} C{x1:.0f},{y1 + 70} {x2:.0f},{y2 - NH / 2 - 50:.0f} {x2:.0f},{y2 - NH / 2:.0f}" class="e-serve"/>')
    # incoming edge endpoints spread along the target's top edge
    incoming = defaultdict(list)
    for a, t_, b in edges:
        incoming[b].append(a)
    for b in incoming:
        incoming[b].sort(key=lambda a: pos[a][0])
    for a, t_, b in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        cls = "e-dep" if t_ == "depends-on" else "e-rel"
        k, m = incoming[b].index(a), len(incoming[b])
        ex = x2 - NW / 2 + NW * (k + 1) / (m + 1)
        ey = y2 - NH / 2 - 3
        sx, sy = x1, y1 + NH / 2
        s.append(f'<path d="M{sx:.0f},{sy:.0f} C{sx:.0f},{sy + 40:.0f} {ex:.0f},{ey - 40:.0f} {ex:.0f},{ey:.0f}" class="{cls}" marker-end="url(#arr)"/>')
        lx, ly = (sx + ex) / 2, (sy + ey) / 2
        s.append(f'<text x="{lx:.0f}" y="{ly + 4:.0f}" class="e-lab" text-anchor="middle">{esc(t_)}</text>')
    for q, (x, y) in qpos.items():
        ql = wrap_words(QUESTIONS[q], 34)
        s.append(f'<g class="qnode"><rect x="{x - 185:.0f}" y="{y - 28}" width="370" height="56" rx="18"/>'
                 + "".join(f'<text x="{x:.0f}" y="{y + 5 - 9 * (len(ql) - 1) + 18 * j:.0f}" text-anchor="middle">'
                           + (f'<tspan class="qid">{q}</tspan> ' if j == 0 else "") + f"{esc(ln)}</text>" for j, ln in enumerate(ql)) + "</g>")
    for cid, (x, y) in pos.items():
        c = claims[cid]
        st = (c.get("Status") or "").split()[0].lower()
        led = c["ledger"]
        L, T = x - NW / 2, y - NH / 2
        word = {"weakened": "narrowed"}.get(st, st)
        s.append(f'<a href="{rel}claims/{cid}.html" class="cnode st-{st}{" untested" if not led else ""}">'
                 f'<title>{esc(cid)}: {esc(label_of(cid))}. Status {esc(word)}. {esc(record_text(c))}.</title>'
                 f'<rect x="{L:.0f}" y="{T:.0f}" width="{NW}" height="{NH}" rx="12"/>'
                 f'<text x="{L + 14:.0f}" y="{T + 24:.0f}" class="cid">{cid}</text>'
                 f'<text x="{L + NW - 14:.0f}" y="{T + 24:.0f}" class="cst" text-anchor="end">{esc(word)}</text>'
                 f'<text x="{L + 14:.0f}" y="{T + 45:.0f}" class="clab">{esc(label_of(cid))}</text>')
        if led:
            s.append(dots_svg(led, r=5.5, gap=4, x0=L + 12, y0=T + 56, standalone=False))
            s.append(f'<text x="{L + 14:.0f}" y="{T + NH - 12:.0f}" class="csub">{esc(record_text(c))}</text>')
        else:
            s.append(f'<text x="{L + 14:.0f}" y="{T + 68:.0f}" class="csub untested-t">untested</text>'
                     f'<text x="{L + 14:.0f}" y="{T + NH - 12:.0f}" class="csub">no attacks yet</text>')
        s.append("</a>")
    s.append("</svg></div>")
    # text alternative
    alt = ["<details class='alt'><summary>Claim map as text</summary><ul>"]
    for q in QUESTIONS:
        cs = [cid for cid in claims if q in serves(claims[cid])]
        alt.append(f"<li><strong>{q}. {esc(QUESTIONS[q])}</strong> Served by: " + ", ".join(
            f'<a href="{rel}claims/{cid}.html">{cid} ({esc(label_of(cid))})</a>: {esc(record_text(claims[cid]))}' for cid in cs) + "</li>")
    for a, t, b in edges:
        alt.append(f"<li>{a} {esc(t)} {b}</li>")
    alt.append("</ul></details>")
    return "".join(s) + LEGEND + "".join(alt)

# ------------------------------------------------------------------ boundary diagram
def wrap_words(text: str, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines

def attr_label(cid: str, a: dict, short: bool = False) -> str:
    """Plain-text attribution."""
    if a["kind"] == "original":
        return f"In the original wording ({nice_date(a['date'])}), before any attack"
    if a["kind"] == "creation":
        return f"Written when the claim was created ({nice_date(a['date'])}); not forced by an attack" if a["date"] else "Written when the claim was created; not forced by an attack"
    if a["kind"] in ("attack", "post"):
        es = a["entries"]
        nums = " + ".join(f"#{e['n']}" for e in es)
        who = "; ".join(sorted({source_label(e) for e in es}))
        d = es[0]["date"]
        return f"Forced by attack {nums} · {who} · {nice_date(d)}"
    if a["kind"] == "unattributed":
        return f"Appeared on {nice_date(a['date'])} without a matching attack in the ledger"
    return "Origin not recorded"

def boundary(cid: str) -> tuple[str, int, int]:
    c = claims[cid]
    items = bound_items(c)
    for it in items:
        it["attr"] = attribute(cid, it)
    n = len(items)
    W, H, CX, CY, R = 1000, 620, 500, 310, 150
    core = labels.get(cid, {}).get("Core") or split_sentences(c.get("Claim", ""))[0]
    s = [f'<svg class="bound" viewBox="0 0 {W} {H}" role="img" aria-labelledby="b-t b-d">',
         f'<title id="b-t">Where {cid} holds</title>',
         f'<desc id="b-d">The core of {cid} sits inside the circle. {plural(n, "bound or carve-out", "bounds and carve-outs")} sit outside the boundary, numbered; the numbered list after the diagram gives each one in full with the attack that forced it.</desc>',
         f'<circle cx="{CX}" cy="{CY}" r="{R + 8}" class="halo"/><circle cx="{CX}" cy="{CY}" r="{R}" class="core"/>']
    lines = wrap_words(core, 26)[:8]
    ly = CY - (len(lines) - 1) * 10 - 4
    s.append(f'<text x="{CX}" y="{ly - 22}" text-anchor="middle" class="core-id">{cid} · core</text>')
    for i, ln in enumerate(lines):
        s.append(f'<text x="{CX}" y="{ly + i * 20 + 4}" text-anchor="middle" class="core-t">{esc(ln)}</text>')
    import math
    RX, RY = 262, 238
    for i, it in enumerate(items):
        ang = -math.pi / 2 + (2 * math.pi * i / max(n, 1)) + (math.pi / max(n, 1) if n % 2 == 0 else 0)
        mx, my = CX + RX * math.cos(ang), CY + RY * math.sin(ang)
        bx, by = CX + R * math.cos(ang), CY + R * math.sin(ang)
        k = it["attr"]["kind"]
        cls = "m-attack" if k in ("attack", "post") else ("m-orig" if k == "original" else "m-create")
        s.append(f'<line x1="{bx:.0f}" y1="{by:.0f}" x2="{mx:.0f}" y2="{my:.0f}" class="spoke {cls}"/>')
        s.append(f'<g class="marker {cls}"><circle cx="{mx:.0f}" cy="{my:.0f}" r="17"/>'
                 f'<text x="{mx:.0f}" y="{my + 5:.0f}" text-anchor="middle">{i + 1}</text></g>')
        right = math.cos(ang) >= 0
        tx = mx + (24 if right else -24)
        if abs(math.cos(ang)) < 0.25:
            tx = mx + (24 if right else -24)
        anchor = "start" if right else "end"
        lab = wrap_words(re.sub(r"^(Does not hold when |Does not transfer to: )", lambda m: "Not when " if m.group(1).startswith("Does not hold") else "Not: ", it["text"]), 30)
        lab = lab[:2] + (["…"] if len(lab) > 2 else [])
        if len(lab) == 3:
            lab = [lab[0], lab[1] + " …"]
        who = attr_label(cid, it["attr"]).split(" · ")
        tag = (f"#{'+#'.join(str(e['n']) for e in it['attr']['entries'])} {who[1]}" if k in ("attack", "post") and len(who) > 1
               else ("original wording" if k == "original" else ("at creation" if k == "creation" else "")))
        yy = my - 6 * (len(lab) - 1) - 2
        for j, ln in enumerate(lab):
            s.append(f'<text x="{tx:.0f}" y="{yy + j * 15:.0f}" text-anchor="{anchor}" class="m-lab">{esc(ln)}</text>')
        if tag:
            s.append(f'<text x="{tx:.0f}" y="{yy + len(lab) * 15 + 1:.0f}" text-anchor="{anchor}" class="m-tag {cls}">{esc(tag)}</text>')
    s.append("</svg>")
    lst = ['<ol class="bounds">']
    n_attr = 0
    for i, it in enumerate(items):
        a = it["attr"]; k = a["kind"]
        cls = "m-attack" if k in ("attack", "post") else ("m-orig" if k == "original" else "m-create")
        extra = ""
        if k in ("attack", "post"):
            n_attr += 1
            src_bits = "; ".join(entry_source_html(e, 1) for e in a["entries"])
            nums = " + ".join(f'<a href="#attack-{e["n"]}">#{e["n"]}</a>' for e in a["entries"])
            extra = f'<p class="attr {cls}">Forced by attack {nums} · {src_bits} · {esc(nice_date(a["entries"][0]["date"]))}</p>'
            if a.get("by_wording"):
                why = "it names that attack's source" if a["by_wording"] == "name" else "its wording echoes that attack's ledger entry"
                extra += f'<p class="muted small">This bound first appeared in a change that applied several attacks at once; it is matched to #{a["entries"][0]["n"]} because {why}.</p>'
            if k == "post":
                extra += '<p class="muted small">Added after the archived record of earlier wordings ends.</p>'
        else:
            extra = f'<p class="attr {cls}">{esc(attr_label(cid, a))}</p>'
        if a.get("earlier"):
            ea = a["earlier"]
            extra += f'<p class="muted small">Earlier form: “{inline(ea["text"])}” ({esc(attr_label(cid, ea["attr"]))}).</p>'
        det = f'<p class="muted small">{inline(it["detail"])}</p>' if it.get("detail") else ""
        lst.append(f'<li id="bound-{i + 1}"><p class="btext">{inline(it["text"])}</p>{extra}{det}</li>')
    lst.append("</ol>")
    return "".join(s) + "".join(lst), n, n_attr

# ------------------------------------------------------------------ history stepper
def fmt_time(t: datetime | None) -> str:
    return f"{nice_date(t.date())}, {t.strftime('%H:%M')} CEST" if t else ""

def stepper(cid: str) -> tuple[str, dict]:
    c = claims[cid]; h = history[cid]
    led = c["ledger"]
    stats = {"versions": 1, "text_steps": 0, "attack_steps": 0, "merged": 0}
    if not h["start"]:
        if led:
            msg = (f"The ledger records {plural(len(led), 'attack')}, but no earlier wording of {cid} is on record, so the text cannot be replayed step by step. Only the current wording is shown.")
        else:
            when = promoted.get(cid) or c.get("Last change", "")
            msg = (f"There is nothing to replay yet: {cid} has not been attacked, and only one wording exists"
                   + (f", the one it was given on {nice_date(when)}." if when else "."))
        return f'<p class="notice">{esc(msg)}</p><blockquote class="claimq">{inline(c.get("Claim", ""))}</blockquote>', stats
    start = h["start"]
    steps = h["steps"]
    items = [f'<li class="step" data-kind="start"><div class="step-h"><span class="step-n">Starting wording</span>'
             f'<span class="muted">first published {esc(fmt_time(start["time"]))}</span></div>'
             f'<blockquote class="claimq">{inline(start["claim"])}</blockquote>'
             + (f'<details><summary>Bounds at this point</summary><p>{inline(start["bounds"])}</p></details>' if start["bounds"] else '<p class="muted small">No bounds were written yet.</p>')
             + "</li>"]
    for st in steps:
        es = st["entries"]
        stats["attack_steps"] += 1
        if st["kind"] in ("changed", "merged", "post", "unattributed") and st["claim"] is not None:
            stats["versions"] += int(norm(st["claim"]) != norm(st["prev_claim"]))
        if es:
            nums = " + ".join(f"#{e['n']}" for e in es)
            vw = verdict_word(es[0])
            head = (f'<span class="step-n">Attack {nums}</span> <span class="pill v-{vw}">{vw}</span> '
                    f'<span class="muted">{" · ".join(dict.fromkeys(esc(source_label(e)) for e in es))} · ledger date {esc(nice_date(es[0]["date"]))}</span>')
        else:
            head = '<span class="step-n">Change without a matching attack</span>'
        notes = []
        if st["kind"] == "merged":
            stats["merged"] += 1
            notes.append(f"Attacks {' and '.join('#' + str(e['n']) for e in es)} were applied in the same cycle and published as one change. The record holds only their combined result, so they are shown together; no in-between wording is invented.")
        for e, t0 in st.get("relogged", []):
            notes.append(f"Attack #{e['n']} was first logged as survived ({fmt_time(t0)}) and later re-applied as narrowed; the wording changed at the re-application.")
        if st["kind"] == "post":
            notes.append("This change happened after the archived record of earlier wordings ends; any intermediate wordings were not recorded.")
        if st["kind"] == "post-unknown":
            notes.append("Logged after the archived record ends; the wording at the time of this attack is not recorded.")
        if st["kind"] == "unattributed":
            notes.append("The wording changed here, but no ledger entry is dated to this change.")
        attacks = "".join(f'<p class="atk"><span class="muted">Attack:</span> {inline(e.get("Attack", ""))}</p>' for e in es)
        if st["claim"] is None:
            body = '<p class="muted">Wording at this point: not recorded.</p>'
        else:
            dh, changed = diff_html(st["prev_claim"], st["claim"])
            bh, bchanged = diff_html(st["prev_bounds"] or "", st["bounds"] or "")
            if changed:
                stats["text_steps"] += 1
                body = f'<blockquote class="claimq diff">{dh}</blockquote>'
            else:
                body = f'<p class="unchanged">Claim wording unchanged.</p><blockquote class="claimq dim">{inline(st["claim"])}</blockquote>'
            if bchanged:
                body += f'<div class="bdiff"><p class="muted small">Bounds field after this step (changes marked):</p><p>{bh}</p></div>'
        when = f'<span class="muted small">published {esc(fmt_time(st["time"]))}</span>' if st["time"] else ""
        items.append(f'<li class="step" data-kind="{esc(st["kind"])}"><div class="step-h">{head} {when}</div>{attacks}'
                     + "".join(f'<p class="note">{esc(n)}</p>' for n in notes) + body + "</li>")
    matches = h.get("current_matches_archive", True)
    intro = (f'<p>Replay of how the wording of {cid} changed, attack by attack. Earlier wordings come from the published history of the old learning-graph site, which kept a snapshot after every change. '
             f'<ins>Added words</ins> and <del>removed words</del> are marked. Steps are in the order the verdicts took effect.</p>')
    tail = "" if matches else '<p class="notice">The current claim file differs from the last archived wording; the difference is shown as the final step.</p>'
    skipped = [e for e in led if all(e not in st["entries"] for st in steps)]
    if skipped:
        tail += f'<p class="notice">{plural(len(skipped), "ledger entry", "ledger entries")} could not be placed in the history.</p>'
    html_ = (intro + f'<div class="stepper" data-stepper><ol class="steps">{"".join(items)}</ol></div>' + tail)
    return html_, stats

# ------------------------------------------------------------------ "last night" card
def last_night(depth: int = 0) -> str:
    rel = "../" * depth
    allent = [e for c in claims.values() for e in c["ledger"] if e.get("date")]
    if not allent:
        return '<section class="card lastnight"><h2>Last night</h2><p>No attacks have been logged yet.</p></section>'
    latest = max(e["date"] for e in allent)
    ld = date.fromisoformat(latest)
    days = (TODAY - ld).days
    if days <= 1:
        title = f"Last night · {nice_date(ld)}"
    else:
        title = f"No attacks since {ld.day} {MONTHS[ld.month - 1]}"
    sub = "" if days <= 1 else f'<p class="ago">The most recent attacks were on {nice_date(ld)}, {plural(days, "day")} ago.</p>'
    parts = [f'<section class="card lastnight" aria-labelledby="ln-h"><p class="eyebrow">Last night</p><h2 id="ln-h">{esc(title)}</h2>{sub}']
    by_claim = defaultdict(list)
    for e in allent:
        if e["date"] == latest:
            by_claim[e["claim"]].append(e)
    for cid, es in by_claim.items():
        c = claims[cid]
        cnt = Counter(verdict_word(e) for e in es)
        outcome = ", ".join(f"{cnt[w]} {w}" for w in ("survived", "narrowed", "killed") if cnt[w])
        parts.append(f'<p class="ln-what"><a href="{rel}claims/{cid}.html"><strong>{cid}</strong> · {esc(label_of(cid))}</a> was attacked {plural(len(es), "time")}: {outcome}. '
                     f'Status now: {status_pill(c)}</p>{dots_svg(es)}')
        # what is known now that wasn't before
        h = history[cid]
        ns = [e["n"] for e in es]
        before = None
        if h["start"]:
            first_idx = min((h["first_seen"].get(n, 10 ** 6) for n in ns), default=None)
            snaps = h["snaps"]
            if first_idx is not None and first_idx < 10 ** 6:
                before = snaps[first_idx - 1][1] if first_idx > 0 else None
        narrowed = [e for e in es if verdict_word(e) == "narrowed"]
        new_bounds = []
        for it in bound_items(c):
            a = attribute(cid, it)
            if a["kind"] in ("attack", "post") and any(e in a["entries"] for e in es):
                new_bounds.append((it, a))
        if before and norm(before["claim"]) != norm(c.get("Claim", "")):
            pairs = diff_regions(before["claim"], c.get("Claim", ""))
            said = "; and ".join(f'“<ins>{esc(n)}</ins>” instead of “<del>{esc(o)}</del>”' if o and n else
                                 (f'“<ins>{esc(n)}</ins>” (new)' if n else f'no longer “<del>{esc(o)}</del>”') for o, n in pairs)
            sent = f'Now known: after {plural(len(narrowed), "narrowing attack")} on {nice_date(ld)}, {cid} says {said}'
            if new_bounds:
                who = "; ".join(dict.fromkeys(source_label(e) for _, a in new_bounds for e in a["entries"]))
                sent += f", and it gained {plural(len(new_bounds), 'new bound')} ({esc(who)})"
            parts.append(f'<p class="known">{sent}.</p>')
            dh, _ = diff_html(before["claim"], c.get("Claim", ""))
            parts.append(f'<details><summary>Before and after, word by word</summary><blockquote class="claimq diff">{dh}</blockquote></details>')
        elif narrowed:
            parts.append(f'<p class="known">Now known: {cid} was narrowed {plural(len(narrowed), "time")}; the ledger does not preserve the earlier wording, so the change cannot be shown word by word.</p>')
        else:
            parts.append(f'<p class="known">Now known: every attack failed to move {cid}; its wording and bounds stand as they were.</p>')
    since = [cid for cid, c in claims.items() if not c["ledger"] and (promoted.get(cid) or c.get("Last change", "")) > latest]
    if since:
        whens = sorted({promoted.get(cid) or claims[cid].get("Last change", "") for cid in since})
        parts.append(f'<p class="muted">Since then: {" and ".join(f"<a href=\"{rel}claims/{cid}.html\">{cid}</a>" for cid in since)} '
                     f'{"was" if len(since) == 1 else "were"} added on {" and ".join(nice_date(w) for w in whens)} and {"has" if len(since) == 1 else "have"} not been attacked yet.</p>')
    parts.append("</section>")
    return "".join(parts)

# ------------------------------------------------------------------ weakest
def weakness() -> list[dict]:
    rows = []
    for cid, c in claims.items():
        led = c["ledger"]
        used = {resolve_source(p) for e in led for p in source_label(e).split(";")} - {None}
        ch = [l for l in links_by_claim.get(cid, []) if l["type"] == "challenges"]
        open_ch = [l for l in ch if l["source"] not in used]
        lim = [l for l in links_by_claim.get(cid, []) if l["type"] == "limits" and l["source"] not in used]
        oq = [q.strip() for q in re.findall(r"^\s*\d+\.\s*(.+)$", open_q, re.M) if re.search(rf"\b{cid}\b", q)]
        rows.append({"cid": cid, "open": open_ch, "answered": [l for l in ch if l["source"] in used],
                     "attacks": len(led), "limits_unused": lim, "oq": oq})
    rows.sort(key=lambda r: (-len(r["open"]), r["attacks"], int(r["cid"][1:])))
    return rows

def aim_text(r: dict, depth: int) -> str:
    c = claims[r["cid"]]
    if r["open"]:
        who = ", ".join(src_link(l["source"], sources[l["source"]]["ay"], depth) for l in r["open"])
        return f"Test the open challenges first: {who}. They point against the claim and no attack has used them yet."
    if not r["attacks"]:
        return f"Never attacked. Aim straight at its kill condition: {inline(c.get('What would kill this', ''))}"
    if r["oq"]:
        return "Open question on this claim: " + " ".join(inline(q) for q in r["oq"])
    if r["limits_unused"]:
        return "Limiting sources not yet used in an attack: " + ", ".join(src_link(l["source"], sources[l["source"]]["ay"], depth) for l in r["limits_unused"])
    return "No open challenges or questions are recorded."

CSS = r'''
:root{--bg:#f7f6f2;--paper:#fff;--ink:#1e2326;--muted:#5d666d;--line:#e2dfd6;--acc:#1d5f6b;--acc2:#e7f0f1;
--surv:#1f5a63;--narr:#b0620a;--narrbg:#fbf0e1;--untested:#5b6470;--untestedbg:#eceef1;--ins:#dff0e3;--insink:#14532d;--del:#f8e0dc;--delink:#8a2a1c}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--acc);text-underline-offset:2px}a:hover{text-decoration-thickness:2px}
.skip{position:absolute;left:-999px}.skip:focus{left:1rem;top:.5rem;background:#fff;padding:.4rem .7rem;z-index:9}
.wrap{max-width:1040px;margin:0 auto;padding:0 1.1rem}
header.top{background:var(--paper);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.4rem 1.2rem;padding:.65rem 1.1rem}
.brand{font-weight:700;color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:.5rem;letter-spacing:-.01em}
.mark{width:18px;height:18px;border-radius:50%;border:3px solid var(--acc);display:inline-block;box-shadow:inset 0 0 0 3px #fff,inset 0 0 0 9px var(--acc)}
.proto{font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--narr);background:var(--narrbg);padding:.1rem .45rem;border-radius:999px}
nav{display:flex;flex-wrap:wrap;gap:.2rem 1rem;font-size:.95rem;align-items:center}nav a{text-decoration:none}nav a:hover{text-decoration:underline}
.claimnav{color:var(--muted)}.claimnav a{margin-left:.35rem}
main{padding:1.6rem 1.1rem 3rem}
h1{font-size:clamp(1.8rem,4.5vw,2.6rem);line-height:1.15;letter-spacing:-.02em;margin:.2rem 0 .8rem}
h2{font-size:1.35rem;letter-spacing:-.01em;margin:2.6rem 0 .6rem}
.eyebrow{font-size:.78rem;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:600;margin:0}
.lede{font-size:1.1rem;max-width:44rem;color:#333b40}
.muted{color:var(--muted)}.small{font-size:.88rem}
.hero .gq{list-style:none;padding:0;margin:1rem 0;display:grid;gap:.6rem;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.hero .gq li{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:.9rem 1.1rem;font-size:1.15rem;font-weight:600;line-height:1.35}
.qid{display:inline-block;font-size:.8rem;font-weight:700;color:#fff;background:var(--acc);border-radius:6px;padding:.05rem .4rem;margin-right:.35rem;vertical-align:.1em}
.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:1.1rem 1.25rem;margin:1.2rem 0}
.lastnight{border-left:5px solid var(--acc)}.lastnight h2{margin:.15rem 0 .3rem}.ago{margin:.2rem 0 .6rem;color:var(--muted)}
.known{font-size:1.05rem;background:var(--acc2);border-radius:10px;padding:.6rem .8rem}
.pill{display:inline-block;font-size:.76rem;font-weight:650;padding:.12rem .55rem;border-radius:999px;vertical-align:.12em;background:#eee;white-space:nowrap}
.st-weakened,.v-narrowed{background:var(--narrbg);color:#7a4306}.st-alive,.v-survived{background:#e1eef0;color:#174a52}.st-killed,.v-killed{background:#f8e0dc;color:#8a2a1c}
.untested{background:var(--untestedbg);color:var(--untested);border:1px dashed #9aa2ab}
.draft{background:var(--narrbg);border-radius:10px;padding:.5rem .8rem;font-size:.93rem;color:#6b3d08}
ol.rules{list-style:none;padding:0;margin:0;counter-reset:r;display:grid;gap:.9rem}
.rule{counter-increment:r;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:1rem 1.2rem 1rem 3.4rem;position:relative}
.rule::before{content:counter(r);position:absolute;left:1rem;top:1rem;width:1.7rem;height:1.7rem;border-radius:50%;background:var(--acc);color:#fff;font-weight:700;display:grid;place-items:center;font-size:.9rem}
.rule.is-untested{background:repeating-linear-gradient(135deg,#fff,#fff 12px,#f6f7f8 12px,#f6f7f8 24px);border-style:dashed}
.rule.is-untested::before{background:var(--untested)}
.rule-t{font-size:1.14rem;line-height:1.5;margin:0 0 .4rem;font-weight:500}
.rule-src{margin:.4rem 0 0;font-size:.92rem;display:flex;flex-wrap:wrap;gap:.3rem .6rem;align-items:center}
.rec{display:inline-flex;align-items:center;gap:.4rem}
details{margin:.4rem 0}summary{cursor:pointer;color:var(--acc);font-size:.93rem}
.lims ul{margin:.3rem 0 .2rem;padding-left:1.2rem;font-size:.93rem;color:#394247}
svg.dots{vertical-align:middle;overflow:visible}
.d-surv{fill:var(--surv)}.d-narr{fill:#fff;stroke:var(--narr);stroke-width:2.2}.d-narr-h{fill:var(--narr)}.d-kill{stroke:#8a2a1c;stroke-width:2.2}
.legend{display:flex;flex-wrap:wrap;gap:.3rem 1.1rem;font-size:.86rem;color:var(--muted);align-items:center}.legend span{display:inline-flex;align-items:center;gap:.35rem}
svg.map{width:100%;height:auto;background:var(--paper);border:1px solid var(--line);border-radius:14px;margin:.4rem 0}
.qnode rect{fill:var(--acc2);stroke:#bcd3d6}.qnode text{font-size:15px;font-weight:600;fill:var(--ink)}.qnode .qid{fill:var(--acc);font-weight:800}
.cnode rect{fill:#fff;stroke:#c9c4b8;stroke-width:1.4}.cnode:hover rect,.cnode:focus rect{stroke:var(--acc);stroke-width:2.4}
.cnode.untested rect{stroke-dasharray:6 4;fill:#fafbfc;stroke:#9aa2ab}
.cnode .cid{font-weight:800;font-size:16px;fill:var(--acc)}.cnode .clab{font-size:13px;font-weight:600;fill:var(--ink)}
.cnode .csub{font-size:12px;fill:var(--muted)}.cnode .untested-t{font-weight:700;fill:var(--untested);text-transform:uppercase;letter-spacing:.08em;font-size:11px}
.e-serve{stroke:#c9d9db;stroke-width:1.6;fill:none}.e-dep{stroke:var(--acc);stroke-width:2;fill:none}.e-rel{stroke:#8d969c;stroke-width:1.8;stroke-dasharray:6 5;fill:none}
.arrowhead{fill:var(--acc)}.e-lab{font-size:12px;fill:var(--muted);paint-order:stroke;stroke:#fff;stroke-width:4px}
.alt{font-size:.93rem}.mapbox{overflow-x:auto;-webkit-overflow-scrolling:touch}.mapbox svg.map{min-width:620px}.cnode .cst{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;fill:var(--muted)}.cnode.st-weakened .cst{fill:#8f4f06}
.wk-mini{padding-left:1.3rem}
.crumb{font-size:.9rem;color:var(--muted);margin:0}
.cidbig{color:var(--acc)}
.statusline{display:flex;flex-wrap:wrap;gap:.35rem .6rem;align-items:center;margin:.2rem 0 1rem}
blockquote.claimq{margin:.6rem 0;padding:.9rem 1.1rem;background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:10px;font-family:Georgia,"Iowan Old Style",serif;font-size:1.06rem;line-height:1.65}
blockquote.claimq.big{font-size:1.16rem}blockquote.claimq.dim{color:#4b5459;border-left-color:#c9c4b8}
ins{background:var(--ins);color:var(--insink);text-decoration:none;border-bottom:2px solid #5fa373;border-radius:3px;padding:0 .08em}
del{background:var(--del);color:var(--delink);text-decoration:line-through;text-decoration-thickness:1.5px;border-radius:3px;padding:0 .08em}
.stepper.hide-del del{display:none}.known del{text-decoration:none}
.rulebox{border-left:5px solid var(--narr)}.rulebox p{margin:.3rem 0}
svg.bound{width:100%;height:auto;background:var(--paper);border:1px solid var(--line);border-radius:14px;margin:.4rem 0 .8rem}
.bound .halo{fill:none;stroke:var(--acc);stroke-width:3;stroke-dasharray:2 7;stroke-linecap:round;opacity:.7}
.bound .core{fill:var(--acc2);stroke:var(--acc);stroke-width:2.5}
.core-id{font-size:13px;font-weight:700;fill:var(--acc);letter-spacing:.06em;text-transform:uppercase}.core-t{font-size:17px;fill:var(--ink);font-family:Georgia,serif}
.spoke{stroke-width:1.5;stroke:#c9c4b8}.spoke.m-attack{stroke:var(--narr)}
.marker circle{stroke-width:2.5}.marker text{font-size:15px;font-weight:800}
.marker.m-attack circle{fill:var(--narr);stroke:var(--narr)}.marker.m-attack text{fill:#fff}
.marker.m-orig circle{fill:#fff;stroke:#7d868c}.marker.m-orig text{fill:#4b5459}
.marker.m-create circle{fill:#fff;stroke:#7d868c;stroke-dasharray:4 3}.marker.m-create text{fill:#4b5459}
.m-lab{font-size:13.5px;fill:var(--ink)}.m-tag{font-size:12px;font-weight:700;fill:#7d868c}.m-tag.m-attack{fill:#8f4f06}
.lg{display:inline-flex;align-items:center;gap:.35rem}.lg::before{content:"";width:14px;height:14px;border-radius:50%;display:inline-block;border:2.5px solid #7d868c;background:#fff}
.lg.m-attack::before{background:var(--narr);border-color:var(--narr)}.lg.m-create::before{border-style:dashed}
ol.bounds{padding-left:1.6rem;display:grid;gap:.5rem;margin:.4rem 0}
ol.bounds li{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:.55rem .85rem}
ol.bounds li:target{outline:3px solid var(--narr)}
.btext{margin:0}.attr{margin:.25rem 0 0;font-size:.9rem;font-weight:600;color:#5d666d}.attr.m-attack{color:#8f4f06}
.summary{background:var(--acc2);border-radius:10px;padding:.55rem .85rem}
.notice{background:var(--untestedbg);border:1px dashed #9aa2ab;border-radius:10px;padding:.6rem .85rem}
.stepctl{display:flex;flex-wrap:wrap;gap:.5rem .8rem;align-items:center;background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:.7rem .9rem;margin:.6rem 0;position:sticky;top:3.4rem;z-index:3}
.stepctl button{font:inherit;font-size:.93rem;border:1px solid var(--acc);background:#fff;color:var(--acc);border-radius:8px;padding:.3rem .8rem;cursor:pointer}
.stepctl button:disabled{opacity:.4;cursor:default}.stepctl button:focus-visible,.stepctl input:focus-visible{outline:3px solid #f0b35a;outline-offset:2px}
.stepctl .rangebox{flex:1 1 220px;display:flex;flex-direction:column;gap:.15rem}
.stepctl input[type=range]{width:100%;accent-color:var(--acc)}
.ticks{display:flex;justify-content:space-between;padding:0 7px}.ticks span{width:9px;height:9px;border-radius:50%;background:#d5d1c6}
.ticks span.t-changed,.ticks span.t-merged,.ticks span.t-post{background:var(--narr)}.ticks span.t-unchanged{background:var(--surv)}.ticks span.t-start{background:#8d969c}
.ticks span.on{outline:2px solid var(--ink);outline-offset:2px}
.pos{font-size:.9rem;color:var(--muted);min-width:7.5rem}
.stepctl label{font-size:.88rem;color:var(--muted);display:inline-flex;gap:.3rem;align-items:center}
ol.steps{list-style:none;padding:0;margin:0;display:grid;gap:.9rem}
.step{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:.8rem 1rem}
.js .stepper .step{display:none}.js .stepper .step.cur{display:block}.js .stepper.all .step{display:block}
.step-h{display:flex;flex-wrap:wrap;gap:.3rem .6rem;align-items:center}.step-n{font-weight:750}
.atk{margin:.4rem 0;font-size:.95rem}.note{font-size:.9rem;background:var(--narrbg);border-radius:8px;padding:.4rem .65rem;color:#6b3d08}
.unchanged{font-weight:600;color:var(--surv);margin:.5rem 0 .2rem}
.bdiff{font-size:.93rem;border-top:1px dashed var(--line);margin-top:.5rem}
ol.attacks{list-style:none;padding:0;display:grid;gap:.6rem}
.atk-card{background:var(--paper);border:1px solid var(--line);border-left:5px solid var(--surv);border-radius:10px;padding:.6rem .9rem}
.atk-card.v-narrowed{border-left-color:var(--narr);background:#fff}.atk-card p{margin:.35rem 0}
.atk-card:target{outline:3px solid var(--narr)}
ol.weak{list-style:none;padding:0}.wk-h{display:flex;flex-wrap:wrap;gap:.4rem .6rem;align-items:center;font-size:1.1rem}
.rank{width:2rem;height:2rem;border-radius:50%;background:var(--ink);color:#fff;display:grid;place-items:center;font-weight:700}
.wk-counts{display:flex;flex-wrap:wrap;gap:.4rem 1.4rem;color:#394247}.wk-counts span{display:inline-flex;gap:.35rem;align-items:center}
.aim{background:var(--acc2);border-radius:10px;padding:.55rem .8rem}
.libcard{background:#fbfaf6}
footer.foot{border-top:1px solid var(--line);color:var(--muted);font-size:.87rem;padding:1.2rem 1.1rem 2rem}
@media (max-width:640px){body{font-size:16px}.rule{padding-left:3rem}.stepctl{top:0;position:static}header.top{position:static}.claimnav{display:none}}
@media (prefers-reduced-motion:no-preference){.step.cur{animation:fade .25s ease}}@keyframes fade{from{opacity:.3}to{opacity:1}}
'''

JS = r'''
document.documentElement.classList.add('js');
document.querySelectorAll('[data-stepper]').forEach(function (box) {
  var steps = Array.prototype.slice.call(box.querySelectorAll('.step'));
  if (steps.length < 2) return;
  var n = steps.length, i = 0;
  var ctl = document.createElement('div');
  ctl.className = 'stepctl';
  ctl.setAttribute('role', 'group');
  ctl.setAttribute('aria-label', 'Replay the wording, step by step');
  ctl.innerHTML = '<button type="button" data-a="prev">← Previous</button>' +
    '<div class="rangebox"><input type="range" min="0" max="' + (n - 1) + '" value="0" aria-label="Step"><div class="ticks" aria-hidden="true"></div></div>' +
    '<button type="button" data-a="next">Next →</button><span class="pos" aria-live="polite"></span>' +
    '<label><input type="checkbox" data-a="del" checked> show removed words</label>' +
    '<label><input type="checkbox" data-a="all"> show all steps</label>';
  box.insertBefore(ctl, box.firstChild);
  var range = ctl.querySelector('input[type=range]'), pos = ctl.querySelector('.pos'), ticks = ctl.querySelector('.ticks');
  steps.forEach(function (s) { var t = document.createElement('span'); t.className = 't-' + (s.getAttribute('data-kind') || ''); ticks.appendChild(t); });
  var tk = ticks.children;
  function show(k) {
    i = Math.max(0, Math.min(n - 1, k));
    steps.forEach(function (s, j) { s.classList.toggle('cur', j === i); tk[j].classList.toggle('on', j === i); });
    range.value = i;
    pos.textContent = (i === 0 ? 'Start' : 'Step ' + i + ' of ' + (n - 1));
    ctl.querySelector('[data-a=prev]').disabled = i === 0;
    ctl.querySelector('[data-a=next]').disabled = i === n - 1;
  }
  ctl.addEventListener('click', function (ev) {
    var a = ev.target.getAttribute('data-a');
    if (a === 'prev') show(i - 1); else if (a === 'next') show(i + 1);
  });
  range.addEventListener('input', function () { show(parseInt(range.value, 10)); });
  ctl.querySelector('[data-a=del]').addEventListener('change', function (ev) { box.classList.toggle('hide-del', !ev.target.checked); });
  ctl.querySelector('[data-a=all]').addEventListener('change', function (ev) { box.classList.toggle('all', ev.target.checked); });
  show(0);
});
'''

# ------------------------------------------------------------------ build
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "assets").mkdir(parents=True)
(OUT / "assets" / "v2.css").write_text(CSS, encoding="utf-8")
(OUT / "assets" / "v2.js").write_text(JS, encoding="utf-8")

# ---- home
body = ['<section class="hero"><p class="eyebrow">Optimal learning in a world full of AI</p>',
        '<h1>What we know tonight</h1>',
        '<ol class="gq">' + "".join(f'<li><span class="qid">{q}</span> {esc(t)}</li>' for q, t in QUESTIONS.items()) + '</ol>',
        '<p class="lede">A few plain claims about learning are attacked on purpose with counter-evidence. What survives, and what had to be narrowed, becomes the rules below. No rule says more than its claim does tonight.</p></section>']
body.append(last_night(0))
body.append(f'<section aria-labelledby="rules-h"><h2 id="rules-h">Rules for learners and teachers</h2>'
            f'<p class="draft">{esc(rules_status or "draft wording, pending Jonatan’s review")}. Each rule comes from one claim and is no stronger than its current wording and bounds.</p><ol class="rules">')
for r in rules:
    c = claims[r["Claim"]]
    lims = [x.strip() for x in r.get("Limits", "").split("|") if x.strip()]
    body.append(f'<li class="rule{" is-untested" if not c["ledger"] else ""}">'
                f'<p class="rule-t">{inline(r["Rule"])}</p>'
                + (f'<details class="lims"><summary>Only within these limits ({len(lims)})</summary><ul>' + "".join(f"<li>{inline(x)}</li>" for x in lims) + "</ul></details>" if lims else "")
                + f'<p class="rule-src"><a href="claims/{c["id"]}.html">From {c["id"]}: {esc(label_of(c["id"]))}</a> {status_pill(c)} {untested_badge(c)}'
                + (f' <span class="rec">{dots_svg(c["ledger"])} <span class="muted small">{esc(record_text(c))}</span></span>' if c["ledger"] else "")
                + "</p></li>")
body.append("</ol></section>")
body.append(f'<section aria-labelledby="map-h"><h2 id="map-h">Claim map</h2><p class="muted">Questions at the top, claims below. Arrows show that one claim depends on or relates to another. Each claim shows its attacks as dots, oldest first.</p>{claim_map(0)}</section>')
wk = weakness()
body.append('<section aria-labelledby="wk-h"><h2 id="wk-h">Where it\'s weakest</h2><ol class="wk-mini">' + "".join(
    f'<li><a href="claims/{r["cid"]}.html"><strong>{r["cid"]}</strong> {esc(label_of(r["cid"]))}</a>: '
    f'{plural(len(r["open"]), "open challenge")}, {plural(r["attacks"], "attack")}</li>' for r in wk)
    + '</ol><p><a href="weakest.html">Where the next attack should aim →</a></p></section>')
body.append('<section class="card libcard"><h2>Evidence library</h2><p>The sources behind these claims, with their Swedish notes, the candidate claims and the method, are in the <a href="../index.html">evidence library</a> on the main site.</p></section>')
page("index.html", "What we know tonight", "".join(body))

# ---- claim pages
report = {}
for cid, c in claims.items():
    led = c["ledger"]
    b = [f'<p class="crumb"><a href="../index.html">Tonight</a> · {cid}</p>',
         f'<h1><span class="cidbig">{cid}</span> {esc(label_of(cid))}</h1>',
         f'<p class="statusline">{status_pill(c)} {untested_badge(c)} '
         + (f'{dots_svg(led)} <span class="muted">{esc(record_text(c))}</span>' if led else "")
         + f' <span class="muted">· serves {", ".join(serves(c))} · last change {esc(nice_date(c["Last change"])) if c.get("Last change") else "not recorded"}</span></p>',
         f'<blockquote class="claimq big">{inline(c.get("Claim", ""))}</blockquote>']
    rel_rules = [r for r in rules if r["Claim"] == cid]
    if rel_rules:
        b.append('<div class="card rulebox"><p class="eyebrow">In practice (draft)</p>' + "".join(f'<p>{inline(r["Rule"])}</p>' for r in rel_rules) + "</div>")
    bd, nb, na = boundary(cid)
    b.append(f'<section aria-labelledby="wh-h"><h2 id="wh-h">Where it holds</h2><p class="muted">Inside the circle: the core of the claim. Outside: every bound and carve-out in the claim file, numbered, with the attack that forced it. '
             '</p>'
             f'<p class="legend"><span class="lg m-attack">forced by a narrowing attack</span><span class="lg m-orig">in the original wording</span><span class="lg m-create">written at creation</span></p>{bd}')
    surv = [e for e in led if verdict_word(e) == "survived"]
    b.append(f'<p class="summary"><strong>{na} of {nb}</strong> bounds and carve-outs were forced by a specific attack.'
             + (f' {plural(len(surv), "attack")} hit the boundary and did not move it: ' + ", ".join(f'<a href="#attack-{e["n"]}">#{e["n"]}</a>' for e in surv) + "." if surv else "")
             + "</p></section>")
    sh, stats = stepper(cid)
    b.append(f'<section aria-labelledby="hc-h"><h2 id="hc-h">How it changed</h2>{sh}</section>')
    # attack list
    b.append(f'<section aria-labelledby="ar-h"><h2 id="ar-h">Attack record</h2>')
    if led:
        b.append(LEGEND + '<ol class="attacks">')
        for e in led:
            vw = verdict_word(e)
            b.append(f'<li id="attack-{e["n"]}" class="atk-card v-{vw}"><div class="atk-h"><span class="step-n">#{e["n"]}</span> <span class="pill v-{vw}">{vw}</span> '
                     f'<span class="muted">{esc(nice_date(e["date"]))} · {entry_source_html(e, 1)} · target: {esc(e.get("Target", ""))}</span></div>'
                     f'<p>{inline(e.get("Attack", ""))}</p><details><summary>Strongest reading and verdict reasoning</summary>'
                     f'<p><strong>Steelmans to:</strong> {inline(e.get("Steelmans to", ""))}</p><p><strong>Why:</strong> {inline(e.get("Why", ""))}</p></details></li>')
        b.append("</ol>")
    else:
        b.append('<p class="notice">No attacks yet. This claim is untested: its wording has not been exposed to counter-evidence in this project.</p>')
        b.append(f'<p><strong>What would kill it:</strong> {inline(c.get("What would kill this", ""))}</p>')
    b.append("</section>")
    ls = links_by_claim.get(cid, [])
    cnt = Counter(l["type"] for l in ls)
    b.append(f'<section aria-labelledby="ev-h"><h2 id="ev-h">Evidence</h2><p>{plural(len({l["source"] for l in ls}), "linked source")}: '
             + ", ".join(f'{cnt[t]} {t}' for t in ("supports", "limits", "challenges") if cnt[t])
             + f' (first-pass draft, pending human review). ' + " · ".join(
                 f'{t}: ' + ", ".join(src_link(l["source"], sources[l["source"]]["ay"], 1) for l in ls if l["type"] == t)
                 for t in ("supports", "limits", "challenges") if cnt[t])
             + f'</p><p><a href="../../claims/{cid}.html">Full claim record in the evidence library →</a></p></section>')
    page(f"claims/{cid}.html", f"{cid}: {label_of(cid)}", "".join(b))
    report[cid] = {"bounds": nb, "attributed": na, **stats}

# ---- weakest
b = ['<p class="crumb"><a href="index.html">Tonight</a> · Where it\'s weakest</p><h1>Where it\'s weakest</h1>',
     '<p class="lede">Claims ranked by how exposed they are: first by open challenges (sources linked as pointing against the claim that no attack has used yet), then by fewest attacks. The top of the list is where the next attack should aim.</p><ol class="weak">']
for i, r in enumerate(wk, 1):
    c = claims[r["cid"]]
    b.append(f'<li class="card"><div class="wk-h"><span class="rank">{i}</span> <a href="claims/{r["cid"]}.html"><strong>{r["cid"]}</strong> {esc(label_of(r["cid"]))}</a> {status_pill(c)} {untested_badge(c)}</div>'
             f'<p class="wk-counts"><span><strong>{len(r["open"])}</strong> open {"challenge" if len(r["open"]) == 1 else "challenges"}</span>'
             f'<span><strong>{r["attacks"]}</strong> {"attack" if r["attacks"] == 1 else "attacks"} {dots_svg(c["ledger"])}</span>'
             f'<span><strong>{len(r["limits_unused"])}</strong> limiting {"source" if len(r["limits_unused"]) == 1 else "sources"} not yet used in an attack</span></p>'
             f'<p class="aim"><strong>Aim next:</strong> {aim_text(r, 0)}</p>')
    if r["open"]:
        b.append('<details><summary>Why these count as challenges</summary><ul>' + "".join(
            f'<li>{src_link(l["source"], sources[l["source"]]["ay"], 0)}: {inline(l["basis"])}</li>' for l in r["open"]) + "</ul></details>")
    b.append("</li>")
b.append('</ol><p class="muted">Challenge links are a first-pass draft, pending human review. A challenge counts as answered when its source has been used in an attack on that claim.</p>')
page("weakest.html", "Where it's weakest", "".join(b))

print(f"built {sum(1 for _ in OUT.rglob('*.html'))} pages into docs/v2/")
for cid, r in report.items():
    print(cid, r)
