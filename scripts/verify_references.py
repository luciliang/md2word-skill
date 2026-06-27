#!/usr/bin/env python3
"""
MD ↔ BIB cross-validation + three-source reference verification & metadata arbitration

Three-source verification (PubMed is independently curated, weighted in arbitration):
  - CrossRef  (api.crossref.org)        : DOI anchor / journal / volume-issue-pages / year (publisher-direct)
  - PubMed   (eutils.ncbi.nlm.nih.gov) : biomedical gold standard / most rigorous author full-names (NLM manual indexing)
  - OpenAlex (api.openalex.org)        : broadest coverage / author affiliations / ORCID (free, no key)

⚠️ Sources are not independent: OpenAlex inherits much of its data from CrossRef, so "CrossRef+OpenAlex agree" ≠ double
   independent evidence. PubMed is independently curated — its single vote weighs ≥ CR+OA combined — arbitration is not simple vote-counting.

Arbitration flow: normalize to eliminate false conflicts → judge same paper → AUTO/FLAG/REJECT tiers → on real conflicts pick the value from the field's best source

Tiers:
  AUTO    agree / agree after normalization / clear majority   → auto-adopt (PASS)
  FLAG    substantive conflict but a reasonable default       → import (best value) + flag the conflict
  REJECT  clearly not the same paper / key fields all conflict → do not import
  SKIP    not found in any of the three sources               → do not import (authenticity unverified)

Usage:
  python3 verify_references.py <md_path> <bib_path> [--verify] [--strict] [--json OUT]
  --verify   enable three-source verification (default: MD↔BIB cross-validation only)
  --strict   FLAG also blocks (default: FLAG does not block — imports but tags in Extra)
"""

import argparse
import json
import re
import subprocess
import sys
import os
import time
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed


# ── Constants ─────────────────────────────────────────────────────────
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENALEX_BASE = "https://api.openalex.org"
CONTACT_EMAIL = os.environ.get("NCBI_EMAIL", "md2word-skill@example.com")

# Per-field source priority on conflicts (PubMed weighted first for authors)
SOURCE_PRIORITY = {
    "title":   ["crossref", "pubmed", "openalex"],
    "year":    ["crossref", "pubmed", "openalex"],
    "authors": ["pubmed", "crossref", "openalex"],   # authors prefer PubMed (NLM curation is most rigorous)
    "journal": ["crossref", "pubmed", "openalex"],
    "volume":  ["crossref", "pubmed", "openalex"],
    "issue":   ["crossref", "pubmed", "openalex"],
    "pages":   ["crossref", "pubmed", "openalex"],
}

# PubMed free tier is rate-limited to 3 req/s — be polite during concurrent verification
PUBMED_PAUSE = 0.4
MAX_WORKERS = 4


# ── BibTeX / Markdown parsing (unchanged from original) ────────────────
def load_bib(bib_path):
    """Parse a standard BibTeX file; returns {cite_key: {doi, title, year, author}}"""
    import bibtexparser
    with open(bib_path, encoding="utf-8") as f:
        db = bibtexparser.load(f)
    entries = {}
    for e in db.entries:
        entries[e["ID"]] = {
            "doi": e.get("doi", "").strip().lstrip("DOI:").lower() or None,
            "title": e.get("title", "").strip().strip("{}") or None,
            "year": e.get("year", "").strip() or None,
            "author": e.get("author", "").strip() or None,
        }
    return entries


def _ast_citation_ids(obj):
    """Recursively traverse the pandoc AST, collecting all Cite node citationIds in order (including each item in composite citations)."""
    ids = []
    if isinstance(obj, dict):
        if obj.get("t") == "Cite" and isinstance(obj.get("c"), list) and obj["c"]:
            for cit in obj["c"][0]:              # c[0] = citations list
                if isinstance(cit, dict) and cit.get("citationId"):
                    ids.append(cit["citationId"])
        for v in obj.values():
            ids.extend(_ast_citation_ids(v))
    elif isinstance(obj, list):
        for item in obj:
            ids.extend(_ast_citation_ids(item))
    return ids


