#!/usr/bin/env python3
"""Build the static site for the merged learning project into docs/.

Input: the project folder (default below, override with LEARNING_ROOT).
Output: docs/ (GitHub Pages, main:/docs). Never publishes local filesystem paths.
"""
from __future__ import annotations
import csv, html, os, re, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path
import markdown

ROOT = Path(os.environ.get("LEARNING_ROOT", "/home/box/learning"))
OUT = Path(__file__).resolve().parent / "docs"
SITE = "Learning: claims under fire"

AGES = {
    "foralder-tidig-barndom": "Early childhood / preschool",
    "grundskola-lag": "Primary school (grades 1–6)",
    "grundskola-hog": "Lower secondary (grades 7–9)",
    "gymnasium": "Upper secondary",
    "vuxen-livslangt": "Adults / lifelong learning",
    "overgripande": "Across ages",
}
THEMES = {
    "ai-och-larande": "AI and learning",
    "analogt-vs-digitalt": "Analog vs digital",
    "explicit-undervisning-kunskap": "Explicit teaching and knowledge building",
    "feedback-bedomning": "Feedback and assessment",
    "lasning-och-skrivande": "Reading and writing",
    "optimalt-larande-grunder": "Foundations of optimal learning",
    "papper-vs-skarm": "Paper vs screen",
    "penna-vs-tangentbord": "Pen vs keyboard",
    "uppmarksamhet-och-minne": "Attention and memory",
}
QUESTIONS = {
    "Q1": "What is optimal learning?",
    "Q2": "How do we achieve it when AI and screens are everywhere?",
}
LINK_TYPES = ["supports", "limits", "challenges"]
VERDICT_WORD = {"survived": "survived", "weakened": "narrowed", "killed": "killed"}
CLAIM_FIELD_ORDER = ["Claim", "Status", "Last change", "Serves", "Ages", "Depends on", "Depended on by", "Relates to",
                     "Bounds", "Contradicts", "Special-case-of", "Does-not-transfer-to", "What would kill this",
                     "Tutor consequence"]
PATH_RE = re.compile(r"(/home/box|/workspace)[^\s<>\"')]*")

# ---------------------------------------------------------------- helpers
def esc(s: str) -> str:
    return html.escape(s or "", quote=True)

def scrub(s: str) -> str:
    return PATH_RE.sub("[local path removed]", s)

def inline(s: str) -> str:
    """Escape, then render **bold** and *em* and `code`."""
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s

MD = markdown.Markdown(extensions=["tables", "sane_lists"])
def md(text: str) -> str:
    MD.reset()
    return MD.convert(text)

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def status_pill(status: str) -> str:
    key = status.split()[0].lower() if status else "unknown"
    return f'<span class="pill st-{esc(key)}">{esc(status)}</span>'

# ---------------------------------------------------------------- load data
def parse_fields(text: str) -> dict:
    fields, cid = {}, None
    for line in text.splitlines():
        if re.fullmatch(r"[CK]\d+", line.strip()):
            fields["id"] = line.strip(); continue
        if line.startswith("Sources allowed"):
            continue  # deliberately omitted from public cards
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields

def parse_ledger(text: str) -> list[dict]:
    entries, cur = [], None
    for ln in text.splitlines():
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ln.strip()):
            cur = {"date": ln.strip()}; entries.append(cur); continue
        if cur is not None and ":" in ln:
            k, _, v = ln.partition(":"); cur[k.strip()] = v.strip()
    return entries

def parse_meta(text: str) -> dict:
    m = {}
    for ln in text.splitlines():
        if ln.startswith("#") or ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        bold_key = k.strip().startswith("**")
        k, v = k.strip().strip("*").strip(), v.strip()
        if bold_key and v.startswith("**"):
            v = v[2:].strip()
        m.setdefault(k, v)
    return m

claims = {}
for p in sorted((ROOT / "claims").glob("C*.md")):
    f = parse_fields(read(p)); f["file"] = p.stem
    led = ROOT / "ledgers" / p.name
    f["ledger"] = parse_ledger(read(led)) if led.exists() else []
    claims[f["id"]] = f
cands = {}
for p in sorted((ROOT / "candidates").glob("K*.md")):
    f = parse_fields(read(p)); cands[f["id"]] = f

