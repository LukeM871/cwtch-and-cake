# API Contract

This is the exact agreement between the **website** and the **backend**. The Lambdas are built to this document (Phases 3–5), their tests check it, and the website calls it (Phase 7).

> Change this document first, then the code. Breaking changes need both sides updated in the same commit.

---

## 1. General rules

| Rule | Value |
|---|---|
| Base path | `/api` on the same domain as the website (through CloudFront) |
| Format | JSON in, JSON out. `Content-Type: application/json` is required on requests with a body (otherwise `415`) |
| Max request body | 4 KB (otherwise `413`) |
| Time zone | All dates and times are **UK local time (Europe/London)**. "Today" and "in the past" use UK time |
| Date format | `YYYY-MM-DD`, for example `2026-11-14` |
| Time format | `HH:MM`, 24-hour, for example `14:00` |
| Text | Trimmed. Control characters removed. Lengths counted in characters |
| Emails | Trimmed and lower-cased before they're compared or stored |
| Unknown fields | Ignored and never stored |
| Honeypot | Every public form has a hidden `website` field. If it isn't empty → a fake success, and nothing is saved |

### Error format (every error looks like this)
```json
{
  "error": "validation",
  "message": "Please check the highlighted fields.",
  "fields": {
    "email": "Enter a valid email address",
    "date": "Classes run on Saturdays only"
  }
}
```
`fields` only appears for `validation` errors. The website shows each message next to its field.

### Status codes
| Code | `error` value | When |
|---|---|---|
| `200` | — | OK (read, cancel, admin update) |
| `201` | — | Booking created |
| `202` | — | Review received (waiting for approval) |
| `400` | `validation` | One or more fields are wrong |
| `401` | `unauthorized` | Admin route without a valid login |
| `403` | `forbidden` | The request didn't come through CloudFront |
| `404` | `not_found` | Booking not found **or** the email doesn't match (deliberately the same) |
| `405` | `method_not_allowed` | Wrong HTTP method |
| `409` | `slot_full` / `already_reviewed` | No space left in the slot / the booking was already used for a review |
| `413` | `too_large` | Body over 4 KB |
| `415` | `unsupported_media_type` | Not JSON |
| `429` | `rate_limited` | Too many requests |
| `500` | `server` | Something broke. The website shows "Sorry, something went wrong, please try again" |

---

## 2. Endpoints at a glance

| Method & path | Who | Purpose | Success | Cache (CloudFront) |
|---|---|---|---|---|
| `POST /api/booking` | Public | Create a booking | `201` | none |
| `POST /api/booking/cancel` | Public | Cancel a booking | `200` | none |
| `GET /api/availability` | Public | Spaces left per slot for one day | `200` | 30 s |
| `GET /api/status` | Public | How busy the café is now | `200` | 30 s |
| `GET /api/menu` | Public | Full menu, deals and sold-out flags | `200` | 5 min |
| `POST /api/reviews` | Public | Leave a review | `202` | none |
| `GET /api/reviews` | Public | Approved reviews and a summary | `200` | 5 min |
| `GET /api/admin/bookings` | Admin | One day's bookings | `200` | none |
| `PUT /api/admin/status` | Admin | Set how busy the café is | `200` | none |
| `PATCH /api/admin/menu/{itemId}` | Admin | Change a price or mark an item sold out | `200` | none |
| `GET /api/admin/reviews` | Admin | Reviews by status (the moderation queue) | `200` | none |
| `POST /api/admin/reviews/{reviewId}` | Admin | Approve or reject a review | `200` | none |

**Change from the plan:** cancelling is `POST /api/booking/cancel`, not `DELETE /api/booking`. Some proxies and tools drop the body of a `DELETE`, and a `POST` is simpler for the website form.

Admin routes need `Authorization: Bearer <Cognito token>`. API Gateway checks the token before the Lambda runs.

---

## 3. Opening hours and what can be booked

**Opening hours:**
- Monday–Friday: 08:00–20:00
- Saturday and Sunday: 09:00–18:00
- During exam season the café is open until 22:00 on weekdays. That's website content only; no extra booking slots.

