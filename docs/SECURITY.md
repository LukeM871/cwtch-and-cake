# Security Contract

These are the rules **every part of Cwtch & Cake must follow**: the infrastructure, the Lambdas and the website.
The website is built last, so it's built to fit these rules from the start, rather than having security added afterwards.

> If something needs to break a rule here, change this document first (in its own commit, with a reason), then change the code.

---

## 1. HTTP security headers (set by CloudFront on every response)

CloudFront adds these through a **response headers policy**, so they apply to every page, file and API response, and the website code can't forget them.

| Header | Value | What it protects against |
|---|---|---|
| `Content-Security-Policy` | see section 2 | Cross-site scripting (XSS), injected scripts, data being sent to other sites |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` | Downgrade to plain HTTP (forces HTTPS for 2 years) |
| `X-Content-Type-Options` | `nosniff` | The browser guessing a file type and running it as a script |
| `X-Frame-Options` | `DENY` | Clickjacking (the site being hidden inside another site's frame) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Full page URLs leaking to other sites |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` | Any script using device features the site never needs |
| `Cross-Origin-Opener-Policy` | `same-origin` | Other sites getting a handle on our window |

Add `preload` to HSTS only if a custom domain is added later. The `cloudfront.net` address can't be preloaded.
The same goes for the **minimum TLS version**: the shared `*.cloudfront.net` certificate has a fixed AWS-managed setting. With a custom domain and an ACM certificate, set `TLSv1.2_2021`.

**Target:** an **A+** on securityheaders.com and a top grade on Mozilla Observatory.

---

## 2. Content Security Policy (CSP)

```
default-src 'self';
script-src 'self';
style-src 'self';
img-src 'self' data:;
font-src 'self';
connect-src 'self' https://cwtch-and-cake-admin.auth.eu-west-2.amazoncognito.com;
frame-ancestors 'none';
base-uri 'self';
form-action 'self';
object-src 'none';
upgrade-insecure-requests
```

Terraform builds the Cognito address from the user pool's domain (`infra/cognito.tf`), so the CSP and the login can't drift apart. It's the only other site the browser may call: the admin page swaps its login code for tokens there.

### What this means for the website (Phase 7)
| ✅ Allowed | ❌ Not allowed |
|---|---|
| JavaScript in `.js` files under `/js/` | `<script>` blocks inside HTML, or `onclick=""` and other inline handlers |
| CSS in `.css` files under `/css/` | `<style>` blocks or `style=""` attributes in HTML |
| JS changing `element.style` or classes | `eval()`, `new Function()`, `innerHTML` with any user data |
| Fonts self-hosted as `.woff2` | Google Fonts, Adobe Fonts or any font CDN |
| Images self-hosted in `/img/` (WebP photos; JPG/PNG only for the link preview and phone icon) | Images hot-linked from Unsplash, Pexels or anywhere else |
| `fetch('/api/...')` on the same domain | Calling any other API from the browser (except the Cognito token exchange) |
| The admin login redirecting to Cognito's hosted page | Embedding anything in an `<iframe>` |

**Showing user content (reviews, names):** always insert it with `textContent`, never `innerHTML`. Then even a review containing `<script>` is shown as plain text.