def extract_md_keys(md_path):
    """Extract every cite_key cited in the MD (including each item in composite citations), deduplicated in order of appearance.

    Main path: pandoc AST (``pandoc md -t json`` → Cite.citationId) — structured ground truth, one shot;
    immune to composite citations / prefix decoration (-@) / nesting / syntactic variants that regex cannot cover.
    Fallback: regex (when pandoc is unavailable)."""
    keys = []
    try:
        r = subprocess.run(["pandoc", md_path, "-t", "json"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            keys = _ast_citation_ids(json.loads(r.stdout))
    except Exception:
        keys = []
    if not keys:  # pandoc failed → regex fallback
        with open(md_path, encoding="utf-8") as f:
            text = f.read()
        for block in re.findall(r"\[@([^\]]+)\]", text):
            for part in re.split(r"[;,]", block):
                part = part.strip().lstrip("-")
                m = re.match(r"@?([\w][\w-]*)", part)
                if m:
                    keys.append(m.group(1))
    seen = {}
    for k in keys:
        if k not in seen:
            seen[k] = len(seen) + 1
    return seen


def cross_validate(md_path, bib_path):
    """MD ↔ BIB cross-validation"""
    print(f"  Parsing MD citations: {md_path}", flush=True)
    md_keys = extract_md_keys(md_path)
    print(f"  Found {len(md_keys)} unique citations", flush=True)

    print(f"  Loading BIB: {bib_path}", flush=True)
    bib_entries = load_bib(bib_path)
    bib_keys = set(bib_entries.keys())
    print(f"  Found {len(bib_entries)} entries", flush=True)

    missing_in_bib = sorted(set(md_keys.keys()) - bib_keys)
    unused_in_md = sorted(bib_keys - set(md_keys.keys()))
    matched = set(md_keys.keys()) & bib_keys
    no_doi = sorted(k for k in matched if not bib_entries[k].get("doi"))
    no_title = sorted(k for k in matched if not bib_entries[k].get("title"))

    print(f"  ✅ matched {len(matched)} | ❌ missing in BIB {len(missing_in_bib)} | ⚠ unused in MD {len(unused_in_md)}", flush=True)
    return {
        "md_total": len(md_keys),
        "bib_total": len(bib_entries),
        "matched": len(matched),
        "missing_in_bib": missing_in_bib,
        "unused_in_md": unused_in_md,
        "no_doi": no_doi,
        "no_title": no_title,
    }


def print_cross_report(result):
    print("\nCross-validation report")
    print("━" * 50)
    print(f'  MD citations: {result["md_total"]}    BIB entries: {result["bib_total"]}')
    print(f'  ✅ matched: {result["matched"]}')
    if result["missing_in_bib"]:
        print(f'\n❌ cited in MD but missing from BIB ({len(result["missing_in_bib"])}):  ← must fix')
        for k in result["missing_in_bib"]:
            print(f"   - {k}")
    if result["unused_in_md"]:
        print(f'\n⚠️  in BIB but not cited in MD ({len(result["unused_in_md"])}):  ← optional cleanup')
        for k in result["unused_in_md"][:10]:
            print(f"   - {k}")
        if len(result["unused_in_md"]) > 10:
            print(f"   ... and {len(result['unused_in_md'])} more")
    if result["no_doi"]:
        print(f'\nℹ️  no DOI, reverse-lookup by title ({len(result["no_doi"])}/{result["matched"]}):  ← three-source title query')
    if result["no_title"]:
        print(f'\n❌ no title, cannot reverse-lookup ({len(result["no_title"])}):  ← must fix')
        for k in result["no_title"]:
            print(f"   - {k}")
    print("━" * 50)


# ── Normalization (eliminate false conflicts) ─────────────────────────
def normalize(text):
    """Strip punctuation + lowercase, for title comparison"""
    return re.sub(r"[^\w]", "", text or "").lower()


def norm_lastname(name):
    """Author surname normalization: strip diacritics / hyphens / periods / spaces + lowercase. Fogliatà ≡ Fogliata ≡ FOGLIATA"""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[.\-'\s]", "", n).lower()


def norm_year(y):
    m = re.search(r"\d{4}", str(y or ""))
    return m.group(0) if m else ""


def _title_similar(a, b):
    """Title word-level Jaccard similarity ≥ 0.8 → considered the same paper"""
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.8


# ── Three-source queries ────────────────────────────────────────────────
def query_crossref(doi=None, title=None):
    """Query CrossRef; returns standardized authoritative-metadata dict or None"""
    try:
        if doi:
            r = subprocess.run(
                ["curl", "-s", f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                msg = json.loads(r.stdout).get("message", {})
                if msg:
                    return _parse_crossref(msg)
        elif title:
            q = urllib.parse.quote(title)
            r = subprocess.run(
                ["curl", "-s", f"https://api.crossref.org/works?query.title={q}&rows=1"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                items = json.loads(r.stdout).get("message", {}).get("items", [])
                if items:
                    return _parse_crossref(items[0])
        return None
    except Exception:
        return None


def _parse_crossref(msg):
    dp = msg.get("published-print", msg.get("published-online", {})).get("date-parts", [[None]])[0]
    authors = [{"family": a.get("family", ""), "given": a.get("given", "")}
               for a in msg.get("author", [])]
    return {
        "title": (msg.get("title") or [""])[0],
        "year": str(dp[0]) if dp and dp[0] else None,
        "authors": authors,
        "journal": (msg.get("container-title") or [""])[0],
        "volume": str(msg.get("volume", "")) or None,
        "issue": str(msg.get("issue", "")) or None,
        "pages": msg.get("page", "") or None,
        "doi": msg.get("DOI", ""),
        "issn": (msg.get("ISSN") or [""])[0] or None,
    }


def query_pubmed(doi=None, title=None):
    """Query PubMed. DOI uses idconv for an exact lookup (avoids esearch [AID] treating an invalid DOI
    as fuzzy text and mismatching unrelated papers); title uses esearch [TI]. esummary fetches metadata."""
    try:
        pmid = None
        if doi:
            # idconv exact: DOI → PMID. Returns None if not found (no fuzzy matching)
            url = (f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={urllib.parse.quote(doi)}"
                   f"&format=json&tool=md2word&email={CONTACT_EMAIL}")
            r = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                recs = json.loads(r.stdout).get("records", [])
                if recs and recs[0].get("status") != "error":
                    pmid = recs[0].get("pmid")
        elif title:
            esearch = (f"{PUBMED_BASE}/esearch.fcgi?db=pubmed&term={urllib.parse.quote(title + '[TI]')}"
                       f"&retmode=json&retmax=1&tool=md2word&email={CONTACT_EMAIL}")
            r = subprocess.run(["curl", "-s", esearch], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                idlist = json.loads(r.stdout).get("esearchresult", {}).get("idlist", [])
                if idlist:
                    pmid = idlist[0]
        if not pmid:
            return None
        time.sleep(PUBMED_PAUSE)  # polite rate-limiting for the free 3 req/s tier
        esummary = (f"{PUBMED_BASE}/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
                    f"&tool=md2word&email={CONTACT_EMAIL}")
        r = subprocess.run(["curl", "-s", esummary], capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        rec = json.loads(r.stdout).get("result", {}).get(pmid, {})
        if not rec or "error" in rec:
            return None
        return _parse_pubmed(rec)
    except Exception:
        return None


def _parse_pubmed(rec):
    authors = []
    for a in rec.get("authors", []):
        # esummary author only has a lowercase "name" (e.g. "Fogliata A" = LastName + Initials)
        name = a.get("name") or a.get("LastName", "") or ""
        parts = name.split()
        if len(parts) >= 2:
            last, given = parts[0], " ".join(parts[1:])   # PubMed: surname first, initials after
        elif parts:
            last, given = parts[0], ""
        else:
            last, given = "", ""
        authors.append({"family": last, "given": given})
    doi = ""
    for el in rec.get("articleids", []):
        if el.get("idtype") == "doi":
            doi = (el.get("value") or "").lower()
    year = norm_year(rec.get("sortpubdate") or rec.get("pubdate") or "")
    return {
        "title": rec.get("title", "").rstrip("."),
        "year": year or None,
        "authors": authors,
        "journal": rec.get("fulljournalname", "") or rec.get("source", ""),
        "volume": rec.get("volume", "") or None,
        "issue": rec.get("issue", "") or None,
        "pages": rec.get("pages", "") or None,
        "doi": doi,
        "issn": rec.get("issn", "") or None,
        "pmid": rec.get("uid", ""),
    }


def query_openalex(doi=None, title=None):
    """Query OpenAlex. by-DOI direct lookup; by-title search."""
    try:
        if doi:
            url = f"{OPENALEX_BASE}/works/doi:{doi}?mailto={CONTACT_EMAIL}"
        elif title:
            url = (f"{OPENALEX_BASE}/works?search={urllib.parse.quote(title)}"
                   f"&per-page=1&mailto={CONTACT_EMAIL}")
        else:
            return None
        r = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        data = json.loads(r.stdout)
        if isinstance(data, dict) and data.get("results") is not None:
            data = data["results"][0] if data["results"] else None
        if not data or not data.get("id"):
            return None
        return _parse_openalex(data)
    except Exception:
        return None


def _parse_openalex(work):
    authors = []
    for au in work.get("authorships", []):
        a = au.get("author", {}) or {}
        raw = au.get("raw_author_name") or a.get("display_name", "")
        if "," in raw:
            # "Last, Given" format (common in OpenAlex raw_author_name)
            parts = [p.strip() for p in raw.split(",", 1)]
            last = parts[0]
            given = parts[1] if len(parts) > 1 else ""
        else:
            # "Given Last" format (common in display_name)
            p = raw.rsplit(" ", 1)
            given, last = (p[0], p[1]) if len(p) == 2 else ("", raw)
        authors.append({
            "family": last,
            "given": given,
            "orcid": (a.get("orcid") or "").replace("https://orcid.org/", ""),
        })
    venue = (work.get("primary_location", {}) or {}).get("source", {}) or {}
    biblio = work.get("biblio", {}) or {}
    pages = f'{biblio.get("first", "")}-{biblio.get("last", "")}'.strip("-")
    return {
        "title": work.get("title", "") or "",
        "year": work.get("publication_date", "")[:4] or None,
        "authors": authors,
        "journal": venue.get("display_name", "") or "",
        "volume": str(biblio.get("volume", "")) or None,
        "issue": str(biblio.get("issue", "")) or None,
        "pages": pages or None,
        "doi": (work.get("doi") or "").replace("https://doi.org/", ""),
        "issn": venue.get("issn_l") or (venue.get("issn") or [""])[0] or None,
        "cited_by_count": work.get("cited_by_count", 0),
    }


# ── Arbitration ────────────────────────────────────────────────────────
def is_same_paper(records):
    """records: {source: meta or None}. Judge whether the fetched records are the same paper."""
    got = {s: r for s, r in records.items() if r}
    if not got:
        return False
    titles = [normalize(r.get("title", "")) for r in got.values()]
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            if titles[i] and titles[j] and not _title_similar(titles[i], titles[j]):
                return False
    years = [norm_year(r.get("year")) for r in got.values() if norm_year(r.get("year"))]
    if len(years) >= 2:
        yint = [int(y) for y in years]
        if max(yint) - min(yint) > 1:  # ±1 tolerance for epub/print differences
            return False
    return True


def reconcile(records):
    """
    records: {source: meta or None}
    Returns (authoritative, conflicts):
      authoritative: adjudicated fields (each field taken from its best source; format matches meta dict)
      conflicts: [{field, values:{source: display value}, chosen_source}, ...]
    """
    got = {s: r for s, r in records.items() if r}
    authoritative, conflicts = {}, []
    if not got:
        return authoritative, conflicts

    for field in ["title", "year", "authors", "journal", "volume", "issue", "pages", "doi"]:
        # ── journal special-case: issn match OR bracket-stripped text match → same journal (no conflict) ──
        if field == "journal":
            issns = {(r.get("issn") or "").lower().replace("-", "")
                     for r in got.values() if (r.get("issn") or "").lower().replace("-", "")}
            texts = {normalize(re.sub(r"\s*\([^)]*\)", "", r.get("journal", "")))
                     for r in got.values()}
            texts.discard("")
            same = (len(issns) == 1) or (len(texts) == 1)
            chosen_src = next((s for s in SOURCE_PRIORITY["journal"] if s in got), None)
            if chosen_src:
                authoritative[field] = got[chosen_src].get("journal")
            if not same:
                conflicts.append({"field": "journal",
                                  "values": {s: r.get("journal") for s, r in got.items()},
                                  "chosen_source": chosen_src})
            continue

        # ── generic fields: normalized comparison ──
        vals = {}  # source -> (raw, norm)
        for s, r in got.items():
            raw = r.get(field)
            if field == "authors":
                norm = tuple(norm_lastname(a.get("family", "")) for a in (raw or []))
            elif field == "year":
                norm = norm_year(raw)
            elif field in ("volume", "issue"):
                norm = re.sub(r"\D", "", str(raw or ""))
            elif field == "pages":
                # Pages: compare only the start page (PubMed often abbreviates "2253-65" = "2253-2265")
                norm = re.split(r"[-–]", str(raw or ""))[0].strip()
            else:
                norm = normalize(raw)
            vals[s] = (raw, norm)
        present = {s: v[1] for s, v in vals.items() if v[1]}
        if not present:
            continue

        distinct = {v for v in present.values() if v}
        chosen_src = next((s for s in SOURCE_PRIORITY.get(field, ["crossref", "pubmed", "openalex"])
                           if s in present), None)
        if chosen_src and vals[chosen_src][0] is not None:
            authoritative[field] = vals[chosen_src][0]
        if len(distinct) > 1:
            display = {}
            for s, v in vals.items():
                if not v[1]:
                    continue
                display[s] = ([a.get("family", "") for a in (v[0] or [])]
                              if field == "authors" else v[0])
            conflicts.append({"field": field, "values": display, "chosen_source": chosen_src})

    # Merge OpenAlex-only ORCID (not counted as a conflict)
    oa = got.get("openalex")
    if oa:
        orcids = {norm_lastname(a.get("family", "")): a.get("orcid")
                  for a in oa.get("authors", []) if a.get("orcid")}
        if orcids:
            authoritative["orcids"] = orcids
    return authoritative, conflicts


def verify_one(entry):
    """Verify a single reference (three sources queried serially; scheduled concurrently by multi_verify).
    entry: {cite_key, doi, title, ...} → (cite_key, result)"""
    cite_key = entry["cite_key"]
    doi = entry.get("doi")
    title = entry.get("title")

    records = {
        "crossref": query_crossref(doi=doi, title=title),
        "pubmed": query_pubmed(doi=doi, title=title),
        "openalex": query_openalex(doi=doi, title=title),
    }

    # Key safeguard: each source's title must be similar to the BIB title, otherwise that source mismatched — prevents
    # a single source's erroneous data from spuriously PASSing due to "no other source to compare" (e.g. PubMed fuzzy-matching an invalid DOI to an unrelated paper).
    bib_t = normalize(title)
    if bib_t:
        for s in list(records):
            r = records[s]
            if r:
                src_t = normalize(r.get("title", ""))
                if src_t and not _title_similar(src_t, bib_t):
                    records[s] = None  # drop sources whose title doesn't match the BIB

    found = [s for s, r in records.items() if r]

    if not found:
        return cite_key, {"status": "SKIP", "authoritative": {}, "conflicts": [],
                          "sources_found": [], "issues": ["Not found in any of the three sources, or title doesn't match the BIB (DOI may be invalid)"]}

    if not is_same_paper(records):
        return cite_key, {"status": "REJECT", "authoritative": {}, "conflicts": [],
                          "sources_found": found,
                          "issues": ["Sources don't look like the same paper (title/author/year mismatch)"]}

    authoritative, conflicts = reconcile(records)
    status = "FLAG" if conflicts else "PASS"
    return cite_key, {"status": status, "authoritative": authoritative,
                      "conflicts": conflicts, "sources_found": found, "issues": []}


def multi_verify(verify_entries):
    """Three-source concurrent verification. verify_entries: {cite_key: {doi,title,...}}"""
    items = list(verify_entries.items())
    total = len(items)
    print(f"  Three-source verification of {total} entries (CrossRef + PubMed + OpenAlex, concurrent) ...", flush=True)
    results, done = {}, 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(verify_one, {**v, "cite_key": k}): k for k, v in items}
        for fut in as_completed(futures):
            ck = futures[fut]
            try:
                k, res = fut.result()
                results[k] = res
                done += 1
                print(f'  [{done}/{total}] {k}: {res["status"]} '
                      f'(sources={",".join(res["sources_found"]) or "none"} '
                      f'conflicts={len(res["conflicts"])})', flush=True)
            except Exception as e:
                done += 1
                results[ck] = {"status": "SKIP", "authoritative": {}, "conflicts": [],
                               "sources_found": [], "issues": [str(e)]}
                print(f"  [{done}/{total}] {ck}: ERROR ({e})", flush=True)
    return results


def print_verify_report(results, strict=False):
    from collections import Counter
    counts = Counter(r["status"] for r in results.values())
    print("\nThree-source reference verification report")
    print("━" * 60)
    print(f"  Verified {len(results)} entries | " + " | ".join(
        f"{s}: {counts.get(s, 0)}" for s in ["PASS", "FLAG", "REJECT", "SKIP"]))

    rejects = [(k, v) for k, v in results.items() if v["status"] == "REJECT"]
    flags = [(k, v) for k, v in results.items() if v["status"] == "FLAG"]
    skips = [(k, v) for k, v in results.items() if v["status"] == "SKIP"]

    if rejects:
        print(f"\n❌ REJECT ({len(rejects)}): not imported")
        for k, v in rejects:
            print(f'   - {k}: {"; ".join(v["issues"])}')
    if flags:
        tag = "blocked (--strict)" if strict else "imported but tagged in Extra"
        print(f"\n⚠️  FLAG ({len(flags)}): {tag}")
        for k, v in flags:
            for c in v["conflicts"]:
                vals = " | ".join(f"{s}={x}" for s, x in c["values"].items())
                print(f'   - {k}.{c["field"]}: {vals}  → using {c["chosen_source"]}')
    if skips:
        print(f"\n⏭  SKIP ({len(skips)}): not found in any source")
        for k, v in skips:
            print(f"   - {k}")
    print("━" * 60)


# ── Main ──────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="MD↔BIB cross-validation + three-source (CrossRef/PubMed/OpenAlex) verification & metadata arbitration")
    parser.add_argument("md_path", help="Path to the Markdown file")
    parser.add_argument("bib_path", help="Path to the BibTeX file")
    parser.add_argument("--verify", action="store_true", help="Enable three-source verification (default: cross-validation only)")
    parser.add_argument("--strict", action="store_true",
                        help="FLAG also blocks (default: FLAG does not block — imports but tags in Extra)")
    parser.add_argument("--json", help="Output results JSON (includes adjudicated authoritative metadata)")
    args = parser.parse_args()

    # Step 2b: cross-validation
    print("Step 2b: MD ↔ BIB cross-validation")
    cv_result = cross_validate(args.md_path, args.bib_path)
    print_cross_report(cv_result)

    fatal = cv_result["missing_in_bib"] + cv_result["no_title"]
    if fatal:
        print("\n⛔ Fatal issues found — please fix and re-run.")
        if args.json:
            with open(args.json, "w") as f:
                json.dump({"cross_validate": cv_result}, f, ensure_ascii=False, indent=2)
        return 1

    # Step 2c: three-source verification (optional)
    v_results = None
    blocked = False
    if args.verify:
        print("\nStep 2c: three-source verification (CrossRef + PubMed + OpenAlex)")
        bib_entries = load_bib(args.bib_path)
        md_keys = extract_md_keys(args.md_path)
        entries = {k: v for k, v in bib_entries.items() if k in md_keys}
        v_results = multi_verify(entries)
        print_verify_report(v_results, strict=args.strict)
        if args.strict and any(r["status"] in ("FLAG", "REJECT") for r in v_results.values()):
            blocked = True
            print("\n⛔ --strict mode: FLAG/REJECT present, blocked. Remove --strict to import (FLAG will be tagged in Extra).")

    # Output JSON (includes authoritative metadata, consumed by import_zotero.py)
    if args.json:
        output = {"cross_validate": cv_result}
        if v_results:
            output["multi_verify"] = v_results
        with open(args.json, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nResults (with authoritative metadata) saved to {args.json}")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