| Booking `type` | What | Days | Start times | Length | `partySize` | Capacity per slot | What the capacity counts |
|---|---|---|---|---|---|---|---|
| `class` | Latte art or Welsh cake baking class | **Saturdays only** | `10:00`, `14:00` | 90 min | 1–4 | **8 places** | people |
| `room` | Group study room | Every day | Weekdays: `08:00 10:00 12:00 14:00 16:00 18:00`. Weekends: `10:00 12:00 14:00 16:00` | 2 h | 2–6 | **2 rooms** | rooms (1 per booking) |
| `group` | Big society or group table | Every day | Same as `room` | 2 h | 5–20 | **1 table** | tables (1 per booking) |

**Change from the plan:** group tables use the same 2-hour slots as rooms, not "any half hour". That stops two group bookings from overlapping.

**Booking window:** from today up to **60 days ahead**. If the slot is today, its start time must still be at least **30 minutes away**.

---

## 4. Bookings

### `POST /api/booking`
**Request**
```json
{
  "type": "class",
  "classKind": "latte-art",
  "date": "2026-11-14",
  "time": "10:00",
  "partySize": 2,
  "name": "Ffion Roberts",
  "email": "ffion@example.com",
  "society": "",
  "notes": "One of us is left-handed!",
  "website": ""
}
```

| Field | Required | Rules |
|---|---|---|
| `type` | ✅ | `class` · `room` · `group` |
| `classKind` | for `class` | `latte-art` · `welsh-cakes` (ignored for other types) |
| `date` | ✅ | Valid date, today up to 60 days ahead. A `class` must be on a Saturday |
| `time` | ✅ | One of the start times in §3 for that type and day |
| `partySize` | ✅ | Whole number in the range for that type (§3) |
| `name` | ✅ | 1–80 characters |
| `email` | ✅ | Valid email format, ≤ 254 characters |
| `society` | for `group` | 1–80 characters (ignored for other types) |
| `notes` | ❌ | ≤ 500 characters |
| `website` | — | Honeypot. Must be empty |

**Success: `201`**
```json
{
  "reference": "CC-7F3K9Q",
  "type": "class",
  "classKind": "latte-art",
  "date": "2026-11-14",
  "time": "10:00",
  "partySize": 2,
  "emailSent": true
}
```
- `emailSent` is `false` if the confirmation email couldn't be sent. **The booking still counts.**
- If the honeypot is filled in, the response is a normal-looking `201` with a random reference, nothing is saved and no email is sent.

**Slot full: `409`**
```json
{ "error": "slot_full", "message": "Sorry, that slot has just been taken. Please pick another time." }
```

**How double-booking is prevented:** the booking is saved and the slot counter goes up **in one DynamoDB transaction** (`TransactWriteItems`). The counter update has a condition: `booked + units <= capacity`, where `units` is `partySize` for classes and `1` for rooms and groups. If two people try for the last space at the same moment, one transaction succeeds and the other fails, and the one that fails gets `409`. Nothing is ever half-saved.

