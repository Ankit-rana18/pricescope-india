# Product matching

Code: `backend/app/services/matching/`. The question it answers: **is this listing the
exact same purchasable item** (same brand, model/recipe, size, pack count, colour, storage)?

## Rules (first that applies decides)

| # | Condition | Result |
|---|---|---|
| 1 | Same marketplace and listing ID (the link you pasted) | EXACT |
| 2 | Brand, model number, net quantity, pack count, colour, storage or RAM differ (when both sides state them) | **MISMATCH**, always |
| 3 | Both have a valid barcode (GS1 check digit verified): different | MISMATCH |
| 3 | …equal, nothing ambiguous, titles not wildly different | EXACT |
| 3 | …equal, but an attribute is ambiguous ("+ 1 kg free") or titles disagree (< 40%) | PROBABLE |
| 4 | Same brand + same model number, nothing ambiguous | EXACT |
| 5 | Same brand + same size/pack/variant + title similarity ≥ 85% | PROBABLE |
| 6 | Anything else | UNVERIFIED |

Only **EXACT** results are ranked. PROBABLE and UNVERIFIED are shown so you can inspect them.

## Normalisation details

- **Barcodes:** EAN-13, UPC-A and GTIN-14 forms compare equal; a barcode with a wrong check
  digit is ignored (with a warning) so a typo can't force a mismatch or a false exact match.
- **Model numbers:** `NX2-8128`, `nx2 8128` and `NX2/8128` are the same.
- **Brands:** case, punctuation, `&`/`and` and spacing are folded (`One Plus` = `OnePlus`);
  known alternate spellings live in `brand_aliases.json` (same brand only, never sub-brands).
  If one listing has no brand field, a brand at the start of its title counts.
- **Title similarity (RapidFuzz):** sizes, pack words and the brand are removed first; the
  score is the average of order-insensitive and subset-tolerant ratios. It separates
  PROBABLE from UNVERIFIED and is shown as a reason; it never creates EXACT or beats a veto.

## Optional AI review (off by default)

Enable with `PRICESCOPE_LLM_REVIEW_ENABLED=true` and Anthropic credentials (for example
`ANTHROPIC_API_KEY`) on the server. Claude (default `claude-opus-5-5`, low effort, structured
JSON output, server-side refusal fallback) reviews only PROBABLE / UNVERIFIED candidates,
at most 6 per comparison (configurable), with verdicts cached per listing pair.

| Verdict | Effect |
|---|---|
| "same product", high confidence, no conflicts | UNVERIFIED → PROBABLE (never EXACT) |
| "different product", high/medium confidence | PROBABLE → UNVERIFIED (never MISMATCH) |
| anything else, errors, timeouts, refusals | no change |

EXACT and MISMATCH results are never sent for review. Only product data (titles, brands,
barcodes, attributes) is sent, wrapped as data so listing text can't act as instructions.
It costs API tokens per reviewed pair.