### How the website meets these rules (Phase 7)
- **No inline code at all.** Every page loads `/css/site.css` and `/js/*.js` files only. GitHub Actions refuses to deploy if an HTML file contains a `<script>` block, a `<style>` block, a `style=""` attribute or an `onclick=""`-style handler. Every page was loaded on the live site with the real CSP: **0 console errors**.
- **No `innerHTML` anywhere.** Pages are built with a small `h()` helper that creates DOM nodes and puts text in with `textContent`. A review containing `<script>alert(1)</script>` was shown on screen as exactly that text (the worst-case test data in `scripts/ui-fixtures/`).
- **Self-hosted everything.** Fonts (Fraunces and DM Sans, SIL Open Font Licence) are `.woff2` files in `/fonts/`. All 67 photos are WebP files in `/img/`, downloaded once and credited on the About page. The browser never contacts Unsplash, Google Fonts or any CDN.
- **Explicit file types.** `scripts/deploy_site.sh` uploads each kind of file with a fixed `Content-Type`. The AWS CLI otherwise guesses from the operating system, and with `X-Content-Type-Options: nosniff` a wrong guess (a JavaScript module sent as `binary/octet-stream`) would stop the page working. Pages, CSS and JavaScript are sent with `Cache-Control: no-cache`, so a deploy is never half-old, half-new in someone's browser.
- **Clean addresses at the edge.** A CloudFront Function (`infra/functions/pretty-urls.js`) serves `/menu/` from `menu/index.html` and redirects `/menu` to `/menu/`. It only runs on page requests, never on `/api/*`, and the bucket stays private.
- **Nothing personal kept in the browser.** The booking confirmation reads its details from the address bar (reference, date, time, size: no name or email), and checks them, because anyone can edit an address. The only thing saved with `localStorage` is the visitor's colour choice (light, dark or auto).

### The admin page's login (Phase 7)
- **Authorization code flow with PKCE**, in the browser, against Cognito's managed login. The page creates a one-time secret (the PKCE verifier) and a random `state` for every login, and rejects a returning login whose `state` doesn't match. A stolen login code is useless without the verifier, and a forged login link is refused.
- **Tokens live in `sessionStorage` only**, so they disappear when the tab closes. The strict CSP is what stops injected scripts from reading them. The login code is removed from the address bar straight after it's used.
- **Short-lived access, quiet refresh.** The access token lasts 60 minutes; the page refreshes it at Cognito a minute before it expires, and if anything is refused it asks for a fresh login. **Logging out revokes the refresh token** at Cognito (token revocation is on), then ends the Cognito session.
- **The page is only a front end.** It isn't linked from the site and isn't indexed (`noindex`), but that's tidiness, not security: every admin request is checked by API Gateway's JWT authorizer and again by the admin Lambda (section 3), so editing the page gives no extra power.

---

## 3. Who can reach what

| Thing | Who can reach it | How it's enforced |
|---|---|---|
| Website files (S3 site bucket) | **Only CloudFront** | Private bucket, all public access blocked, Origin Access Control (OAC) |
| API (API Gateway) | **Only through CloudFront** | CloudFront adds a secret `x-origin-verify` header. Every Lambda rejects requests without it (`403`) |
| `/api/admin/*` routes | **Only the logged-in admin** | API Gateway's JWT authorizer checks the Cognito token (signature, expiry, user pool, app client). Then the admin Lambda checks it's an access token for a user in the `admins` group (`API.md` §7) |
| The admin Lambda's 06:00 task | **Only the project's schedule** | The scheduler role can only invoke the admin Lambda, and only schedules in the project's own schedule group, in this account, can use that role |
| Terraform state bucket | **Only luke-admin** (and later the deploy role, read-only for the state it needs) | Private bucket, HTTPS-only policy |
| AWS account | luke-admin with a passkey. Root is locked away with MFA | IAM |

The `x-origin-verify` secret is generated by Terraform (`random_password`), passed to CloudFront and the Lambdas, and **never written in the repo**.

### The admin login (Cognito)
- **Nobody can sign up.** The one admin user is created with the AWS CLI, not Terraform, so no password or personal email ends up in the code or the Terraform state:
  ```
  aws cognito-idp admin-create-user --user-pool-id <pool id> --username cafe-admin --temporary-password <random> --message-action SUPPRESS
  aws cognito-idp admin-add-user-to-group --user-pool-id <pool id> --username cafe-admin --group-name admins
  ```
- **MFA is required:** an authenticator app, set up at the first login. SMS isn't used: it costs money and phone numbers can be stolen (SIM swap).
- **Passwords:** at least 14 characters, with upper case, lower case and a number. The last 5 can't be reused. The temporary password lasts 3 days.
- **No email or phone is stored.** A forgotten password is reset by the AWS account owner (`admin-set-user-password`), not by a self-service email link.
- **Tokens:** access and ID tokens last 60 minutes, the refresh token 12 hours. Logging out revokes the session.
- **The admin page is a public client:** browser JavaScript can't keep a secret, so there's no client secret, and the login code is protected with PKCE instead. Cognito only sends the code back to the admin page's own address or `http://localhost:8765/admin/` (for working on the page locally).
- "Wrong username" and "wrong password" look the same, so usernames can't be guessed.