**Reference format:** `CC-` + 6 characters from the Crockford base32 alphabet `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (no I, L, O or U). That gives about 1 billion combinations. The save uses `attribute_not_exists(pk)`, so a clash (very unlikely) is retried with a new reference.

### `POST /api/booking/cancel`
**Request**
```json
{ "reference": "CC-7F3K9Q", "email": "ffion@example.com", "website": "" }
```
- `reference` must match `^CC-[0-9A-HJKMNP-TV-Z]{6}$` (case-insensitive, stored upper-case).
- The booking must not have started yet.

**Success: `200`**
```json
{ "reference": "CC-7F3K9Q", "cancelled": true }
```
- **`404`** if the reference doesn't exist **or** the email doesn't match. It's the same response either way.
- **`400`** with `fields.reference = "This booking has already started"` if it's in the past.
- How it works: read the booking → in **one transaction**, delete it (on condition that the email matches) and take its `units` off the slot counter. A "booking cancelled" email is then sent.

### `GET /api/availability?type=room&date=2026-11-14`
| Query | Rules |
|---|---|
| `type` | `class` · `room` · `group` |
| `date` | Same rules as booking |

**Success: `200`**
```json
{
  "type": "room",
  "date": "2026-11-14",
  "slots": [
    { "time": "10:00", "capacity": 2, "booked": 2, "available": 0 },
    { "time": "12:00", "capacity": 2, "booked": 1, "available": 1 },
    { "time": "14:00", "capacity": 2, "booked": 0, "available": 2 },
    { "time": "16:00", "capacity": 2, "booked": 0, "available": 2 }
  ]
}
```
- Today's slots that start in under 30 minutes are left out.
- If the type isn't available that day (a `class` on a non-Saturday) → `slots: []`.
- Cached for 30 seconds, so the numbers can be up to 30 seconds old. The booking transaction is always the final check.

---

## 5. Café status and menu

### `GET /api/status`
**Success: `200`**
```json
{ "level": "busy", "label": "Busy", "message": "About 10 seats free", "updatedAt": "2026-11-14T13:05:00Z", "open": true }
```
- `level` is one of `quiet` · `steady` · `busy` · `packed` · `unknown` · `closed`.
- It's `unknown` if no one has updated the status in the last **3 hours**, so the site never shows an old "Quiet".
- It's `closed` outside opening hours, whatever was last set.

### `GET /api/menu`
**Success: `200`**
```json
{
  "currency": "GBP",
  "sections": [
    {
      "id": "hot-coffee",
      "title": "Hot coffee",
      "sizes": { "regular": "240ml", "large": "350ml" },
      "items": [
        {
          "id": "latte",
          "name": "Latte",
          "prices": { "regular": 350, "large": 390 },
          "tags": ["V"],
          "allergens": ["milk"],
          "soldOut": false
        }
      ]
    },
    {
      "id": "welsh-cakes",
      "title": "Welsh cakes",
      "items": [
        {
          "id": "white-chocolate-chip",
          "name": "White chocolate chip",
          "description": "Creamy white chocolate chips",
          "prices": { "each": 110 },
          "tags": ["V"],
          "allergens": ["gluten", "milk", "egg"],
          "soldOut": true
        }
      ]
    }
  ],
  "deals": [
    {
      "id": "cwtch-deal",
      "name": "The Cwtch Deal",
      "description": "Any regular latte, cappuccino, flat white or flavoured latte, hot or iced, plus 2 Welsh cakes",
      "price": 480,
      "studentOnly": true,
      "active": true
    }
  ]
}
```
- **Prices are whole pence** (`350` = £3.50). That avoids rounding errors with decimals.
- Allowed `tags`: `V` · `VG` · `GF-available`.
- Allowed `allergens` (from the UK's 14 allergens): `gluten` · `milk` · `egg` · `nuts` · `peanuts` · `soya` · `sesame` · `sulphites` · and the others as needed.
- Section ids: `hot-coffee` · `iced` · `tea-and-others` · `welsh-cakes` · `bakes`.

---

## 6. Reviews

### `POST /api/reviews`
**Request**
```json
{
  "rating": 5,
  "tags": ["best-welsh-cakes", "fast-wifi"],
  "comment": "Salted caramel Welsh cakes got me through my dissertation.",
  "displayName": "Ffion R.",
  "courseYear": "3rd year",
  "reference": "CC-7F3K9Q",
  "email": "ffion@example.com",
  "website": ""
}
```

| Field | Required | Rules |
|---|---|---|
| `rating` | ✅ | Whole number 1–5 |
| `tags` | ❌ | Up to 3, no repeats, from: `best-welsh-cakes` · `great-coffee` · `quiet` · `fast-wifi` · `plenty-of-plugs` · `friendly-staff` · `good-value` · `cosy` |
| `comment` | ✅ | 20–500 characters |
| `displayName` | ✅ | 1–30 characters. Shown as given. The website suggests "first name + initial" |
| `courseYear` | ❌ | `1st year` · `2nd year` · `3rd year` · `4th year` · `Postgrad` · `Staff` · `Visitor` |
| `reference` + `email` | ❌, but both or neither | For the **"Verified visit"** badge |
| `website` | — | Honeypot |

**What happens, in order:**
1. Honeypot and field checks. If they fail → `400`.
2. **Word filter:** obvious slurs or abuse → `400`, with `fields.comment = "Please keep reviews friendly"`.
3. **Amazon Comprehend toxicity check** on the comment:
   - very toxic (score ≥ 0.8) → `400`, same message
   - borderline (0.5–0.8) → saved with `flagged: true` for the admin to look at
   - if Comprehend is unavailable → saved as normal (the admin still moderates everything)
4. **If a reference and email were given:** the booking must exist, the email must match and the booking's date must have passed.
   - If the reference or email is wrong → `404`.
   - If the date hasn't passed → `400`.
   - In **one transaction**, the booking is marked `reviewed` (on condition that it wasn't already) and the review is saved with `verified: true`.
   - If the booking was already used → `409 already_reviewed`.
5. Saved with `status: "pending"`. **The email is never stored on the review.**

**Success: `202`**
```json
{ "reviewId": "rv_01JC3X8Z9Q", "status": "pending", "verified": true,
  "message": "Diolch! Thanks for your review. It'll appear once it's been checked." }
