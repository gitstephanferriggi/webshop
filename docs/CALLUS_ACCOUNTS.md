# Callus customer account screens

The shop now provides its own Builder pages at `/login`, `/signup`, `/forgot-password` and `/update-password`, plus `/account-callus`. These pages use the existing storefront colours, official logo, responsive layout and accessible labelled fields. The standard customer login and password forms are replaced; Frappe still handles credentials and sessions.

Registration collects first name, last name and email. Native `frappe.core.doctype.user.user.sign_up` creates a Website User with the configured Portal Settings default role. The welcome email's original `/update-password?key=...` link now opens the matching shop page. A password is chosen only after following the email link. Frappe enforces password strength, reset-token expiry and single use. The API returns an explicit team-help state when welcome mail could not be generated.

Sign-in uses native `login`, supports a verification-code challenge when requested, and validates redirects against the current origin. Forced password resets also stay inside the shop design. A signed-in account screen offers shop, favourites, basket and sign-out links. This change does not add an order-history portal, cross-device favourites or Shop/Shop Pay identity.

Recovery uses the native reset endpoint, with a generic response for unknown addresses. Passwords and reset links are never placed in local or session storage. Reset keys are removed from the address bar after reading, and account pages use a no-referrer policy. Account pages remain noindex on production exports as well as UAT. All requests retain Frappe's CSRF handling, session cookies, rate limits and authentication checks.

## Portable source

- `webshop/public/callus/account.js` is appended to the generated shared Builder JavaScript by `build.py`.
- The four new Builder page records are versioned with the existing 15 pages.
- Only public signup/password-login settings enter the page-data JSON. User identity is fetched from the authenticated session endpoint; it is never embedded in cached Builder HTML.
- No new backend endpoint or credential store was introduced.

Run `python3 webshop/callus_storefront/build.py` after changes, then deploy and import the 19 records using the normal release procedure. Preserve current Builder edits before importing. No email configuration is enabled by source code or migration.

## Verification and UAT email

- 13 catalogue/export checks passed after regeneration.
- 14 actual Frappe WSGI account checks passed in the isolated local test site: creation, duplicate account, email-link format, incorrect password, weak password, initial password setup, authenticated session, single-use link, sign-in, sign-out, loss of authenticated access, recovery email, generic unknown-address response and replacement password. Email delivery was intercepted in those tests; no local test mail left the machine.
- The UAT pages were visually checked on desktop and mobile. Required fields and failed-login feedback were checked without creating customer records.
- Existing UAT SMTP credentials were validated. A delivery-check email and the explicitly requested password-reset email were sent only to the user's authorized test address. Both queue records reported Sent; inbox receipt remains for the recipient to confirm.
- That test address is an existing System User, so it was not recreated or converted into a customer account. No existing password was changed. New-account verification was tested locally, not by altering that staff account.
- UAT outgoing accounts were restored to disabled and background mail queue paused after the targeted sends. Automatic welcome/recovery email delivery in UAT therefore remains disabled. Enable a controlled UAT delivery policy before unattended registration testing; do not resume a copied production email backlog.

`tests/account_http.py` accepts only `test_site` or the isolated `checkout.localhost` site, and is included in CI. Two-factor setup and actual inbox receipt still need merchant acceptance testing.
