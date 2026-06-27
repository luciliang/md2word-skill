#!/usr/bin/env python3
"""
import_zotero.py — Import authoritative metadata (after three-source arbitration) into a Zotero collection.

Consumes the output of verify_references.py --json. For each PASS/FLAG entry, builds a complete
Zotero item from the 【authoritative metadata】 (not the BIB original value) — this is the core
of fixing BIB errors (e.g. author names): even if the BIB spells the author as Fogliato,

three-source arbitration yields Fogliata, so the import is correct.

FLAG entries additionally write the conflict record into the Extra field. An existing item
with the same DOI in the collection → update_item (can fix author names); otherwise create_items.

  python3 import_zotero.py \
      --verify-json verify_out.json --collection "Acuros XB" \
      [--bib refs.bib] [--user-id ID] [--api-key KEY] [--dry-run] [--import-skip]

  --dry-run      Report only, do not write
  --import-skip  Also import SKIP entries using BIB values (tagged "three-source unverified")
"""
import argparse
import json
import os
import sys
import time


def connect(user_id, api_key):
    from pyzotero import zotero
    return zotero.Zotero(user_id, "user", api_key)


def _retry(fn, label, tries=4):
    """Retry Zotero Web API write operations (network jitter / 502 / SSL timeouts are common). Returns None on failure, does not abort the whole run."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                print(f"  ✗ {label} network failure ({type(e).__name__}), skipping this entry")
                return None
            print(f"    ⚠ {label} network error ({type(e).__name__}), retrying in {2*(i+1)}s...")
            time.sleep(2 * (i + 1))


def auth_to_item(auth, bib_entry):
    """Adjudicated authoritative metadata → Zotero item payload"""
    creators = [{"creatorType": "author",
                 "firstName": (a.get("given") or ""),
                 "lastName": (a.get("family") or "")}
                for a in auth.get("authors", [])]
    doi = auth.get("doi") or (bib_entry or {}).get("doi") or ""
    return {
        "itemType": "journalArticle",
        "title": auth.get("title", "") or "",
        "creators": creators,
        "date": auth.get("year", "") or "",
        "publicationTitle": auth.get("journal", "") or "",
        "volume": auth.get("volume", "") or "",
        "issue": auth.get("issue", "") or "",
        "pages": auth.get("pages", "") or "",
        "DOI": doi,
    }


def bib_authors_to_creators(author_str):
    """BIB author string → creators (SKIP fallback for --import-skip).
    Rules (docs/step3.md): drop 'and others'; split 'Last, First'; for 'First Last' the last word is the surname."""
    creators = []
    for raw in str(author_str or "").split(" and "):
        raw = raw.strip().strip("{}")
        if not raw or raw.lower() == "others":
            continue
        if "," in raw:
            last, first = [p.strip() for p in raw.split(",", 1)]
        else:
            parts = raw.split()
            if len(parts) >= 2:
                first, last = " ".join(parts[:-1]), parts[-1]
            else:
                first, last = "", raw
        creators.append({"creatorType": "author", "firstName": first, "lastName": last})
    return creators


def extra_from_conflicts(conflicts):
    if not conflicts:
        return ""
    lines = ["⚠️ METADATA CONFLICT (md2word three-source arbitration):"]
    for c in conflicts:
        vals = " | ".join(f"{s}={v}" for s, v in c["values"].items())
        lines.append(f'  {c["field"]}: {vals}  → using {c["chosen_source"]}')
    return "\n".join(lines)


def find_existing_by_doi(zot, coll_key, doi):
    if not doi or not coll_key:
        return None
    for it in zot.collection_items(coll_key):  # first 100 items by default; large collections need pagination
        d = it.get("data", {})
        if d.get("itemType") in ("attachment", "note"):
            continue
        if (d.get("DOI") or "").lower() == doi.lower():
            return it
    return None


def main():
    ap = argparse.ArgumentParser(description="Import into Zotero using authoritative metadata (consumes verify_references --json)")
    ap.add_argument("--verify-json", required=True, help="verify_references.py --json output")
    ap.add_argument("--collection", required=True, help="Zotero collection name")
    ap.add_argument("--bib", help="BibTeX (--import-skip fallback)")
    ap.add_argument("--user-id", default=os.environ.get("ZOTERO_USER_ID"))
    ap.add_argument("--api-key", default=os.environ.get("ZOTERO_API_KEY"))
    ap.add_argument("--dry-run", action="store_true", help="Report only, do not write")
    ap.add_argument("--import-skip", action="store_true", help="Also import SKIP entries using BIB values (tagged unverified)")
    ap.add_argument("--output-mapping", help="Output cite_key→Zotero key mapping (with confidence/audit); defaults to mapping.json in verify.json's directory")
    args = ap.parse_args()

    if not (args.user_id and args.api_key):
        sys.exit("❌ ZOTERO_USER_ID + ZOTERO_API_KEY required (or pass --user-id/--api-key)")

    zot = connect(args.user_id, args.api_key)
    coll_key = next((c["data"]["key"] for c in zot.collections()
                     if c["data"]["name"] == args.collection), None)
    if coll_key:
        print(f"collection: {args.collection} (exists, key={coll_key})")
    elif args.dry_run:
        print(f"collection: {args.collection} (does not exist; dry-run would create it)")
    else:
        resp = zot.create_collections([{"name": args.collection}])
        coll_key = list(resp.get("success", {}).values())[0]
        print(f"collection: {args.collection} (created, key={coll_key})")

    bib = {}
    if args.bib:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import verify_references
        bib = verify_references.load_bib(args.bib)

    verify = json.load(open(args.verify_json))
    mv = verify.get("multi_verify", {})

    stats = {"created": 0, "updated": 0, "skipped": 0, "flagged": 0}
    mapping_out = {}  # cite_key → {zotero_key, anchor, confidence, status} (with confidence and audit)
    for cite_key, v in mv.items():
        status, auth, be = v["status"], v.get("authoritative", {}), bib.get(cite_key, {})

        if status in ("PASS", "FLAG"):
            item_data = auth_to_item(auth, be)
            extra = extra_from_conflicts(v.get("conflicts", []))
            if extra:
                item_data["extra"] = extra
                stats["flagged"] += 1
            tag = "FLAG " if status == "FLAG" else "     "
            # Confidence: strong DOI anchor = high / title reverse-lookup = medium
            has_doi = bool(item_data.get("DOI"))
            anchor, confidence = ("doi", "high") if has_doi else ("title", "medium")
        elif status == "SKIP" and args.import_skip:
            item_data = {
                "itemType": "journalArticle",
                "title": be.get("title", "") or "",
                "creators": bib_authors_to_creators(be.get("author")),
                "date": be.get("year", "") or "",
                "DOI": be.get("doi", "") or "",
                "extra": "⚠️ three-source unverified (SKIP), using BIB original value",
            }
            tag = "SKIP "
            anchor, confidence = "bib", "low"  # not three-source verified
        else:
            stats["skipped"] += 1
            print(f"  ⊘ {cite_key}: {status} not imported")
            continue

        doi = item_data.get("DOI", "")
        existing = find_existing_by_doi(zot, coll_key, doi)
        lead = item_data["creators"][0]["lastName"] if item_data["creators"] else "?"
        zotero_key = ""

        if existing:
            for k, val in item_data.items():
                if k == "itemType":
                    continue
                if k == "extra" and existing["data"].get("extra"):
                    val = existing["data"]["extra"] + "\n" + val
                existing["data"][k] = val
            if not args.dry_run:
                if _retry(lambda: zot.update_item(existing), cite_key) is None:
                    continue
                time.sleep(0.5)
            zotero_key = existing["data"].get("key", "")
            stats["updated"] += 1
            print(f'  ↻ {tag}{cite_key}: updated → {lead} et al. ({item_data["date"]})')
        else:
            item_data["collections"] = [coll_key]
            if not args.dry_run:
                resp = _retry(lambda: zot.create_items([item_data]), cite_key)
                if resp is None:
                    continue
                if resp.get("failed"):
                    print(f"  ✗ {cite_key} creation failed: {resp['failed']}")
                    continue
                zotero_key = list(resp.get("success", {}).values())[0] if resp.get("success") else ""
                time.sleep(0.5)
            stats["created"] += 1
            print(f'  + {tag}{cite_key}: created → {lead} et al. ({item_data["date"]})')

        mapping_out[cite_key] = {"zotero_key": zotero_key, "anchor": anchor,
                                 "confidence": confidence, "status": status}

    # Output mapping (with confidence/audit) — removes the separate Step 4 network dependency on reading the collection
    out_mapping = args.output_mapping or os.path.join(
        os.path.dirname(os.path.abspath(args.verify_json)), "mapping.json")
    json.dump(mapping_out, open(out_mapping, "w"), ensure_ascii=False, indent=2)
    low_conf = [k for k, v in mapping_out.items() if v["confidence"] != "high"]
    suffix = " (DRY-RUN, not written)" if args.dry_run else ""
    print(f"\nDone: created {stats['created']} | updated {stats['updated']} | FLAG {stats['flagged']} | skipped {stats['skipped']}{suffix}")
    print(f"Mapped {len(mapping_out)} entries → {out_mapping}")
    if low_conf:
        print(f"⚠️ {len(low_conf)} low-confidence entries (non-DOI anchors; manual review recommended):")
        for k in low_conf:
            v = mapping_out[k]
            print(f"   - {k}: anchor={v['anchor']} confidence={v['confidence']} ({v['status']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
