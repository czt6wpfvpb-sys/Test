"""Collect new FDA events from primary FDA sources.

Standard library only. Writes the items not seen in earlier runs to a JSON
file, which the digest step (Claude) triages and emails.

Usage:
    python -m fda_agent.fetch --out out/new_items.json [--days 7] [--no-state]
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = "Mozilla/5.0 (compatible; fda-news-agent/1.0)"
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "seen.json"
STATE_KEEP_DAYS = 60

RSS_BASE = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds"
RSS_FEEDS = {
    "press_release": f"{RSS_BASE}/press-releases/rss.xml",
    "whats_new_drugs": f"{RSS_BASE}/drugs/rss.xml",
    "whats_new_biologics": f"{RSS_BASE}/biologics/rss.xml",
    "medwatch_safety": f"{RSS_BASE}/medwatch/rss.xml",
    "recall_alert": f"{RSS_BASE}/recalls/rss.xml",
}

# Pre-filter: drop obvious non-investable noise before Claude sees it.
NOISE = re.compile(
    r"\b(tobacco|e-cigarette|vape|cigar|nicotine pouch|food allerg|undeclared|"
    r"salmonella|listeria|e\. coli|cronobacter|infant formula|dietary supplement|"
    r"pet food|animal feed|cosmetic|seafood|produce|juice|cheese|peanut|milk|"
    r"egg|bakery|spice|honey|tattoo|cattle|beef|bison|livestock|poultry|veterinary)\b",
    re.I,
)
WL_KEEP_OFFICES = re.compile(
    r"Drug Evaluation|Biologics|Devices|Radiological|Pharmaceutical Quality|"
    r"Medical Products|Bioresearch|Manufacturing Quality|Office of Prescription Drug Promotion",
    re.I,
)


def get(url: str, headers: dict | None = None, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(url: str, **kw) -> dict:
    return json.loads(get(url, **kw))


def item(source, title, url, date, category, summary="", **extra) -> dict:
    key = hashlib.sha1(f"{source}|{url or title}|{date}".encode()).hexdigest()[:16]
    return {"id": key, "source": source, "category": category, "date": date,
            "title": title.strip(), "url": url, "summary": summary.strip()[:800], **extra}


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


# ---------------------------------------------------------------- sources

def rss(since: dt.date) -> list[dict]:
    out = []
    for name, url in RSS_FEEDS.items():
        root = ET.fromstring(get(url))
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            pub = it.findtext("pubDate") or ""
            try:
                d = email.utils.parsedate_to_datetime(pub).date()
            except (TypeError, ValueError):
                continue
            if d < since:
                continue
            desc = strip_tags(it.findtext("description") or "")
            if NOISE.search(title) or (name == "recall_alert" and NOISE.search(desc)):
                continue
            out.append(item(name, title, it.findtext("link"), d.isoformat(), "fda_news", desc))
    return out


def federal_register(since: dt.date) -> list[dict]:
    q = urllib.parse.urlencode({
        "conditions[agencies][]": "food-and-drug-administration",
        "conditions[publication_date][gte]": since.isoformat(),
        "per_page": 200, "order": "newest",
        "fields[]": ["title", "type", "abstract", "html_url", "publication_date", "document_number"],
    }, doseq=True)
    data = get_json(f"https://www.federalregister.gov/api/v1/documents.json?{q}")
    out = []
    for r in data.get("results", []):
        title = r.get("title") or ""
        if NOISE.search(title):
            continue
        t = title.lower()
        cat = ("advisory_committee" if "advisory committee" in t else
               "guidance" if "guidance" in t else
               "rule" if r.get("type") in ("Rule", "Proposed Rule") else
               "approval_withdrawal" if "withdraw" in t else
               "patent_extension" if "patent extension" in t or "regulatory review period" in t else
               "federal_register")
        # Info-collection / paperwork notices are pure noise.
        if "information collection" in t or "paperwork reduction" in t:
            continue
        out.append(item("federal_register", title, r.get("html_url"), r.get("publication_date"),
                        cat, r.get("abstract") or "", fr_type=r.get("type")))
    return out


def openfda(path: str, search: str, limit: int = 100, sort: str | None = None) -> list[dict]:
    params = {"search": search, "limit": limit}
    if sort:
        params["sort"] = sort
    url = f"https://api.fda.gov/{path}.json?" + urllib.parse.urlencode(params)
    try:
        return get_json(url).get("results", [])
    except urllib.error.HTTPError as e:
        if e.code == 404:  # openFDA returns 404 for zero matches
            return []
        raise


def drug_approvals(since: dt.date) -> list[dict]:
    s, e = since.strftime("%Y%m%d"), dt.date.today().strftime("%Y%m%d")
    rows = openfda("drug/drugsfda",
                   f"submissions.submission_status_date:[{s} TO {e}] AND submissions.submission_status:AP",
                   limit=1000)
    out, anda_count = [], 0
    for r in rows:
        app = r.get("application_number", "")
        is_anda = app.startswith("ANDA")
        brands = sorted({p.get("brand_name", "") for p in r.get("products", [])})
        actives = sorted({a.get("name", "") for p in r.get("products", [])
                          for a in p.get("active_ingredients", [])})
        for sub in r.get("submissions", []):
            d = sub.get("submission_status_date", "")
            if sub.get("submission_status") != "AP" or not (s <= d <= e):
                continue
            stype, cls = sub.get("submission_type"), sub.get("submission_class_code", "")
            if is_anda:
                if stype == "ORIG":
                    anda_count += 1
                continue
            # NDA/BLA: originals and new-indication (efficacy) supplements only.
            if not (stype == "ORIG" or cls == "EFFICACY"):
                continue
            docs = sub.get("application_docs") or []
            out.append(item(
                "openfda_drugsfda",
                f"{'Approval' if stype == 'ORIG' else 'New indication/efficacy supplement'}: "
                f"{', '.join(b for b in brands if b) or app} "
                f"({', '.join(a for a in actives if a) or 'ingredient n/a'}) - {r.get('sponsor_name')}",
                docs[0]["url"] if docs else f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={app[3:] if app[:3] in ('NDA','BLA') else app}",
                f"{d[:4]}-{d[4:6]}-{d[6:]}", "drug_approval",
                f"{app} {stype} #{sub.get('submission_number')} class={sub.get('submission_class_code_description')} "
                f"priority={sub.get('review_priority')}",
                sponsor=r.get("sponsor_name"), application=app))
    if anda_count:
        out.append(item("openfda_drugsfda", f"{anda_count} original ANDA (generic) approvals in window",
                        "https://www.fda.gov/drugs/drug-and-biologic-approval-and-ind-activity-reports/first-generic-drug-approvals",
                        e[:4] + "-" + e[4:6] + "-" + e[6:], "generic_approvals_summary",
                        "Check FDA First Generics list for first-generic entries."))
    return out


def crls(since: dt.date) -> list[dict]:
    out = []
    for r in openfda("transparency/crl", "_exists_:letter_date", limit=100, sort="letter_date:desc"):
        try:
            d = dt.datetime.strptime(r.get("letter_date", ""), "%m/%d/%Y").date()
        except ValueError:
            continue
        if d < since:
            continue
        fn = r.get("file_name", "")
        out.append(item("openfda_crl",
                        f"{r.get('letter_type', 'CRL').title()}: {r.get('company_name')} {r.get('application_number')}",
                        f"https://download.open.fda.gov/crl/{fn}" if fn else "https://open.fda.gov/apis/transparency/completeresponseletters/",
                        d.isoformat(), "crl", (r.get("text") or "")[:800],
                        sponsor=r.get("company_name"), approval_status=r.get("approval_status")))
    return out


def pma(since: dt.date) -> list[dict]:
    s, e = since.strftime("%Y%m%d"), dt.date.today().strftime("%Y%m%d")
    out = []
    for r in openfda("device/pma", f"decision_date:[{s} TO {e}] AND decision_code:APPR", limit=1000):
        if r.get("supplement_number"):  # originals only; supplements are mostly manufacturing noise
            continue
        out.append(item("openfda_pma", f"PMA approval: {r.get('trade_name')} - {r.get('applicant')}",
                        f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpma/pma.cfm?id={r.get('pma_number')}",
                        r.get("decision_date"), "device_approval",
                        f"{r.get('generic_name')} | {r.get('advisory_committee_description')} | {r.get('ao_statement', '')}",
                        sponsor=r.get("applicant")))
    return out


def class1_recalls(since: dt.date) -> list[dict]:
    s, e = since.strftime("%Y%m%d"), dt.date.today().strftime("%Y%m%d")
    out = []
    for path in ("drug/enforcement", "device/enforcement"):
        for r in openfda(path, f'report_date:[{s} TO {e}] AND classification:"Class I"', limit=200):
            d = r.get("report_date", "")
            out.append(item(f"openfda_{path.split('/')[0]}_recall",
                            f"Class I recall: {r.get('recalling_firm')} - {r.get('product_description', '')[:120]}",
                            "https://www.accessdata.fda.gov/scripts/ires/index.cfm",
                            f"{d[:4]}-{d[4:6]}-{d[6:]}", "recall_class1", r.get("reason_for_recall", ""),
                            sponsor=r.get("recalling_firm"), recall_number=r.get("recall_number")))
    return out


def warning_letters(since: dt.date) -> list[dict]:
    url = ("https://www.fda.gov/datatables/views/ajax?view_name=warning_letter_solr_index"
           "&view_display_id=warning_letter_solr_block&start=0&length=200")
    data = get_json(url, headers={"X-Requested-With": "XMLHttpRequest"})
    out = []
    for row in data.get("data", []):
        posted_m = re.search(r'datetime="([\d-]{10})', row[0])
        if not posted_m:
            continue
        posted = dt.date.fromisoformat(posted_m.group(1))
        if posted < since:
            continue
        office, subject = strip_tags(row[3]), strip_tags(row[4])
        if not WL_KEEP_OFFICES.search(office) or NOISE.search(subject):
            continue
        href = re.search(r'href="([^"]+)"', row[2])
        company = strip_tags(row[2])
        out.append(item("warning_letter", f"Warning letter: {company} ({subject})",
                        f"https://www.fda.gov{href.group(1)}" if href else None,
                        posted.isoformat(), "warning_letter",
                        f"Issued {strip_tags(row[1])} by {office}", sponsor=company))
    return out


SOURCES = [rss, federal_register, drug_approvals, crls, pma, class1_recalls, warning_letters]


# ---------------------------------------------------------------- state & main

def load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def save_state(state: dict) -> None:
    cutoff = (dt.date.today() - dt.timedelta(days=STATE_KEEP_DAYS)).isoformat()
    state = {k: v for k, v in state.items() if v >= cutoff}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=0, sort_keys=True))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out/new_items.json")
    ap.add_argument("--days", type=int, default=10,
                    help="Lookback window. openFDA datasets lag 1-10 days, so keep this wide; "
                         "the seen-state prevents repeats.")
    ap.add_argument("--no-state", action="store_true", help="Ignore and don't update seen-state.")
    args = ap.parse_args(argv)

    since = dt.date.today() - dt.timedelta(days=args.days)
    state = {} if args.no_state else load_state()
    items, errors = [], []
    for src in SOURCES:
        try:
            got = src(since)
            items.extend(got)
            print(f"{src.__name__}: {len(got)}", file=sys.stderr)
        except Exception as e:  # one broken source must not kill the digest
            errors.append(f"{src.__name__}: {type(e).__name__}: {e}")
            print(f"ERROR {errors[-1]}", file=sys.stderr)

    seen_urls, deduped = set(), []
    for i in items:  # the same page often appears in several RSS feeds
        k = i["url"] or i["id"]
        if k not in seen_urls:
            seen_urls.add(k)
            deduped.append(i)
    new = [i for i in deduped if i["id"] not in state]
    new.sort(key=lambda i: i["date"] or "", reverse=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"generated": dt.datetime.now().isoformat(timespec="seconds"),
                               "since": since.isoformat(), "source_errors": errors,
                               "count": len(new), "items": new}, indent=1))
    if not args.no_state:
        today = dt.date.today().isoformat()
        state.update({i["id"]: today for i in new})
        save_state(state)
    print(f"{len(new)} new of {len(items)} fetched -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
