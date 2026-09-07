# US-1.30 — Unified Account Provisioning (design change)

**Date**: 2026-08-11
**Trigger**: user question — "why we have self service different than admin creating user, both should be same right?"
**Status**: designed, NOT implemented
**Affects**: US-1.30, US-1.31, US-1.32, BR-P3, BR-P4, BR-P8 (new), BR-A6, BR-A10 (new)

## Summary

Self-registration and Administrator-created users provision accounts by two different
mechanisms today. The difference is not cosmetic: the admin path proves control of the
user's mailbox as a structural consequence of its design, and the self-registration path
proves nothing at all. Since self-registration is the path with the *lower* trust in the
address, the weaker check is on the wrong side.

This change makes both paths use the admin mechanism. It is a **correction**, not a new
requirement — US-1.30 already required "Cognito enforces email verification", which the
implementation never did.

## Findings that motivate the change

### F1 — Self-registration asserts email verification instead of obtaining it

`CognitoAuthProvider.self_sign_up` calls `admin_create_user` with
`MessageAction="SUPPRESS"` and `email_verified: "true"` set by the portal, then
`admin_set_user_password(..., Permanent=True)` with the password the caller typed.

No code is ever sent. Nobody confirms the registrant can read mail at that address.

Consequence: an anonymous caller can register using another person's address, provided
the domain is allow-listed and that person has no account yet, then choose the password
and hold an account bearing an identity they do not own.

Two things currently limit the impact, and neither is a designed control:
- the first-login OTP mails a code to the *real* owner, which the registrant cannot read
- SES is in sandbox, so that mail currently fails for unverified addresses anyway

The first is exactly the control that the "pre-stamp `lastVerifiedAt` at creation" idea
would have removed. That is why pre-stamping was rejected for this path (see F4).

### F2 — Account enumeration on `/auth/register`

`AuthService.self_register` performs no duplicate check — `user_exists` is called only in
`create_user` and `bulk_import`. An existing address therefore reaches
`admin_create_user`, which raises `UsernameExistsException`. That is not an `AppError`,
so `global_handler` maps it to a generic **500**, while a new address returns **201**.

Two distinguishable outcomes let an unauthenticated caller determine who holds an
account. This contradicts BR-A6, which the login and reset paths honour carefully.

### F3 — The two paths, compared

| | Admin-created / bulk import | Self-registration |
|---|---|---|
| Initiator | authenticated Administrator, audit-logged | anonymous caller |
| Who vouches for the address | a person, accountable | nobody |
| Password at creation | system-generated, never disclosed | chosen by the caller |
| `email_verified` | earned via the reset code | asserted `"true"` by the portal |
| Mailbox proven before access | **yes, unavoidably** | **no** |
| Route in | "Forgot password" (only possible route) | immediate login |

The initiator and role differences are legitimate and are retained. The *mechanism*
difference is the defect.

### F4 — Why convergence is on the admin mechanism, not the other way

The admin path's assurance is structural rather than added: because the generated password
is never disclosed, the only way to obtain a usable credential is the forgot-password flow,
which requires reading a code sent to the registered address. Verification cannot be
skipped without breaking the ability to log in at all.

Adopting that for self-registration yields, in one move:
- mailbox control proven on every provisioning path (F1 closed)
- `email_verified` no longer asserted falsely
- a uniform response for existing addresses becomes natural (F2 closed)
- **first-login** OTP becomes genuinely redundant everywhere (BR-A10), removing the
  dependency that currently blocks new users while SES is in sandbox

## Target design

One provisioning mechanism, expressed as BR-P8. Every path:

1. creates the Cognito identity with a system-generated **permanent** password, never
   disclosed or emailed, and no Cognito invitation

### Correction to F1 — `email_verified: "true"` must STAY (2026-08-11, before implementation)

