# FDA Digest — instructions for the scheduled Claude run

Audience: a healthcare-dedicated hedge fund CIO (pan-healthcare, ex-HCIT; $5–25mm positions
in listed equities; 18–24 mo longs, 6–9 mo shorts). The digest exists to surface **investable
signal**, not to summarise everything the FDA did.

## 1. Inputs
- `out/new_items.json` from `python -m fda_agent.fetch` (only items not sent before).
- `fda_agent/watchlist.txt`: tickers/companies/assets that always get reported, however small the item.
- Web search, to supplement. FDA does **not** publish most PDUFA outcomes, CRLs or AdComm votes in
  real time; companies disclose them in press releases or 8-Ks. Search for
  "FDA approval", "complete response letter", "PDUFA", "advisory committee vote", "clinical hold",
  "refuse to file", "breakthrough therapy designation" from the last 24–72h (72h on Mondays).

## 2. Triage — keep only items that pass at least one test
| Tier | Examples | Treatment |
|---|---|---|
| **1 — Price-moving** | Novel NDA/BLA approval or CRL at a listed company; AdComm vote/outcome; clinical hold; FDA statement on a specific pending application; boxed warning/market withdrawal; warning letter or OAI at a listed company's commercial site; Class I recall of a material product line | Full entry |
| **2 — Thesis-relevant** | New-indication approvals; label expansions; major guidances (rare disease, CGT, accelerated approval, biosimilar interchangeability, 505(b)(2), compounding, LDTs); AdComm meeting notices (date set); FDA leadership/policy changes; user-fee or priority-voucher changes; first generics or biosimilars against branded franchises | Short entry |
| **3 — Drop** | Food, tobacco, cosmetics, animal; webpage housekeeping ("data files updated", rosters, SOPP lists); private-company recalls with no listed read-through; paperwork notices | Count only, in footer |

Always include watchlist hits, whatever the tier.

## 3. For each kept item
- **Company / ticker.** Map sponsors to listed tickers (parent for subsidiaries, e.g. "Genzyme, a Sanofi Co." → SNY). If the company is private, or you're unsure of the ticker, write "private" or "ticker unverified". Never guess a ticker.
- **What happened.** One factual line with the primary FDA source link (and the company PR link, if from search).
- **So what** (mark it *[Assessment]*). Materiality to the company: rough share of revenue or pipeline value if known, whether this was expected (priced in) or a surprise, and whether a label/REMS/boxed warning changes the commercial case.
- **Read-throughs** (mark it *[Speculative]* when inferential). Competitors, same-mechanism peers, CDMOs/API suppliers named in warning letters, tools/services exposure.
- **Flags.** Call out direct CMS/payor dependency, "stroke-of-the-pen" reimbursement risk, or customer concentration whenever an item touches them.

## 4. Email format (HTML)
Subject: `FDA Digest — {Day DD Mon YYYY} — {N} Tier-1 / {M} Tier-2`

1. **Top 3** — at most 3 bullets: the items most likely to move a listed stock.
2. **Tier 1** — a table: Ticker | Event | Source | So what.
3. **Tier 2** — bullets, grouped as Drugs/Biologics · Devices · Policy/Guidance · Enforcement.
4. **Upcoming 7 days** — known PDUFA dates and AdComm meetings (from Federal Register items + search). Mark any date not confirmed by a primary source "(unverified)".
5. **Footer** — the dropped Tier-3 count by category; any `source_errors` from the fetch; this line: "Generated automatically; verify before trading."

Keep it scannable, around 1 page. No preamble, no flattery. If nothing clears Tier 2, send a one-line
"No investable FDA signal today" email that still carries the footer.

## 5. Accuracy rules
- Never invent approvals, dates, tickers or numbers. If a fact comes only from web search and has no primary source, label it "(per company PR)" or "(unverified)".
- openFDA data lags 1–10 days, so an approval can show up days after it was announced. If it was already in the news, say "(confirmed in FDA database; announced {date})" instead of presenting it as new.