---

## 4. Least privilege: each Lambda's permissions

Every Lambda has **its own IAM role** and can do **only** what's listed. Anything not listed is denied. All roles can also write their own CloudWatch logs.

| Lambda | Allowed actions | On |
|---|---|---|
| `create-booking` | `dynamodb:PutItem`, `dynamodb:UpdateItem` (inside one transaction); `ses:SendEmail` | bookings table, slots table; the one SES sender identity |
| `cancel-booking` | `dynamodb:DeleteItem`, `dynamodb:UpdateItem` (inside one transaction), `dynamodb:GetItem`; `ses:SendEmail` | bookings table, slots table; SES sender |
| `get-availability` | `dynamodb:BatchGetItem` | slots table |
| `get-status` | `dynamodb:GetItem` | café table, **status row only** (`dynamodb:LeadingKeys` = `status`) |
| `get-menu` | `dynamodb:Query` | café table, **menu and deals only** (`dynamodb:LeadingKeys` = `menu` or `deal`) |
| `create-review` | `dynamodb:GetItem` (bookings, **only** `email`, `date`, `time`, `reviewed`, `ttl`), `dynamodb:UpdateItem` (bookings, **only** the `reviewed` field), `dynamodb:PutItem` (reviews, **only** `rv_...` rows); `comprehend:DetectToxicContent` (only in the one region, and only while the check is switched on) | bookings and reviews tables |
| `list-reviews` | `dynamodb:Query` (status index), `dynamodb:GetItem` (**summary row only**) | reviews table |
| `admin` | `dynamodb:Query` (bookings **date index only**: it can list a day, but not look up or change a booking); `Query`, `GetItem`, `UpdateItem` on reviews, `DeleteItem` (**`rv_...` rows only**), `PutItem` (**summary row only**); `Query` (**menu rows**) and `UpdateItem` (**menu and status rows**) on the café table | reviews, café, bookings (date index) |
| *scheduler role* | `lambda:InvokeFunction` | the admin Lambda only |

**Row-level locks** (`dynamodb:LeadingKeys`, the partition key being read or written): `get-status` and `get-menu` share the café table, so `get-menu` can't read the status row, and `get-status` can't read the menu. In the same way, `create-review` can add reviews but never overwrite the summary row, `list-reviews` can read the summary row but not look up a review directly, and the admin Lambda can't delete the summary row or change the deals.

