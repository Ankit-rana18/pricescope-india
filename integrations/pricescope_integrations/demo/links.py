"""Pasteable URLs for demo listings.

They use each marketplace's URL *shape* (so they go through the normal parser), with IDs
that are clearly marked DEMO or sit in ranges no real listing uses. The app never links to
them; they only exist to be pasted into the form.
"""

from pricescope_integrations.models import Marketplace

_FLIPKART_ITEMS = {
    "DEMOSALT00000001": "itmdemosalt01",
    "DEMOBTTR00000002": "itmdemobttr02",
    "DEMOPHNE00000003": "itmdemophne03",
    "DEMOPHNE00000004": "itmdemophne04",
    "DEMODTRG00000005": "itmdemodtrg05",
}


def canonical_demo_url(marketplace: Marketplace, external_id: str) -> str:
    if marketplace is Marketplace.AMAZON_IN:
        return f"https://www.amazon.in/dp/{external_id}"
    if marketplace is Marketplace.FLIPKART:
        item = _FLIPKART_ITEMS.get(external_id, "itmdemo000000")
        return f"https://www.flipkart.com/demo-product/p/{item}?pid={external_id}"
    if marketplace is Marketplace.BIGBASKET:
        return f"https://www.bigbasket.com/pd/{external_id}/demo-product/"
    if marketplace is Marketplace.BLINKIT:
        return f"https://blinkit.com/prn/demo-product/prid/{external_id}"
    return f"https://www.zeptonow.com/pn/demo-product/pvid/{external_id}"
