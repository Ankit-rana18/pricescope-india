# PIN codes and published fee policies

## India Post PIN directory

Without the directory, PriceScope checks only a PIN code's **format** and says so
("Format checked only"). With it, PIN codes are confirmed to exist and the comparison page
shows the area.

**Source:** data.gov.in → "All India Pincode Directory till last month" (Department of
Posts, updated monthly, released under the National Data Sharing and Accessibility Policy):
<https://www.data.gov.in/resource/all-india-pincode-directory-till-last-month>

1. Open the page, click **Download** and choose **CSV**. data.gov.in may ask for a name,
   email and purpose before the download starts.
2. Save it as `data/pincode_directory.csv` in this repository (the `data/` folder is
   git-ignored).
3. In `.env`: `PRICESCOPE_PINCODE_DIRECTORY_FILE=../data/pincode_directory.csv`
   (relative to `backend/`), then restart the API.

Either published shape works. Only `pincode` and `officename` are required; `district`,
`statename`, `divisionname` and `circlename` are used when present. The resource page
currently lists circle / region / division / office / pincode only. In that case the area
shown is the postal circle, and the state is **not** guessed from it (some circles cover
several states). Malformed rows are skipped.

## Published fee policies (estimated fees)

When a marketplace doesn't report a fee for an offer (status UNKNOWN), a **published
policy** can fill it in as an **estimate**:

- Only UNKNOWN fees are filled. A fee the marketplace reported always wins.
- Shown as "≈ ₹40", with the source in the notes, and the total is labelled
  **estimated final price**.
- Estimated prices are ranked, but **after** fully verified ones, and never get the
  "Cheapest verified" highlight. A cheaper estimated option is mentioned in the summary
  with the reason.
- If two policies disagree for the same fee, none is applied.

### Adding a policy

With Google Sheets storage, add a row to the `delivery_fees` tab:

| Column | Example | Notes |
|---|---|---|
| `marketplace_id` | id from the `marketplaces` tab | |
| `fee_type` | `DELIVERY` | `DELIVERY`, `HANDLING`, `PLATFORM`, `SMALL_CART`, `OTHER` |
| `amount` | `40` | rupees |
| `source` | `PUBLISHED_POLICY` | |
| `source_url` | `https://…` | the marketplace's own policy page; **https required** |
| `conditions` | `{"below_order_value":"500"}` | see below; `{}` for none |
| `effective_from` | `2026-12-01` | |
| `effective_to` | *(empty)* or `2027-03-31` | |

Supported conditions (anything else makes the policy be skipped, never guessed):

- `below_order_value`: the fee applies below this order value and is ₹0 at or above it.
- `pincode_prefixes`: e.g. `["110","122"]`; the policy covers only those PIN codes.

`id`, `created_at` and `updated_at` may be left empty on hand-typed rows. Policies are
re-read every 5 minutes. Rows that fail validation are logged and skipped.

Only enter what the marketplace actually publishes, with its link. Demo mode uses its own
fictional policy from the demo catalog and never reads this tab.