**Field-level locks** (`dynamodb:Attributes`, plus `dynamodb:Select` / `dynamodb:ReturnValues` so a request can't ask for "everything" instead): `create-review` needs to check a booking, but it can only read the 5 fields the check uses. It can never read the name, notes or party size, and the only field it can change is `reviewed`.

**Proof:** the IAM Policy Simulator (checked 11 Nov 2026) shows `get-menu` → `Query` on `pk = menu` or `deal` is **allowed**, but `pk = status`, any `GetItem`/`PutItem`, and the bookings table are all **denied**. `get-status` → `GetItem` on `pk = status` is **allowed**, but the menu rows, any write and the bookings table are **denied**.

**Proof with real calls (11 Nov 2026):** each Phase 5 Lambda's exact policy was copied onto a temporary role, which then made real DynamoDB calls. Writes used a condition that can never be true, so nothing was changed, and the roles were deleted afterwards. All 27 results were as designed. For example:
- `create-review` can read a booking's email, date and time, but is **denied** the name or the whole booking.
- `create-review` can mark a booking `reviewed` inside a transaction, but is **denied** changing its email in exactly the same kind of call.
- `list-reviews` can read the summary row, but is **denied** reading any one review directly or scanning the table.
- `admin` can list a day's bookings, but is **denied** looking one up, deleting one, deleting the summary row or changing a deal's price.

---

## 5. Input handling

- **Validate everything on the server.** The website checks inputs too, but only to be helpful. The Lambda is the real gatekeeper.
- **Allow-lists, not block-lists.** Types, times, tags and sizes must be one of a fixed set of values (see `API.md`).
- **Size limits:**
  - request body ≤ 4 KB, otherwise `413`
  - every string has a maximum length
  - strings are trimmed
  - control characters are removed
- **`Content-Type` must be `application/json`.** Anything else gets `415`.
- **Unknown fields are ignored and never stored.**
- **Honeypot field (`website`):** hidden from people with CSS. If it's filled in, the request came from a bot. Return a normal-looking success and **save nothing**, so the bot learns nothing.
- **Same answer for "wrong email" and "no such booking"** (`404`), so nobody can find out which references exist.
- **Secrets and emails are compared in constant time** (`hmac.compare_digest`, on UTF-8 bytes so an email with an accent like `ffiôn@...` works).
- **Reviews get three checks before anyone sees them:** a whole-word filter for obvious slurs (stored as hashes, so the repo holds no slurs), the Amazon Comprehend toxicity check (once switched on), and **the admin approves every review** by hand.

---

## 6. Rate limiting

| Where | Limit |
|---|---|
| API Gateway (whole API) | 10 requests/second steady, bursts of 20 |
| `POST /api/booking` and `POST /api/booking/cancel` | 3/second, burst 5 |
| `POST /api/reviews` | 1/second, burst 3 |

Too many requests get `429`, and the website shows "Busy right now, try again in a moment". AWS WAF would allow per-IP limits, but it's left out because of its monthly cost.

---

## 7. Personal data (UK GDPR basics)

| Data | Where | How long | Shown publicly? |
|---|---|---|---|
| Booking name, email, notes | bookings table | **Deleted automatically 30 days after the booking date** (DynamoDB TTL) | Never |
| Review text, rating, first name + initial, course year | reviews table | Until deleted by admin | Yes, after approval |
| Email on a review | **Not stored.** Only used to check the booking at that moment. The booking just gets `reviewed: true`, with no link to which review | — | — |
| Review comment + display name (when the AI check is on) | Sent to Amazon Comprehend in **Ireland** (`eu-west-1`, inside the EU; London doesn't offer the check) for scoring | Not kept by this project; only the score is stored | The review is public once approved anyway |
| Admin login | Cognito: a username, password hash and MFA secret. **No email or phone number** | Until deleted | Never |
| CloudWatch logs | CloudWatch | 14 days | Never |
| CloudWatch metrics (counts of bookings, reviews, bots...) | CloudWatch | 15 months (AWS's fixed retention) | Never, and they hold **no personal data**: just numbers |
| The café owner's alarm email address | An SNS subscription, plus a gitignored settings file on the owner's laptop | Until the subscription is removed | Never |

- **Logs never contain emails, names or request bodies.** Only the booking reference, route, status code and error type are logged.
- Collect only what's needed. No accounts, no tracking cookies, no analytics scripts.
- The website has a Privacy page that explains all of this.

---

## 8. Secrets and credentials

- **No AWS keys anywhere in the repo or in GitHub.** GitHub Actions uses **OIDC** to get short-lived credentials for one role, and only from the `main` branch of this repo. The trust matches GitHub's **immutable subject** (owner and repo numeric IDs), so a renamed or re-created repo can't inherit it.
- On the laptop, `aws login` gives short-lived credentials.
- `.gitignore` blocks: `*.tfstate*`, `*.tfvars`, `.env*`, `*.pem`, `*.key`, personal notes and plans.
- Before the repo is made public (Phase 8), scan the whole history with `gitleaks`.
- **Throwaway copies of the stack** (a separate Terraform workspace, used to prove the whole system rebuilds from code) get their own names for everything and **no GitHub deploy access at all**: the OIDC provider and the deploy role only exist in the live stack.

---

## 9. Monitoring

Everything here is in Terraform (`infra/monitoring.tf`) and stays inside CloudWatch's always-free tier.

- **Alarm 1, `backend-errors`:** **more than 5 errors in 5 minutes** across the backend → email. It adds up AWS's own Lambda `Errors` for all 8 functions **plus** our own `ServerError` count. The second part matters: a crash that the API safety net (`cwtch/http.py`) turns into a friendly 500 is a *successful* Lambda run as far as AWS knows, so AWS's metric alone would never see it.
- **Alarm 2, `daily-reset-failed`:** **any** error in the admin Lambda → email. A failed 06:00 job is retried twice, which makes 3 errors and is never enough for alarm 1. Web requests can't trip this alarm, because their crashes become 500s.
- **Both alarms were tested on purpose** (Phase 6): ALARM → email → OK → email.
- **The alarm topic (SNS)** has a policy that lets **only these two alarms**, from this account, over **HTTPS**, publish to it. It isn't encrypted with SNS's AWS-managed key, because CloudWatch can't publish to a topic that uses it, and a customer-managed key costs $1 a month. Alarm emails only name the alarm and the numbers, never customer data.
- **The alarm email address is not in Git.** It lives in `infra/alarm.auto.tfvars` (covered by `*.tfvars` in `.gitignore`), the variable is marked `sensitive` (so Terraform doesn't print it), and AWS only sends to it after the owner clicks "Confirm subscription".
- **A dashboard** shows bookings, reviews, bots caught, API traffic and errors, CloudFront traffic, response times and the alarms. The business numbers are **counted by the Lambdas themselves** through CloudWatch's embedded metric format: a JSON line in the normal logs, so **no extra IAM permission** and no extra API call. They are plain counts with **no personal data**: never names, emails or booking references (the tests check this).
- **Logs:** every Lambda's logs are kept for **14 days**, then deleted. They never contain names, emails or notes (section 7).
- **Anything that isn't an API Gateway event** (only possible through a direct `lambda:Invoke`, which needs AWS credentials) is refused with a real error, so it shows up in the metrics instead of being silently ignored.

---

## 10. Threats considered

| Threat | Defence |
|---|---|
| Script injection (XSS) through reviews or names | Strict CSP + `textContent` only + server-side validation |
| Spam bots filling in forms | Honeypot + rate limits + review moderation + AI toxicity check |
| Abusive or hateful reviews | Whole-word filter (sees through leetspeak and spacing) → AI toxicity check → nothing is public until the admin approves it. Shown with `textContent` only |
| Faking "Verified visit" badges | Needs a real booking's reference **and** its email, after the visit; one review per booking (transaction condition); same `404` for every wrong guess; 1 review/second rate limit |
| Sneaking abuse past the AI check by making Comprehend fail (an over-long comment) | Comments are cut into segments that fit Comprehend's 1 KB limit, so the check runs on all of it |
| Two people taking the last place | DynamoDB transaction with a capacity condition (`API.md` §4) |
| Guessing booking references to cancel other people's bookings | References are random (about 1 billion combinations) + the email must match + the same `404` either way + rate limits |
| Calling the API directly, bypassing CloudFront | Secret origin header checked by every Lambda |
| Abuse of admin routes | Cognito login with **required MFA**, no self sign-up, JWT check at API Gateway, then the Lambda checks it's an access token for the `admins` group |
| A stolen admin token | Tokens last 60 minutes; the strict CSP blocks the injected scripts that would steal one; the admin Lambda still can't touch bookings or the slots table |
| A stolen deploy credential | No long-lived keys exist. The OIDC role only works from this repo's `main` branch and can only deploy this site |
| Something breaks and nobody notices | Two CloudWatch alarms email the owner (crashes counted even when they're turned into friendly 500s); a dashboard; both alarms tested on purpose |
| Losing the whole AWS setup | Everything is code: a complete copy was built from nothing (94 resources in ~3 minutes), tested and destroyed. Data that matters (the menu) is reseeded from `scripts/menu.json` |
| A surprise AWS bill | $5 budget alert, on-demand pricing, rate limits, no always-on servers |
