# Prompt 5 — Authentication & Authorization Design

> Scope: identity and access for the scale-up tier. The shipped MVP does
> email/password → **JWT** plus per-tenant **API keys** (see
> [src/infrastructure/security](../../src/infrastructure/security) and the
> `api_keys` table). This document extends that to OAuth (Google, GitHub),
> organization invites, refresh tokens, and full **RBAC** over the
> `Organizations → Projects → Knowledge Bases` hierarchy from
> [03-database-design.md](03-database-design.md). No code — flows only.

---

## 1. Principles

1. **Identity (who you are) is separate from membership (what you can do).** A
   `user` is one global human; authorization is resolved per-organization through
   `organization_members.role`. This is why the schema splits `users` from
   `organization_members`.
2. **Stateless access tokens, stateful refresh tokens.** Access JWTs are short-lived
   and verified with no DB hit; refresh tokens are long-lived, stored hashed, and
   revocable. You get horizontal scalability *and* the ability to log someone out.
3. **Never store a credential in plaintext.** Passwords → Argon2id. API keys and
   refresh tokens → hashed at rest; the raw value is shown exactly once.
4. **Authorization is enforced server-side on every request**, derived from the
   token's claims + the resource's `org_id`, and backed by Postgres RLS as
   defense-in-depth (the MVP's `app.tenant_id` GUC).
5. **All auth methods converge on the same session model.** Email, Google, and
   GitHub all end at "issue our access+refresh tokens for this user," so the rest
   of the system never cares how the user logged in.

---

## 2. The four entry points (and how they unify)

```
                         ┌─────────────────────────────┐
  Email + password ─────▶│                             │
  Google OAuth     ─────▶│   Identity resolution:       │
  GitHub OAuth     ─────▶│   find-or-link a `users` row │──▶ issue tokens
  Org invite accept ────▶│   + resolve memberships      │
                         └─────────────────────────────┘
```

### 2.1 Email + password
- **Register:** validate email → hash password with **Argon2id** → create `users`
  row (and, if self-serve signup, a new `organization` + `owner` membership) →
  send verification email → issue tokens (or gate login until verified).
- **Login:** look up by email (citext) → verify Argon2id hash (constant-time) →
  issue tokens. Generic "invalid credentials" on any failure (no user enumeration).
- **Password reset:** email a single-use, expiring, hashed reset token; never
  reveal whether the email exists.

### 2.2 Google / GitHub OAuth (Authorization Code + PKCE)
Same flow for both providers, different endpoints:
1. App generates a `state` (CSRF guard) + PKCE `code_verifier`/`code_challenge`,
   stores them server-side, redirects the user to the provider's consent screen.
2. Provider redirects back with `code` + `state`. App **validates `state`**,
   exchanges `code` + `code_verifier` for provider tokens.
3. App fetches the provider profile (verified email, provider user id).
4. **Find-or-link** (see §3) → issue **our** access+refresh tokens.

We use OAuth purely for **authentication** (identity), requesting minimal scopes
(`email`, `profile`). We do not act on the user's behalf, so we don't store
provider access tokens long-term (unless the same provider is later used as an
*ingestion connector* — Google Drive — which is a separate consent with its own
scopes; see [06](06-ingestion-pipeline.md)).

### 2.3 Organization invites
1. An `owner`/`admin` invites `email` + `role`. A row lands in `invitations` with
   a hashed, expiring `token`; the raw token goes only in the email link.
2. Invitee clicks the link:
   - **Existing user:** authenticate (any method) → accept → create
     `organization_members(org_id, user_id, role)` → mark invite accepted.
   - **New user:** register (email or OAuth) → then the same accept step.
3. The invite's `role` becomes their membership role. The invite is single-use
   and expires; `UNIQUE(org_id, email) WHERE accepted_at IS NULL` prevents
   duplicate live invites.

This is the mechanism that turns the MVP's one-user-per-tenant model into real
multi-user organizations.

---

## 3. Identity resolution & account linking

The crux of supporting multiple login methods for one human:

- A `user_identities` table (extends the MVP) maps
  `(provider, provider_user_id) → user_id`, where `provider ∈ {password, google,
  github}`. One user can have several identities.
- **Find-or-link rules:**
  - If `(provider, provider_user_id)` already exists → log that user in.
  - Else if the provider's **verified** email matches an existing `users.email`
    → link a new identity to that user (so Google + GitHub + password on the same
    verified email are one account).
  - Else → create a new `users` row + identity.
- **Only link on a *verified* email** from the provider. Linking on an unverified
  email is an account-takeover vector.
- `users.password_hash` stays NULL for OAuth-only users; they can add a password
  later (which just creates a `password` identity).

---

## 4. Token model

### 4.1 Access token (JWT)
- **Short TTL** (~15 min). Signed (RS256/EdDSA preferred over HS256 so verifiers
  don't hold the signing secret; the MVP's symmetric JWT is fine early).
- **Claims:** `sub` (user id), `email`, `active_org` (current org context),
  `role` (in that org), `token_version`, `iat/exp/jti`.
- Verified **statelessly** on every request — no DB round-trip in the hot path.
- **Org switching:** because a user can be in many orgs, the access token carries
  one `active_org`; switching orgs mints a new access token for the new context
  (validated against memberships).

### 4.2 Refresh token
- **Long TTL** (e.g. 30 days), opaque random string, stored **hashed** in a
  `refresh_tokens` table with `user_id`, `expires_at`, `revoked_at`, device info.
- **Rotation:** each use issues a new refresh token and invalidates the old one.
  **Reuse detection** — if a already-rotated token is presented again, treat the
  whole family as compromised and revoke it (stolen-token defense).
- **Revocation / logout:** delete or mark the row; also bump the user's
  `token_version` to invalidate outstanding *access* tokens at their next
  (≤15-min) refresh. This is how stateless access tokens stay revocable.

### 4.3 API keys (machine-to-machine)
- For server-to-server use (the MVP already has these). Format: `prefix_random`;
  only the **hash** is stored (`api_keys.key_hash`, unique-indexed for O(1)
  lookup); `prefix` is stored plaintext for display ("...which key was this").
- **Scoped**: `org_id`, optional `project_id`, a `scopes` array (e.g.
  `documents:write`, `chat:read`), and an `expires_at`. They authorize a *service*,
  not a user, so they carry their own permission set rather than a role.
- `last_used_at` is updated asynchronously for audit and stale-key cleanup.

---

## 5. Role-Based Access Control (RBAC)

**Roles** (on `organization_members`, org-relative):

| Role | Can |
|---|---|
| `owner` | everything incl. billing, delete org, manage members/roles |
| `admin` | manage projects/KBs/documents/keys/members (not billing or org delete) |
| `member` | create/use KBs and chat, upload documents within assigned projects |
| `viewer` | read-only: query chat, view documents/analytics |

**Permission model:** roles map to a permission set (`resource:action`). The
check on every request is:

```
authorize(user, action, resource):
  1. resource.org_id == token.active_org            # tenant boundary
  2. membership = members[user, resource.org_id]    # exists & active?
  3. role_permissions[membership.role] ⊇ {action}   # role grants it?
  4. (optional) project/KB-level scoping            # finer than org
```

- **Org boundary first, role second.** Even an `owner` of org A has no access to
  org B's resources — the `org_id` match is checked before role.
- **Project-level scoping** (optional): a `member` can be limited to specific
  projects via a `project_members` table, for larger orgs.
- **API keys** bypass roles and use their explicit `scopes` instead.
- **RLS backstop:** the request sets `app.org_id` (GUC) for the transaction;
  Postgres RLS policies (already in `0001_initial`) reject any row from another
  org even if an application check is missed.

---

## 6. End-to-end flows

### 6.1 Email signup → first request
```
register(email,pw,org_name)
  → Argon2id(pw) → create user + org + owner membership
  → send verify email
  → issue access(15m) + refresh(30d)
client stores tokens → calls API with `Authorization: Bearer <access>`
  → server verifies JWT signature + exp → sets app.org_id → RBAC check → serve
```

### 6.2 Google/GitHub login
```
client → /auth/{provider}/start → server stores state+PKCE, redirects to provider
provider consent → redirect back with code+state
server: validate state → exchange code (+PKCE) → fetch verified profile
  → find-or-link identity (§3) → issue access+refresh → redirect to app
```

### 6.3 Invite acceptance
```
admin → invite(email, role) → store hashed token → email link
invitee → click link → authenticate or register
  → validate token (unexpired, unused) → create membership(role)
  → mark invite accepted → issue tokens for active_org = that org
```

### 6.4 Token lifecycle
```
access expires (15m) → client POSTs refresh token
  → server: hash-match a live, unrevoked, unexpired row
  → rotate (issue new refresh, revoke old) → issue new access
  → if a revoked/rotated token is reused → revoke whole family (breach)
logout → revoke refresh row + bump token_version
```

### 6.5 Machine/API access
```
service → request with `X-API-Key: prefix_secret`
  → server hashes → unique lookup on key_hash → check active + not expired
  → load org_id/project_id/scopes → authorize action against scopes
  → update last_used_at async
```

---

## 7. Security posture (cross-cutting)

- **Hashing:** Argon2id (passwords), SHA-256/HMAC (API keys & refresh tokens —
  fast lookup, no need for slow hashing on high-entropy random secrets).
- **Transport:** HTTPS only; access token in `Authorization` header; refresh
  token ideally in an `HttpOnly`, `Secure`, `SameSite` cookie for browser clients.
- **CSRF:** `state` param on OAuth; SameSite cookies + CSRF tokens for cookie-based
  refresh.
- **Enumeration:** generic errors on login/reset/register-existing.
- **Rate limiting / lockout:** on login, reset, and OAuth callback endpoints.
- **Audit:** auth events (login, key use, role change, invite) recorded in the
  `audit_events` / `analytics_events` stream for the org.
- **Least privilege at the DB:** the app connects as a non-owner role so RLS is
  actually *enforced* (the README's production note), not merely present.
