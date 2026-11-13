"""Write the worst-case / empty / one API fixtures used by the dev server's data toggle (break-ui).
Every value is realistic or sits exactly at the limit the API accepts (docs/API.md).
Usage: python scripts/ui-fixtures/make_fixtures.py"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
now = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

COMMENT_500 = (
    "I've been coming here since freshers' week and it's honestly the reason I passed second year. "
    "The salted caramel Welsh cakes are unreal, the oat flat white is the best in Cathays, and there's a plug at "
    "literally every seat.\n\n"
    "Small things: it gets packed after 12 in exam season, so book a study room if you need quiet. The Wi-Fi "
    "dropped once during a video call but the staff sorted it in a minute. Also the Cwtch Deal is unbeatable "
    "value. Diolch o galon to everyone behind the counter!"
)
COMMENT_500 = (COMMENT_500 + " " + "x" * 500)[:500].rstrip(" x")
assert 20 <= len(COMMENT_500) <= 500, len(COMMENT_500)

reviews_worst = [
    {"reviewId": "rv_01WORST000000000000000001", "rating": 5, "tags": ["best-welsh-cakes", "plenty-of-plugs", "good-value"],
     "comment": COMMENT_500, "displayName": "Christopher Montgomery-Ashford", "courseYear": "Postgrad", "verified": True,
     "createdAt": iso(now - timedelta(days=3 * 365))},
    {"reviewId": "rv_01WORST000000000000000002", "rating": 1, "tags": [], "comment": "Great coffee, ta xx",
     "displayName": "Jo", "courseYear": None, "verified": False, "createdAt": iso(now - timedelta(seconds=20))},
    {"reviewId": "rv_01WORST000000000000000003", "rating": 3, "tags": ["fast-wifi"],
     "comment": "Wi-Fi's fine but bookmark this: https://example.com/workspaces/cathays/study-groups/q3-revision/docs/9f8e7d6c5b4a?tab=comments&filter=unresolved <script>alert(1)</script> &amp; **bold**",
     "displayName": "🦊 Fox", "courseYear": "1st year", "verified": False, "createdAt": iso(now - timedelta(days=12))},
    {"reviewId": "rv_01WORST000000000000000004", "rating": 4, "tags": ["cosy", "quiet", "friendly-staff"],
     "comment": "أفضل مقهى للدراسة في كارديف. The staff are lovely and it's always warm.",
     "displayName": "نور الهدى عبد الرحمن", "courseYear": "Staff", "verified": True, "createdAt": iso(now - timedelta(days=330))},
    {"reviewId": "rv_01WORST000000000000000005", "rating": 5, "tags": ["great-coffee"],
     "comment": "Đặng here 👩🏽‍💻 Bổ sung: cà phê ngon, bánh Welsh rất tuyệt vời. Mae'r cacennau cri yn wych!",
     "displayName": "Đặng Thị Ngọc Hân", "courseYear": "4th year", "verified": False, "createdAt": iso(now - timedelta(hours=26))},
]
admin_extra = lambda r, i: {**r, "status": "pending", "flagged": i == 0, "toxicityScore": 0.612 if i == 0 else (None if i % 2 else 0.04),  # noqa: E731
                             "toxicityLabels": ["INSULT"] if i == 0 else [], "moderatedAt": None}

menu_worst = {
    "currency": "GBP",
    "sections": [
        {"id": "hot-coffee", "title": "Hot coffee", "sizes": {"regular": "240ml", "large": "350ml"}, "items": [
            {"id": "flavoured-latte", "name": "Iced oat-milk salted caramel and vanilla latte with an extra shot",
             "description": "Double-shot espresso, salted caramel and vanilla syrups, oat milk, cream and a drizzle. Ask for it decaf.",
             "prices": {"regular": 5000, "large": 5000}, "tags": ["V", "VG-available", "GF-available"],
             "allergens": ["celery", "gluten", "crustaceans", "egg", "fish", "lupin", "milk", "molluscs", "mustard", "nuts", "peanuts", "sesame", "soya", "sulphites"],
             "soldOut": True},
            {"id": "espresso", "name": "Tea", "prices": {"regular": 0}, "tags": [], "allergens": [], "soldOut": False},
        ]},
        {"id": "welsh-cakes", "title": "Welsh cakes", "note": "Baked fresh every morning, from 07:00, on a proper bakestone",
         "offers": [{"label": "Any 3", "price": 300}, {"label": "Box of 6", "price": 550}, {"label": "Box of 12 for the whole flat", "price": 1000}],
         "items": [{"id": "white-chocolate-raspberry", "name": "White chocolate & raspberry", "description": "Sweet and a bit sharp",
                    "prices": {"each": 110}, "tags": ["V"], "allergens": ["gluten", "milk", "egg", "soya"], "soldOut": True}]},
    ],
    "deals": [{"id": "cwtch-deal", "name": "The Cwtch Deal: any latte-style drink, hot or iced, with two Welsh cakes", "description": "Any regular latte, cappuccino, flat white or flavoured latte, hot or iced, plus 2 Welsh cakes",
               "price": 480, "normalPrice": {"from": 520, "to": 640}, "studentOnly": True, "active": True},
              {"id": "exam-fuel", "name": "Exam Fuel", "description": "Any large coffee, hot or iced, plus any 3 Welsh cakes", "price": 580, "when": "Exam season only", "studentOnly": True, "active": False}],
}

status_worst = {"level": "packed", "label": "Packed", "message": "Society takeover until 6pm, back room only. Sofas upstairs!", "updatedAt": iso(now), "open": True,
                "hoursToday": {"opens": "08:00", "closes": "21:00"}}
assert len(status_worst["message"]) <= 60, len(status_worst["message"])

bookings_worst = {"date": now.strftime("%Y-%m-%d"), "bookings": [
    {"reference": "CC-7F3K9Q", "type": "group", "classKind": None, "time": "08:00", "partySize": 20,
     "name": "Christopher Alexander Montgomery III, Treasurer of the Cardiff Welsh Society",
     "email": "bartholomew.fitzgerald@northwind-industries-holdings.example.com",
     "society": "Cardiff University Welsh Language and Culture Society (Cymdeithas Gymraeg)",
     "notes": "Two wheelchair users, so the ground floor please.\n\nWe'll bring a cake for a 21st birthday, and need a plug for the projector. Can we pay for drinks on one bill? Diolch!"},
    {"reference": "CC-ABCDEF", "type": "class", "classKind": "latte-art", "time": "10:00", "partySize": 1, "name": "J", "email": "a@b.co", "society": None, "notes": None},
    {"reference": "CC-ZZZZZZ", "type": "room", "classKind": None, "time": "14:00", "partySize": 6, "name": "Aleksandra Wiśniewska-Kowalczyk",
     "email": "first.last+billing-notifications@example.com", "society": None, "notes": "<script>alert(1)</script> &amp;"},
]}

summary_many = {"averageRating": 4.3, "count": 1284, "topTags": ["best-welsh-cakes", "plenty-of-plugs", "good-value"]}
fixtures = {
    "worst": {
        "/api/reviews": {"summary": summary_many, "reviews": reviews_worst, "nextCursor": "eyJpZCI6InJ2XzAxIn0"},
        "/api/admin/reviews": {"status": "pending", "reviews": [admin_extra(r, i) for i, r in enumerate(reviews_worst)], "nextCursor": "eyJpZCI6InJ2XzAxIn0"},
        "/api/menu": menu_worst,
        "/api/status": status_worst,
        "/api/admin/bookings": bookings_worst,
    },
    "empty": {
        "/api/reviews": {"summary": {"averageRating": None, "count": 0, "topTags": []}, "reviews": [], "nextCursor": None},
        "/api/admin/reviews": {"status": "pending", "reviews": [], "nextCursor": None},
        "/api/menu": {"currency": "GBP", "sections": [], "deals": []},
        "/api/admin/bookings": {"date": now.strftime("%Y-%m-%d"), "bookings": []},
    },
    "one": {
        "/api/reviews": {"summary": {"averageRating": 1.0, "count": 1, "topTags": []}, "reviews": [reviews_worst[1]], "nextCursor": None},
        "/api/admin/reviews": {"status": "pending", "reviews": [admin_extra(reviews_worst[1], 1)], "nextCursor": None},
        "/api/admin/bookings": {"date": now.strftime("%Y-%m-%d"), "bookings": [bookings_worst["bookings"][1]]},
    },
}
for name, data in fixtures.items():
    (HERE / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
print("fixtures written:", ", ".join(fixtures))