```

### `GET /api/reviews?limit=20&cursor=...`
- `limit`: 1–50, default 20.
- `cursor`: from the previous response, to load more.

**Success: `200`**
```json
{
  "summary": { "averageRating": 4.7, "count": 128, "topTags": ["best-welsh-cakes", "cosy", "fast-wifi"] },
  "reviews": [
    {
      "reviewId": "rv_01JC3X8Z9Q",
      "rating": 5,
      "tags": ["best-welsh-cakes", "fast-wifi"],
      "comment": "Salted caramel Welsh cakes got me through my dissertation.",
      "displayName": "Ffion R.",
      "courseYear": "3rd year",
      "verified": true,
      "createdAt": "2026-11-15T10:12:00Z"
    }
  ],
  "nextCursor": null
}
```
Only `approved` reviews, newest first. The summary is worked out from approved reviews only.

---

## 7. Admin (Cognito login required)

| Route | Request | Response |
|---|---|---|
| `GET /api/admin/bookings?date=YYYY-MM-DD` | — | `{ "date": "...", "bookings": [ { reference, type, classKind, time, partySize, name, email, society, notes } ] }`, sorted by time |
| `PUT /api/admin/status` | `{ "level": "busy", "message": "About 10 seats free" }` (message ≤ 60 characters, optional) | The new status (same shape as `GET /api/status`) |
| `PATCH /api/admin/menu/{itemId}` | Any of `{ "soldOut": true, "prices": { "regular": 360 } }` | The updated item |
| `GET /api/admin/reviews?status=pending` | `status`: `pending` · `approved` · `rejected` | `{ "reviews": [ ...same as public, plus "status", "flagged", "toxicityScore" ] }` |
| `POST /api/admin/reviews/{reviewId}` | `{ "action": "approve" }` or `{ "action": "reject" }` | `{ "reviewId": "...", "status": "approved" }` |

`soldOut` flags are reset to `false` automatically at **06:00 UK time** every morning, when the Welsh cakes are baked fresh. This runs on an EventBridge schedule, using the admin Lambda with a special event.

---

## 8. Emails (Amazon SES)

| When | Subject | Contains |
|---|---|---|
| Booking created | "Your Cwtch & Cake booking: CC-7F3K9Q" | Type, date, time, party size, café address area (Cathays), how to cancel (reference + link to the Cancel page) |
| Booking cancelled | "Booking cancelled: CC-7F3K9Q" | Confirmation that it's cancelled |

- Plain text plus simple HTML. No tracking pixels.
- The footer says "Fictional café, a portfolio project".
- In the SES sandbox, emails only reach verified addresses. If sending fails, the booking or cancellation still succeeds (`emailSent: false`).

---

## 9. Data model (DynamoDB, on-demand)

| Table | Key | Main attributes | Extras |
|---|---|---|---|
| `cwtch-and-cake-bookings` | `pk` = reference (`CC-7F3K9Q`) | type, classKind, date, time, partySize, units, name, email, society, notes, createdAt, reviewed, **ttl** | GSI `by-date` (pk = `date`, sk = `time`) for the admin list. TTL = booking date + 30 days |
| `cwtch-and-cake-slots` | `pk` = `room#2026-11-14#10:00` | booked, capacity, **ttl** | TTL = slot date + 1 day |
| `cwtch-and-cake-reviews` | `pk` = reviewId | rating, tags, comment, displayName, courseYear, verified, flagged, toxicityScore, status, createdAt | GSI `by-status` (pk = `status`, sk = `createdAt`) |
| `cwtch-and-cake-cafe` | `pk` + `sk`: (`status`, `current`) · (`menu`, `<sectionOrder>#<section>#<itemOrder>#<item>`) · (`deal`, `<id>`) | Depends on the item type | All menu items share `pk = "menu"`, so the whole menu, in display order, is **one `Query`**. Deals are a second `Query` |

Reviews have **no TTL** and stay until the admin deletes them. Bookings and slots tidy themselves up.