An earlier draft of this design (and the first wording of BR-P8) said the portal should stop
asserting `email_verified: "true"`. **That is wrong and would have broken every provisioning
path.** Cognito only delivers a forgot-password code to a user who "has a verified email or
phone number attribute"
([troubleshooting guide](https://docs.aws.amazon.com/cognito/latest/developerguide/troubleshooting.html)).
With the flag unset, `ForgotPassword` raises `InvalidParameterException` — which
`CognitoAuthProvider.forgot_password` deliberately swallows to avoid enumeration (BR-A6) — so
the user would be told a code was sent, no code would ever arrive, and since the generated
password is never disclosed there would be **no route to a usable credential at all**.

The flag therefore stays on every path. This does not weaken the design, because the flag was
never the thing providing assurance:

- `email_verified: "true"` is a **Cognito precondition for delivering the code**, not a claim
  the portal relies on.
- The actual proof of mailbox control is **structural**: the only route to a usable credential
  is reading a code sent to that address. That property is unchanged.

What F1 correctly identified remains the defect: self-registration let the caller set a
password directly, so it never had to read anything. Removing the caller-supplied password —
not removing the flag — is what closes it.

Content was rephrased for compliance with licensing restrictions.
2. creates the portal record **immediately**, at provisioning time — not via first-login
   JIT. Discovered during implementation: unifying only the Cognito call left
   self-registration with no portal record, so `confirmResetPassword` had nothing to
   stamp (BR-A10), JIT then created a record with no `lastVerifiedAt`, and the
   first-login OTP fired anyway — defeating the rework for the one path it was aimed
   at. `create_user` and `bulk_import` already created the record eagerly; only
   self-registration deferred it, which was a second undocumented divergence between
   the paths. JIT reverts to the no-op fallback it is meant to be (BR-P1). Registration
   also publishes `UserProvisioned` with `source="self-registration"`, as the other
   paths do.
3. directs the user to "Forgot password" to establish their own password
4. stamps `lastVerifiedAt` when that flow completes (BR-A10), so no first-login OTP fires

Paths differ **only** in:

| Aspect | Self-registration | Administrator-created | Bulk import |
|---|---|---|---|
| Initiator | anonymous | Administrator | Administrator |
| Role | Member only (BR-P3) | admin-selected | Member |
| Domain allow-list | enforced; empty ⇒ blocked | enforced when set | enforced when set |
| Master switch | `selfRegistrationEnabled`, fails closed | n/a | n/a |
| Response on existing address | uniform, indistinguishable (BR-A6) | "already exists" (caller is trusted) | `Skipped (duplicate)` in the row report |

Note the asymmetry in the last row is deliberate: an authenticated Administrator is
entitled to know an account exists; an anonymous caller is not.

### Changes required

**Contract** — `contracts/services/identity-access/openapi.yaml`, `/auth/register`:
- drop `password` from `required` and from `properties`
- response becomes a generic acknowledgement rather than the `User` schema (returning the
  created user would itself confirm existence); `201` for both new and existing addresses

**Service** — `services/identity-access/src`:
- `providers.CognitoAuthProvider.self_sign_up` — remove the `email_verified` attribute and
  the caller-password `admin_set_user_password`; generate a permanent password internally.
  It then differs from `admin_create_user` so little that the two should collapse into one
  provider method, with role and initiator decided by the caller.
- `auth_service.self_register` — drop the password parameter; on an address that already
  exists, return the same shape as success WITHOUT creating or modifying anything; keep the
  allow-list and master-switch gates ahead of any Cognito call
- send the same welcome mail as bulk import, directing the user to "Forgot password"

**Frontend** — `frontend/src/features/AuthScreen.tsx`:
- remove password and confirm-password inputs from the Self-Registration tab
- the existing success copy, *"Account created. Check your email to verify, then sign in."*,
  becomes **true** for the first time; today nothing is emailed and nothing is verified

## Consequences and risks

**Registration stops being instant.** Register → email → set password → sign in. One extra
step, conventional for this class of product, and strictly fewer steps than today's flow
once the first-login OTP is counted.

**A stranger can trigger mail to any allow-listed address.** Anyone may POST an address and
cause a welcome email. Rate limiting on `/auth/register` is therefore recommended
(SECURITY-11/12, as already applied to OTP issuance). Without it the endpoint is a small
mail amplifier aimed at one domain.

**A registrant who already has an account gets a message and no email.** The privacy-preserving
consequence of the uniform response. Accepted deliberately; the copy should be phrased so
it does not promise mail will arrive ("If that address is eligible, you'll receive an email").

**Cognito email becomes the critical dependency for onboarding.** It is `COGNITO_DEFAULT`
and unaffected by the SES sandbox, which is precisely why this design unblocks new users
today. SES remains required for welcome mail and for periodic US-1.32 re-verification, so
this reduces but does not remove the need for SES production access.

**US-1.32 is unchanged.** Only the redundant *first-login* OTP is removed. Periodic
re-verification still runs on its interval and remains the control that detects lost
mailbox access after the fact.

## Migration

Existing accounts are unaffected — they already hold usable passwords. No backfill.

Self-registrations completed under the old flow were never mailbox-verified. Their
`lastVerifiedAt` was set manually on 2026-08-11 to work around the SES block, so their
first genuine verification will be at the next US-1.32 interval. Worth noting rather than
acting on: no such account is known to exist on the dev stack (all current users were
admin-created, bulk-imported, or seeded).

## Decisions (settled 2026-08-11 by the user)

1. **Rate limit on `/auth/register`** — **NOT required.** Declined by the user. Recorded as an
   accepted risk: an anonymous caller can cause a welcome email to any allow-listed address,
   so the endpoint is a small mail amplifier aimed at one domain. Revisit if SES reputation
   metrics (bounce/complaint rate) degrade, or before the portal is exposed beyond a
   trusted audience. Note the OTP path IS rate-limited (BR-A5), so this is an inconsistency
   held deliberately rather than an oversight.
2. **Uniform-response copy** — approved as proposed: *"If that address is eligible, you'll
   receive an email with a link to set your password."* Promises no delivery, so it reads
   identically whether or not an account already exists.
3. **Password field** — **accept and ignore for one release.** `password` is removed from
   `required` but tolerated if sent, so a cached older SPA bundle keeps working; it is never
   used to set a credential. Remove from `properties` in a later release once no client
   sends it. Chosen over immediate removal because it costs nothing and eliminates a
   deploy-ordering hazard between the API and the SPA.

## Addendum — allowed-domain entry and validation (US-8.3)

**Requested 2026-08-11**: an Administrator must be able to enter multiple domains in
comma-separated form, e.g. `amazon.com,cognizant.com`.

**Already supported; no change needed.** `admin.tsx` `setDomains` splits on commas, trims and
drops empties before sending an array; `settings_service.update_settings` also accepts a raw
comma-separated string and normalises it the same way; `AuthService._domain_allowed` compares
the email's domain case-insensitively against the set. Verified against both code paths.

**Gap found while checking (NOT yet fixed).** Entries are validated only as strings
(`require_str(..., max_len=253)`). Nothing checks that a value is shaped like a domain, so
`@example.com`, `example com`, `https://example.com` and `Example.Com ` are all accepted and
stored. `_domain_allowed` compares against `email.split("@")[-1].lower()`, so a stored
a stored `@example.com` can never match anything — self-registration then rejects **every** applicant
with "Email domain is not permitted for registration" while the Settings screen displays a
value that looks correct. A single typo silently disables onboarding with no diagnostic.

**Proposed fix** (small, independent of the rest of this change):
- normalise on save: trim, lowercase, strip a leading `@`, strip a `scheme://` prefix
- reject with a per-field validation message when a value has no dot, contains whitespace,
  or contains `@` after normalisation — the Settings screen already renders per-field
  details (US-8.16), so the admin sees which entry is wrong
- the empty list keeps its current meaning: self-registration blocked (BR-P3)
