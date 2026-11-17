"""Synthetic tenants, users, catalogue snapshots and executable demo policies."""

from datetime import timedelta


SERVICES = {
    "search_product": "Find a product",
    "compare_products": "Compare products",
    "track_order": "Track an order",
    "cancel_order": "Cancel an order",
    "modify_order": "Change delivery preference",
    "request_return": "Request a return or replacement",
    "refund_status": "Check refund status",
    "policy_question": "Ask about a store policy",
    "create_ticket": "Open a support ticket",
    "request_human": "Talk to an agent",
    "ticket_status": "Check a ticket",
}
INTENTS = set(SERVICES) | {"greet", "goodbye", "out_of_scope"}
STORES = {
    "nook": {
        "name": "Nook & Loom", "specialty": "Home & workspace", "days": 14,
        "shipping": 1999, "delivery": "3–5", "warranty": 12, "fee": 89,
        "customers": [("DEMO101", "Maya Sen"), ("DEMO102", "Kunal Rao")],
        "products": [
            ("NL-101", "Arc Desk Lamp", "Lighting", "Nook Studio", 179900, 9, "lamp", "Warm light and an adjustable shade."),
            ("NL-102", "Dune Desk Mat", "Desk", "Nook Studio", 79900, 26, "mat", "A soft cork surface for a keyboard and mouse."),
            ("NL-103", "Loop Cable Set", "Desk", "Nook Studio", 39900, 31, "cable", "Six reusable cable clips for a tidy setup."),
            ("NL-104", "Knot Planter", "Decor", "Earthline", 129900, 4, "planter", "A glazed stoneware pot with a drainage tray."),
            ("NL-105", "Fold Laptop Stand", "Desk", "Earthline", 229900, 0, "stand", "Aluminium stand with four height settings."),
            ("NL-106", "Personalised Name Plate", "Decor", "Nook Studio", 109900, 6, "plate", "Made to order with custom engraving."),
        ],
    },
    "trail": {
        "name": "Trail & Trek", "specialty": "Outdoor gear", "days": 30,
        "shipping": 2499, "delivery": "4–7", "warranty": 24, "fee": 119,
        "customers": [("DEMO101", "Ishaan Roy"), ("DEMO102", "Tara Das")],
        "products": [
            ("TT-101", "Ridge Daypack", "Bags", "Trailworks", 249900, 11, "pack", "An eighteen-litre bag with a rain cover."),
            ("TT-102", "Summit Steel Bottle", "Hydration", "Trailworks", 94900, 25, "bottle", "Insulated steel bottle with a 750 ml capacity."),
            ("TT-103", "Drift Dry Bag", "Bags", "Trailworks", 64900, 19, "drybag", "Five litres with a roll-top closure."),
            ("TT-104", "Cairn Trekking Pole", "Equipment", "Fieldstone", 219900, 6, "pole", "Telescopic aluminium pole with a cork grip."),
            ("TT-105", "Glade Headlamp", "Lighting", "Fieldstone", 149900, 0, "lamp", "Compact headlamp with three brightness modes."),
            ("TT-106", "Personalised Trail Tag", "Accessories", "Trailworks", 59900, 7, "plate", "Laser-engraved tag made to order."),
        ],
    },
}
PREFERENCES = ("Leave with reception", "Hand to recipient", "Call on arrival")
RETURN_REASONS = ("Damaged", "Wrong item", "Changed my mind")
RESOLUTIONS = ("Return", "Replacement")
ISSUE_CATEGORIES = ("Delivery", "Product", "Payment status", "Other")


def money(paise):
    rupees, remainder = divmod(paise, 100)
    digits = str(rupees)
    last = digits[-3:]
    prefix = digits[:-3]
    groups = []
    while prefix:
        groups.insert(0, prefix[-2:])
        prefix = prefix[:-2]
    return "₹" + ",".join([*groups, last]) + f".{remainder:02d}"