sources = {}
with open(ROOT / "sources.tsv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh, delimiter="\t"):
        d = r["dir"]; folder = ROOT / "sources" / d
        r["meta"] = parse_meta(read(folder / "METADATA.md"))
        r["note"] = read(folder / "NOTE.md") if (folder / "NOTE.md").exists() else ""
        r["files"] = sorted(x.name for x in folder.iterdir() if x.name not in ("NOTE.md", "LINKS.md", "METADATA.md"))
        r["ages"] = [a for a in r["ages"].split(";") if a]
        r["themes"] = [t for t in r["themes"].split(";") if t]
        sources[d] = r
id2dir = {s["id"]: d for d, s in sources.items() if s["id"]}

links = []
with open(ROOT / "links.tsv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh, delimiter="\t"):
        links.append(r)
links_by_claim = defaultdict(list); links_by_source = defaultdict(list)
for l in links:
    links_by_claim[l["claim"]].append(l); links_by_source[l["source"]].append(l)
draft_count = sum(1 for l in links if "draft" in l["review"])

brief_text = read(ROOT / "brief.md")
open_q = read(ROOT / "open-questions.md")
unlinked = sorted(d for d in sources if d not in links_by_source)

# ---------------------------------------------------------------- page shell
NAV = [("index.html", "Home"), ("candidates.html", "Candidates"), ("sources/index.html", "Sources"),
       ("ages/index.html", "Ages"), ("themes/index.html", "Themes"), ("direction/index.html", "Direction"),
       ("method.html", "Method"), ("inbox.html", "Inbox"), ("about.html", "About")]

def page(path: str, title: str, body: str) -> None:
    depth = path.count("/")
    rel = "../" * depth
    nav = " ".join(f'<a href="{rel}{h}">{esc(t)}</a>' for h, t in NAV)
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(SITE)}</title><link rel="stylesheet" href="{rel}assets/style.css"></head>
<body><header><div class="wrap"><a class="brand" href="{rel}index.html">{esc(SITE)}</a><nav>{nav}</nav></div></header>
<main class="wrap">{body}</main>
<footer><div class="wrap">Built from the merged Kunskapsbank and learning graph. No numeric confidence scores: strength is shown only by status, bounds and the attack record. Source notes are in Swedish and shown verbatim. All source-to-claim links are a first-pass draft pending human review.</div></footer>
</body></html>"""
    doc = scrub(doc)
    out = OUT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")

def R(depth: int) -> str:
    return "../" * depth

def link_ids(h: str, depth: int) -> str:
    """Turn <code>AI-003</code> style ids into links to source pages."""
    def rep(m):
        i = m.group(1)
        return f'<a href="{R(depth)}sources/{id2dir[i]}.html"><code>{i}</code></a>' if i in id2dir else m.group(0)
    return re.sub(r"<code>([A-Z]{2,6}-\d{3})</code>", rep, h)

def target_href(t: str, depth: int) -> str:
    if t.startswith("C"):
        return f'{R(depth)}claims/{t}.html'
    return f'{R(depth)}candidates.html#{t}'

def target_label(t: str) -> str:
    return t if t.startswith("C") else f"{t} (candidate)"

def attack_summary(c: dict) -> str:
    led = c["ledger"]
    if not led:
        return "No attacks yet"
    cnt = Counter(VERDICT_WORD.get(e.get("Verdict", "").split()[0] if e.get("Verdict") else "", e.get("Verdict", "")) for e in led)
    parts = [f"{cnt[w]} {w}" for w in ("survived", "narrowed", "killed") if cnt[w]]
    return f"{len(led)} attack{'s' if len(led) != 1 else ''}: " + ", ".join(parts)

def link_summary(ls: list) -> str:
    if not ls:
        return "No linked sources yet"
    srcs = {l["source"] for l in ls}
    c = Counter(l["type"] for l in ls)
    return f"{len(srcs)} linked source{'s' if len(srcs) != 1 else ''} ({', '.join(f'{c[t]} {t}' for t in LINK_TYPES if c[t])})"

def src_title(d: str) -> str:
    s = sources[d]
    t = s["title"] or d
    return f"{s['id'] + ' · ' if s['id'] else ''}{t}{' (' + s['year'] + ')' if s['year'] else ''}"

def src_link(d: str, depth: int) -> str:
    return f'<a href="{R(depth)}sources/{d}.html">{inline(src_title(d))}</a>'

def chips(items, kind, depth):
    lab = AGES if kind == "ages" else THEMES
    return " ".join(f'<a class="chip" href="{R(depth)}{kind}/{i}.html">{esc(lab.get(i, i))}</a>' for i in items)

def links_table(ls: list, depth: int, by: str) -> str:
    """by='claim' → rows show source; by='source' → rows show claim."""
    if not ls:
        return "<p class='muted'>None.</p>"
    out = []
    for t in LINK_TYPES:
        rows = [l for l in ls if l["type"] == t]
        if not rows:
            continue
        out.append(f'<h3 class="lt lt-{t}">{t.capitalize()} ({len(rows)})</h3><table><tr><th>{"Source" if by == "claim" else "Claim"}</th><th>Basis</th></tr>')
        for l in sorted(rows, key=lambda x: x["source"] if by == "claim" else x["claim"]):
            first = src_link(l["source"], depth) if by == "claim" else f'<a href="{target_href(l["claim"], depth)}">{esc(target_label(l["claim"]))}</a>'
            out.append(f"<tr><td>{first}</td><td>{inline(l['basis'])}</td></tr>")
        out.append("</table>")
    out.append('<p class="muted">Review state: first-pass draft, pending human review.</p>')
    return "".join(out)

def claim_card(c: dict, depth: int, full: bool = False) -> str:
    cid = c["id"]
    h = [f'<article class="card claim" id="{cid}"><h3><a href="{R(depth)}claims/{cid}.html">{cid}</a> {status_pill(c.get("Status", ""))}</h3>',
         f'<p class="claimtext">{inline(c.get("Claim", ""))}</p>',
         f'<p class="meta"><strong>Serves:</strong> {inline(c.get("Serves", ""))}<br><strong>Ages:</strong> {inline(c.get("Ages", ""))}</p>']
    if c.get("Bounds"):
        h.append(f'<p><strong>Bounds:</strong> {inline(c["Bounds"])}</p>')
    h.append(f'<p class="counts"><strong>Attack record:</strong> {attack_summary(c)} · <strong>Evidence links:</strong> {link_summary(links_by_claim.get(cid, []))}</p>')
    h.append("</article>")
    return "".join(h)

# ---------------------------------------------------------------- build
if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "assets").mkdir(parents=True)
shutil.copy2(Path(__file__).resolve().parent / "static" / "style.css", OUT / "assets" / "style.css")
(OUT / ".nojekyll").write_text("")

# home
edges = []
for cid, c in claims.items():
    for fld in ("Depends on", "Relates to"):
        v = c.get(fld, "")
        m = re.match(r"(C\d+) (depends-on|relates-to) (C\d+)", v)
        if m and m.group(1) == cid:
            edges.append(m.groups())
body = [f'<section class="hero"><h1>{esc(SITE)}</h1><p>One project that merges a Swedish evidence library on learning (the Kunskapsbank) with a small set of claims that are deliberately attacked (the learning graph). Everything serves two questions:</p>',
        '<ol class="questions">' + "".join(f'<li><strong>{q}. {esc(t)}</strong></li>' for q, t in QUESTIONS.items()) + '</ol>',
        '<p class="muted">Q1 covers cognition, age and maturity, and teaching, whatever the medium. Q2 covers Swedish school in practice.</p></section>']
for q in QUESTIONS:
    cs = [c for c in claims.values() if c.get("Serves", "").startswith(q) or ("+" in c.get("Serves", "") and q in c.get("Serves", ""))]
    body.append(f'<h2>Claims serving {q}</h2>' + ("".join(claim_card(c, 0) for c in cs) or "<p class='muted'>None yet.</p>"))
body.append("<h2>How the claims connect</h2><ul>" + "".join(
    f'<li><a href="claims/{a}.html">{a}</a> {esc(t)} <a href="claims/{b}.html">{b}</a></li>' for a, t, b in edges) + "</ul>")
body.append(f"""<h2>What else is here</h2><ul>
<li><a href="candidates.html">{len(cands)} candidate claims</a> drawn from the Kunskapsbank, <strong>not approved</strong>.</li>
<li><a href="sources/index.html">{len(sources)} sources</a> with {len(links)} source-to-claim links ({draft_count} still a first-pass draft pending human review).</li>
<li>Views by <a href="ages/index.html">age group</a> and by <a href="themes/index.html">theme</a>, generated from claims, links and sources.</li>
<li><a href="direction/index.html">Direction</a>: the Kunskapsbank's position, practice and counterargument texts (Swedish).</li>
<li><a href="inbox.html">Inbox</a>: {len(unlinked)} sources not yet tied to any claim or candidate.</li></ul>""")
body.append(f'<h2>Open questions</h2><div class="prose">{md(open_q.split(chr(10), 1)[1] if open_q.startswith("#") else open_q)}</div>')
page("index.html", "Home", "".join(body))

# claim pages
for cid, c in claims.items():
    b = [f'<p class="crumb"><a href="../index.html">Home</a> · {cid}</p><h1>{cid} {status_pill(c.get("Status", ""))}</h1>',
         f'<p class="claimtext big">{inline(c.get("Claim", ""))}</p><dl class="fields">']
    for k in CLAIM_FIELD_ORDER[1:]:
        v = c.get(k, "")
        if v:
            b.append(f"<dt>{esc(k)}</dt><dd>{inline(v)}</dd>")
    b.append("</dl>")
    b.append(f"<h2>Attack record</h2><p class='counts'>{attack_summary(c)}</p>")
    if c["ledger"]:
        for e in c["ledger"]:
            v = e.get("Verdict", ""); vw = VERDICT_WORD.get(v.split()[0], v) if v else ""
            b.append(f'<article class="card ledger"><h3>{esc(e["date"])} <span class="pill v-{esc(vw)}">{esc(vw)}</span></h3><dl class="fields">')
            for k in ("Attack", "Target", "Source", "Steelmans to", "Why", "Rewrite"):
                if e.get(k):
                    b.append(f"<dt>{esc(k)}</dt><dd>{inline(e[k])}</dd>")
            b.append("</dl></article>")
    else:
        b.append("<p class='muted'>The ledger is empty. The claim was promoted on its first day and has not been attacked yet.</p>")
    b.append(f"<h2>Linked sources</h2><p>{link_summary(links_by_claim.get(cid, []))}</p>{links_table(links_by_claim.get(cid, []), 1, 'claim')}")
    page(f"claims/{cid}.html", cid, "".join(b))

# candidates
b = ['<h1>Candidate claims</h1><p><strong>Not approved.</strong> Each candidate is built from one "This claim dies if …" sentence shared by one or more Kunskapsbank notes. The kill sentence is quoted in Swedish, verbatim; the claim sentence and English kill condition are first drafts. Candidates have no ledger and are not in the brief. Only Jonatan promotes a candidate. K01 and K12 were promoted on 2026-09-25 as <a href="claims/C3.html">C3</a> and <a href="claims/C2.html">C2</a>.</p>']
for kid, k in cands.items():
    srcs = [l for l in links_by_claim.get(kid, [])]
    b.append(f'<article class="card cand" id="{kid}"><h3>{kid} <span class="pill st-candidate">candidate: not approved</span></h3>'
             f'<p class="claimtext">{inline(k.get("Claim", ""))}</p>'
             f'<p class="meta"><strong>Serves:</strong> {esc(k.get("Serves", ""))} · <strong>Ages:</strong> {esc(k.get("Ages", ""))}</p>'
             f'<p><strong>What would kill this:</strong> {inline(k.get("What would kill this", ""))}</p>'
             f'<p><strong>Kill sentence in the bank (Swedish):</strong> <span lang="sv">{inline(k.get("Kill sentence in the bank (Swedish, verbatim)", ""))}</span></p>'
             f'<p><strong>Overlap:</strong> {inline(k.get("Overlap", ""))}</p>'
             f'<details><summary>{link_summary(srcs)}</summary>{links_table(srcs, 0, "claim")}</details></article>')
page("candidates.html", "Candidates", "".join(b))

# sources
def source_row(d, depth):
    s = sources[d]
    ls = links_by_source.get(d, [])
    tl = ", ".join(f'<a href="{target_href(l["claim"], depth)}">{esc(l["claim"])}</a>&nbsp;{esc(l["type"])}' for l in sorted(ls, key=lambda x: (x["claim"], x["type"]))) or "<span class='muted'>unlinked</span>"
    return f"<tr><td>{src_link(d, depth)}</td><td>{esc(s['tier'])}</td><td>{tl}</td></tr>"

b = [f'<h1>Sources</h1><p>{len(sources)} sources. {sum(1 for s in sources.values() if s["note"])} have a note. Original files (PDFs, abstracts) are kept in the project archive and are not published here; use the DOI or URL on each page.</p>',
     "<table><tr><th>Source</th><th>Tier</th><th>Links</th></tr>" + "".join(source_row(d, 1) for d in sorted(sources, key=lambda d: (sources[d]["id"] or "ZZZ", d))) + "</table>"]
page("sources/index.html", "Sources", "".join(b))

for d, s in sources.items():
    m = s["meta"]
    origin = s["origin"]
    flag = ""
    if "recovered" in origin:
        flag = '<p class="flag">Recovered from the published Kunskapsbank site on 2026-09-25. Original files lost. The note below was converted from the published page.</p>'
    elif "ledger" in origin:
        flag = '<p class="flag">From the learning-graph ledger. Metadata only (citation and DOI); no note or abstract is held.</p>'
    elif "local only" in origin:
        flag = '<p class="flag soft">Added to the Kunskapsbank on 2026-09-07 but not on the old published site.</p>'
    doi = m.get("Källa/DOI", "")
    doi_html = f'<a href="{esc(doi)}" rel="noopener">{esc(doi)}</a>' if doi.startswith("http") else esc(doi)
    b = [f'<p class="crumb"><a href="../index.html">Home</a> · <a href="index.html">Sources</a> · {esc(s["id"] or d)}</p>',
         f'<h1>{inline(s["title"] or d)}</h1>{flag}',
         f'<p class="meta"><strong>Authors:</strong> {esc(m.get("Författare", ""))} · <strong>Year:</strong> {inline(s["year"])} · <strong>Tier:</strong> {esc(s["tier"] or "not assigned")} · <strong>DOI/URL:</strong> {doi_html}</p>']
    if s["ages"] or s["themes"]:
        b.append(f'<p>{chips(s["ages"], "ages", 1)} {chips(s["themes"], "themes", 1)}</p>')
    b.append(f"<h2>Links to claims</h2>{links_table(links_by_source.get(d, []), 1, 'source')}")
    if s["note"]:
        b.append(f'<h2>Source note (Swedish, verbatim from the Kunskapsbank)</h2><div class="prose note" lang="sv">{link_ids(md(s["note"]), 1)}</div>')
    b.append('<h2>Metadata as recorded</h2><dl class="fields small">' + "".join(f"<dt>{esc(k)}</dt><dd>{inline(v)}</dd>" for k, v in m.items()) + "</dl>")
    if s["files"]:
        b.append(f'<p class="muted">Original files held in the project (not published): {esc(", ".join(s["files"]))}</p>')
    page(f"sources/{d}.html", s["id"] or d, "".join(b))

# views
def view(kind: str, key: str, label: str) -> None:
    ds = sorted([d for d, s in sources.items() if key in s[kind]], key=lambda d: (sources[d]["id"] or "ZZZ", d))
    ls = [l for l in links if l["source"] in ds]
    tgt = Counter(l["claim"] for l in ls)
    b = [f'<p class="crumb"><a href="../index.html">Home</a> · <a href="index.html">{"Ages" if kind == "ages" else "Themes"}</a> · {esc(label)}</p><h1>{esc(label)}</h1>',
         f'<p class="muted">Generated view: {len(ds)} sources whose Kunskapsbank note was filed under this {"age group" if kind == "ages" else "theme"}, and the claims and candidates they link to.</p>']
    cl = [t for t in tgt if t.startswith("C")]
    b.append("<h2>Claims</h2>" + ("".join(claim_card(claims[t], 1) + f'<p class="muted">{tgt[t]} link(s) from sources in this view.</p>' for t in sorted(cl)) or "<p class='muted'>No approved claim is linked from sources in this view yet.</p>"))
    kl = sorted(t for t in tgt if t.startswith("K"))
    if kl:
        b.append("<h2>Candidates (not approved)</h2><ul>" + "".join(f'<li><a href="../candidates.html#{t}">{t}</a>: {inline(cands[t].get("Claim", ""))} <span class="muted">({tgt[t]} link(s))</span></li>' for t in kl) + "</ul>")
    b.append("<h2>Sources</h2><table><tr><th>Source</th><th>Tier</th><th>Links</th></tr>" + "".join(source_row(d, 1) for d in ds) + "</table>")
    if kind == "themes":
        arch = ROOT / "archive" / "theme-readmes" / f"{key}.md"
        if arch.exists():
            txt = "\n".join(ln for ln in read(arch).splitlines() if not ln.lstrip().startswith("|"))
            b.append(f'<details><summary>Former theme summary (Swedish, from the Kunskapsbank archive)</summary><div class="prose" lang="sv">{link_ids(md(txt), 1)}</div></details>')
    page(f"{kind}/{key}.html", label, "".join(b))

for kind, labels in (("ages", AGES), ("themes", THEMES)):
    for k, lab in labels.items():
        view(kind, k, lab)
    rows = "".join(f'<li><a href="{k}.html">{esc(lab)}</a> <span class="muted">({sum(1 for s in sources.values() if k in s[kind])} sources)</span></li>' for k, lab in labels.items())
    page(f"{kind}/index.html", "Ages" if kind == "ages" else "Themes", f'<h1>{"Age groups" if kind == "ages" else "Themes"}</h1><p class="muted">Generated views over claims, links and sources.</p><ul>{rows}</ul>')

# direction
DIR = [("position", "Position", "UTKAST.md"), ("practice", "Practice: stop / start / measure", "PRAKTIK.md"),
       ("counterarguments", "Counterarguments (steelman)", "MOTARGUMENT.md")]
def fix_dir_links(text: str) -> str:
    for slug, _, old in DIR:
        text = text.replace(f"]({old})", f"]({slug}.html)")
    text = text.replace("](../00-index/METOD.md)", "](../method.html)")
    return re.sub(r"\]\((?!http|mailto)[^)]*\.md\)", "]", text)
for slug, title, _ in DIR:
    txt = fix_dir_links(read(ROOT / "direction" / f"{slug}.md"))
    page(f"direction/{slug}.html", title, f'<p class="crumb"><a href="../index.html">Home</a> · <a href="index.html">Direction</a></p><h1>{esc(title)}</h1><p class="muted">Kunskapsbank text (Swedish, verbatim). Written before the merge; the recommendations here do not yet cite claim ids.</p><div class="prose" lang="sv">{link_ids(md(txt), 1)}</div>')
page("direction/index.html", "Direction", "<h1>Direction</h1><p>The Kunskapsbank's practice and policy texts, kept as prose (Swedish).</p><ul>" +
     "".join(f'<li><a href="{s}.html">{esc(t)}</a></li>' for s, t, _ in DIR) + "</ul>")

# method, inbox, about
page("method.html", "Method", f'<h1>Method</h1><p>How claims are attacked: an Attacker proposes one-sentence attacks, a Clerk routes each one (apply, hold or reject; the default is reject), and a writer updates the claim and its ledger. Verdicts: survived, narrowed (ledger word: weakened) or killed. Only a human approves new claims. No numeric confidence scores.</p><p>How sources are chosen (Kunskapsbank inclusion rules, Swedish, verbatim):</p><div class="prose" lang="sv">{link_ids(md(fix_dir_links(read(ROOT / "method" / "METHOD.md"))), 0)}</div>')
b = ['<h1>Inbox</h1><p>Material not yet tied to any claim or candidate. Being here says nothing about quality; it only means "not yet connected".</p>',
     f"<h2>Unlinked sources ({len(unlinked)})</h2><table><tr><th>Source</th><th>Origin</th></tr>" +
     "".join(f"<tr><td>{src_link(d, 0)}</td><td>{esc(sources[d]['origin'])}</td></tr>" for d in unlinked) + "</table>",
     "<h2>Uncatalogued</h2><ul><li>Longcamp et al. 2008, <em>Learning through Hand- or Typewriting Influences Visual Recognition of New Graphic Shapes</em> (J. Cogn. Neurosci.): metadata and PDF held, no catalog entry, no tier, no note. Related to Longcamp et al. 2005 (HAND-007).</li></ul>"]
page("inbox.html", "Inbox", "".join(b))
readme = read(ROOT / "README.md")
page("about.html", "About", f'<div class="prose">{md(readme)}</div>')
print(f"built {sum(1 for _ in OUT.rglob('*.html'))} pages into docs/")
