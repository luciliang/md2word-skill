#!/usr/bin/env python3
"""
inject_zotero.py — Replace static numbered citations in a Word document
with Zotero ADDIN CSL_CITATION field codes.

Usage:
    python3 inject_zotero.py \
        --input /tmp/pandoc_output.docx \
        --output final_zotero.docx \
        --mapping /tmp/citation_mapping.json \
        --user-id 3313474

Mapping JSON format:
    {
        "1": "J8K6WXE8",
        "2": "7SU3QAU9",
        "3": "4BC6W52P",
        ...
    }
    Keys are pandoc citation numbers (strings), values are Zotero item keys.
"""

import argparse
import json
import random
import string
import sys
from pathlib import Path

from lxml import etree
from docx import Document
from docx.oxml.ns import qn

# ── Regex ───────────────────────────────────────────────────────────────

CITATION_RE = r'^(\d+(?:\s*,\s*\d+)*)$'

import re
CITATION_PATTERN = re.compile(CITATION_RE)

# ── Helpers ─────────────────────────────────────────────────────────────


def random_citation_id(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def build_csl_citation(citation_nums, user_id, citation_map):
    """Build the CSL_CITATION JSON payload."""
    citation_items = []
    for num in citation_nums:
        key = citation_map.get(str(num))
        if key is None:
            raise ValueError(f"No Zotero key for citation #{num}")
        citation_items.append({
            "id": num,
            "uris": [f"http://zotero.org/users/{user_id}/items/{key}"]
        })
    return json.dumps({
        "citationID": random_citation_id(),
        "properties": {"noteIndex": 0},
        "citationItems": citation_items,
        "schema": "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"
    }, ensure_ascii=False)


def make_run(xml_str):
    """Parse an XML fragment into an element."""
    return etree.fromstring(xml_str)


def escape_xml(text):
    """Escape special XML characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def create_zotero_field_runs(citation_nums, user_id, citation_map, rPr_xml=None):
    """
    Return list of <w:r> elements forming a Zotero ADDIN CSL_CITATION field.
    Preserves the original rPr formatting for the display run.
    """
    csl_json = build_csl_citation(citation_nums, user_id, citation_map)
    instr_text = f" ADDIN ZOTERO_ITEM CSL_CITATION {csl_json} "
    display_text = ",".join(str(n) for n in citation_nums)

    runs = []

    # 1. fldChar begin
    runs.append(make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:rPr><w:rStyle w:val="ZoteroCitation"/></w:rPr>'
        '<w:fldChar w:fldCharType="begin"/>'
        '</w:r>'
    ))

    # 2. instrText
    runs.append(make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:rPr><w:rStyle w:val="ZoteroCitation"/></w:rPr>'
        '<w:instrText xml:space="preserve">{}</w:instrText>'
        '</w:r>'.format(escape_xml(instr_text))
    ))

    # 3. fldChar separate
    runs.append(make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:rPr><w:rStyle w:val="ZoteroCitation"/></w:rPr>'
        '<w:fldChar w:fldCharType="separate"/>'
        '</w:r>'
    ))

    # 4. Display text (superscript numbers, using original rPr if available)
    if rPr_xml:
        display_rpr = rPr_xml.replace(
            '</w:rPr>',
            '<w:rStyle w:val="ZoteroCitation"/></w:rPr>'
        )
        display_xml = (
            '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'{display_rpr}'
            f'<w:t xml:space="preserve">{escape_xml(display_text)}</w:t>'
            '</w:r>'
        )
    else:
        display_xml = (
            '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:rPr><w:rStyle w:val="ZoteroCitation"/>'
            '<w:vertAlign w:val="superscript"/></w:rPr>'
            f'<w:t xml:space="preserve">{escape_xml(display_text)}</w:t>'
            '</w:r>'
        )
    runs.append(make_run(display_xml))

    # 5. fldChar end
    runs.append(make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:rPr><w:rStyle w:val="ZoteroCitation"/></w:rPr>'
        '<w:fldChar w:fldCharType="end"/>'
        '</w:r>'
    ))

    return runs


def is_superscript_citation_run(r_elem):
    """Check if a <w:r> is a superscript citation (digits + commas only)."""
    rPr = r_elem.find(qn('w:rPr'))
    if rPr is None:
        return False
    va = rPr.find(qn('w:vertAlign'))
    if va is None or va.get(qn('w:val')) != 'superscript':
        return False
    t_elem = r_elem.find(qn('w:t'))
    if t_elem is None or t_elem.text is None:
        return False
    return bool(CITATION_PATTERN.match(t_elem.text.strip()))


def get_citation_nums(r_elem):
    """Extract citation numbers from a run's text."""
    t_elem = r_elem.find(qn('w:t'))
    text = t_elem.text.strip()
    return [int(n.strip()) for n in text.split(',')]


def get_rPr_xml(r_elem):
    """Get the rPr XML string from a run."""
    rPr = r_elem.find(qn('w:rPr'))
    if rPr is not None:
        return etree.tostring(rPr, encoding='unicode')
    return None


# ── Main ────────────────────────────────────────────────────────────────


def inject_zotero_fields(input_path, output_path, mapping_path, user_id):
    """Main injection logic."""

    # Load mapping
    with open(mapping_path) as f:
        citation_map = json.load(f)
    print(f"Loaded {len(citation_map)} citation mappings from {mapping_path}")

    print(f"Opening {input_path} ...")
    doc = Document(str(input_path))
    body = doc.element.body
    total_replaced = 0
    warnings = []

    # Step 1: Find and replace all superscript citation runs
    for p_elem in body.iter(qn('w:p')):
        runs_to_replace = []
        for r_elem in list(p_elem):
            if is_superscript_citation_run(r_elem):
                runs_to_replace.append(r_elem)

        for r_elem in runs_to_replace:
            nums = get_citation_nums(r_elem)
            rPr_xml = get_rPr_xml(r_elem)
            try:
                field_runs = create_zotero_field_runs(nums, user_id, citation_map, rPr_xml)
            except ValueError as e:
                warnings.append(str(e))
                continue

            # Replace the original run with field runs
            parent = r_elem.getparent()
            idx = list(parent).index(r_elem)
            parent.remove(r_elem)
            for i, fr in enumerate(field_runs):
                parent.insert(idx + i, fr)

            total_replaced += 1
            print(f"  ✓ Replaced citation {','.join(str(n) for n in nums)}")

    print(f"\nTotal citations replaced: {total_replaced}")
    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠ {w}")

    # Step 2: Remove the static References section
    refs_heading = None
    for p_elem in body.iter(qn('w:p')):
        texts = [t.text for t in p_elem.iter(qn('w:t')) if t.text]
        full_text = ''.join(texts).strip()
        if full_text == 'References':
            refs_heading = p_elem
            break

    if refs_heading is not None:
        elems_to_remove = []
        found = False
        for child in list(body):
            if child is refs_heading:
                found = True
            if found:
                elems_to_remove.append(child)
        for elem in elems_to_remove:
            body.remove(elem)
        print(f"Removed {len(elems_to_remove)} elements from References section")
    else:
        print("⚠ No 'References' heading found — skipping removal")

    # Step 3: Add bibliography section with Zotero field placeholder
    ref_heading = etree.SubElement(body, qn('w:p'))
    ref_heading.set(qn('w:rsidR'), '00000000')
    ref_heading.set(qn('w:rsidRDefault'), '00000000')
    pPr = etree.SubElement(ref_heading, qn('w:pPr'))
    pStyle = etree.SubElement(pPr, qn('w:pStyle'))
    pStyle.set(qn('w:val'), 'Heading1')
    # Add "References" text to the heading
    r_text = etree.SubElement(ref_heading, qn('w:r'))
    t = etree.SubElement(r_text, qn('w:t'))
    t.text = 'References'

    # Bibliography field paragraph
    bib_para = etree.SubElement(body, qn('w:p'))
    bib_para.set(qn('w:rsidR'), '00000000')
    bib_para.set(qn('w:rsidRDefault'), '00000000')
    pPr2 = etree.SubElement(bib_para, qn('w:pPr'))
    pStyle2 = etree.SubElement(pPr2, qn('w:pStyle'))
    pStyle2.set(qn('w:val'), 'Bibliography')

    bib_json = json.dumps({
        "bibliographyStyle": "http://www.zotero.org/styles/apa",
        "bibliographyDefaults": "",
        "citationCluster": []
    }, ensure_ascii=False)
    bib_instr = f" ADDIN ZOTERO_BIBLIOGRAPH {bib_json} "

    r1 = make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:fldChar w:fldCharType="begin"/></w:r>'
    )
    r2_xml = (
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:instrText xml:space="preserve">{}</w:instrText>'
        '</w:r>'
    ).format(escape_xml(bib_instr))
    r2 = make_run(r2_xml)
    r3 = make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:fldChar w:fldCharType="separate"/></w:r>'
    )
    r4 = make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:t xml:space="preserve">[BIBLIOGRAPHY]</w:t></w:r>'
    )
    r5 = make_run(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:fldChar w:fldCharType="end"/></w:r>'
    )
    for r in [r1, r2, r3, r4, r5]:
        bib_para.append(r)

    print("Added bibliography placeholder")

    # Step 4: Add ZoteroCitation character style to styles.xml if missing
    styles_part = doc.styles.element
    has_zotero_style = False
    for style in styles_part.iter(qn('w:style')):
        if style.get(qn('w:styleId')) == 'ZoteroCitation':
            has_zotero_style = True
            break

    if not has_zotero_style:
        zotero_style = make_run(
            '<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            ' w:type="character" w:styleId="ZoteroCitation">'
            '<w:name w:val="ZoteroCitation"/>'
            '<w:rPr>'
            '<w:vertAlign w:val="superscript"/>'
            '</w:rPr>'
            '</w:style>'
        )
        styles_part.append(zotero_style)
        print("Added ZoteroCitation character style")

    # Step 5: Save
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving to {output} ...")
    doc.save(str(output))
    print("✓ Done!")

    return total_replaced, len(warnings)


def main():
    parser = argparse.ArgumentParser(
        description="Inject Zotero ADDIN CSL_CITATION field codes into a Word document"
    )
    parser.add_argument(
        '--input', required=True,
        help='Input Word file (pandoc output with numbered citations)'
    )
    parser.add_argument(
        '--output', required=True,
        help='Output Word file with Zotero field codes'
    )
    parser.add_argument(
        '--mapping', required=True,
        help='JSON file mapping citation numbers to Zotero item keys'
    )
    parser.add_argument(
        '--user-id', default='3313474',
        help='Zotero user ID (default: 3313474)'
    )

    args = parser.parse_args()

    total, warnings = inject_zotero_fields(
        input_path=args.input,
        output_path=args.output,
        mapping_path=args.mapping,
        user_id=args.user_id,
    )

    if total == 0:
        print("\n⚠ No citations were replaced. Check if the document uses superscript citation numbers.")
        sys.exit(1)

    print(f"\n{'='*50}")
    print(f"Result: {total} citations injected, {warnings} warnings")
    print(f"Open '{args.output}' in Word with Zotero plugin to refresh bibliography.")


if __name__ == "__main__":
    main()