def policies(slug, store):
    """A passage per approved policy topic, with versions and effective dates."""
    start = "2025-01-01"
    passages = [
        ("shipping", "Shipping and delivery", "3.1", "shipping charges postage free delivery courier transit arrival time doorstep dispatch parcel rural shipping costs rates standard days minimum threshold",
         f"Standard delivery is estimated at {store['delivery']} business days. Shipping is free on orders of ₹{store['shipping']:,} or more. Below that, the standard charge is ₹{store['fee']}."),
        ("returns", "Returns and replacements", "3.2", "return send back weeks days damaged defect exchange replacement wrong item unwanted changed mind return window deadline eligibility personalised engraved personalised exceptions",
         f"Request an eligible return or replacement within {store['days']} calendar days of delivery. Personalised items are excluded. The team reviews the condition and requested resolution."),
        ("warranty", "Product warranty", "2.1", "manufacturer guarantee warranty manufacturing defect months coverage coverage repair fault workmanship warranty length",
         f"A {store['warranty']}-month warranty covers manufacturing defects. A support agent reviews proof of purchase and the reported issue."),
        ("refund", "Refund processing", "2.2", "refund credit money reimbursement bank processing timeline payment received original method after approval how long refund",
         "After approval, a refund typically takes 5–7 business days on the original payment method. Review your order's refund status for a recorded provider update."),
        ("cancellation", "Order cancellation", "1.4", "cancel void order stop purchase dispatch packed fulfilment locked rules policy when allowed cancellation cut off",
         "Orders in the confirmed or packing state can be cancelled before dispatch. Review the order and explicitly confirm the cancellation."),
        ("changes", "Delivery preference changes", "1.3", "modify update change delivery instructions address reception hand over call recipient fulfilment packing preference change order",
         "You can update a delivery preference while an order is confirmed or packing. Contact support for a full address or item change."),
        ("payments", "Payment methods", "1.2", "accepted payments upi ways pay cash card digital checkout methods credit debit card cash on delivery",
         "The sample checkout policy lists UPI and cards as supported payment methods. Never enter payment credentials in the support desk."),
        ("support", "Support hours", "1.2", "customer service working hours human agent weekend office open time live support when contact help desk",
         "The sample support desk operates Monday through Saturday, 9 AM to 6 PM IST. Tickets can be submitted at any time."),
    ]
    entries = [(slug, f"{slug.upper()}-{topic.upper()}", topic, title, version,
                start, None, "approved", keywords, body) for topic, title, version, keywords, body in passages]
    entries.extend([
        (slug, f"{slug.upper()}-RETURNS", "returns", "Earlier returns policy", "1.0", "2023-01-01",
         "2024-12-31", "approved", "legacy return deadline 60 days", "The earlier window was 60 days."),
        (slug, f"{slug.upper()}-SHIPPING-DRAFT", "shipping", "Shipping proposal", "4.0", start,
         None, "draft", "shipping free nationwide shipping delivery", "Proposed shipping upgrade under review."),
        (slug, f"{slug.upper()}-WARRANTY-FUTURE", "warranty", "Future warranty policy", "3.0", "2099-01-01",
         None, "approved", "warranty future guarantee", "Future warranty policy under a later effective date."),
        (slug, f"{slug.upper()}-PAYMENT-REVOKED", "payments", "Revoked payment notice", "1.0", start,
         None, "revoked", "cash payment coupons methods", "Revoked payment notice."),
    ])
    return entries


def seed(connection, today):
    order_specs = [(2401, "DEMO101", "Packing", 1), (2402, "DEMO101", "Dispatched", 3),
                   (2403, "DEMO101", "Delivered", 5), (2404, "DEMO101", "Delivered", 10),
                   (2405, "DEMO102", "Packing", 1), (2406, "DEMO101", "Delivered", 43),
                   (2407, "DEMO101", "Confirmed", 0), (2408, "DEMO102", "Delivered", 4),
                   (2409, "DEMO101", "Delivered", 20)]
    for slug, store in STORES.items():
        connection.execute("INSERT INTO tenants VALUES (?,?,?,?)", (slug, store["name"], store["days"], "Active"))
        connection.executemany("INSERT INTO customers VALUES (?,?,?)",
                               [(slug, ident, name) for ident, name in store["customers"]])
        connection.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)",
                               [(slug, *p, "INR") for p in store["products"]])
        connection.executemany("INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,?,?,?)", policies(slug, store))
        for number, customer, state, age in order_specs:
            order = f"ORD-{number}"
            day = (today - timedelta(days=age)).isoformat()
            product = store["products"][{2402: 1, 2404: 2, 2405: 3, 2406: 1, 2407: 4, 2408: 2}.get(number, 0)]
            carrier = "Sample Parcel" if state in {"Dispatched", "Delivered"} else None
            secondary = store["products"][5] if number == 2403 else None
            total = product[4] + (secondary[4] if secondary else 0)
            connection.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (slug, order, customer, state, day, day if state == "Delivered" else None,
                                "Hand to recipient", carrier, f"{slug.upper()}-SHIP-{number}" if carrier else None,
                                total, "INR"))
            for line, item in enumerate([product] + ([secondary] if secondary else []), 1):
                connection.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)",
                                   (slug, order, f"{line:02}", item[0], item[1], 1, item[4], item[0].endswith("106")))
        connection.execute("INSERT INTO refunds VALUES (?,?,?,?,?,?,?)",
                           (slug, "RF-901", "ORD-2404", "Processed" if slug == "nook" else "In review",
                            39900 if slug == "nook" else 64900, "INR", today.isoformat()))
