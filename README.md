# FDA News Agent

A weekday pre-market digest of **investable** FDA news, emailed by a scheduled Claude task.

## How it works
1. `python -m fda_agent.fetch` pulls primary FDA sources (no third-party news), drops obvious noise,
   and writes items not seen before to `out/new_items.json`. `fda_agent/state/seen.json` stops repeats.
2. Claude follows `fda_agent/DIGEST_INSTRUCTIONS.md`: it triages items into tiers, maps tickers,
   adds company-disclosed events found by web search (PDUFA outcomes, CRLs, AdComm votes),
   and emails the digest.

## Sources
| Source | What it gives | Lag |
|---|---|---|
| FDA RSS (press, Drugs, Biologics, MedWatch, Recalls) | Press releases, FDA statements, safety alerts | Same day |
| Federal Register API | AdComm notices, guidances, rules, approval withdrawals | Same day |
| openFDA `drug/drugsfda` | NDA/BLA original + efficacy-supplement approvals; ANDA count | ~1–7 days |
| openFDA `transparency/crl` | Complete Response Letters FDA has published | Days to weeks |
| openFDA `device/pma` | Original PMA approvals | ~1–3 weeks |
| openFDA `drug/` + `device/enforcement` | Class I recalls | ~1–3 weeks |
| FDA warning-letter table | Warning letters from drug, biologic and device centers | Posted weekly (Tue) |

**Known gaps:** 510(k) clearances, De Novo grants, 483s, Breakthrough designations and most
PDUFA outcomes are not covered by these feeds. The digest step fills part of that with web search.

## Run locally
```bash
python3 -m fda_agent.fetch --no-state --days 7 --out out/new_items.json
```
Requires network access to `www.fda.gov`, `api.fda.gov`, `www.accessdata.fda.gov`, and `www.federalregister.gov`.
