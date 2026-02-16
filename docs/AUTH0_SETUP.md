# Auth0 Setup for Heimdex

## 1. Create Auth0 Resources

### SPA Application

1. Auth0 Dashboard → Applications → Create Application
2. Type: **Single Page Application**
3. Settings:

| Field | Staging Value |
|-------|---------------|
| Allowed Callback URLs | `https://*.app.heimdexdemo.dev/auth/callback` |
| Allowed Logout URLs | `https://*.app.heimdexdemo.dev` |
| Allowed Web Origins | `https://*.app.heimdexdemo.dev` |

For local testing, add `http://localhost:3000/auth/callback` and `http://localhost:3000` as well.

4. Advanced Settings → Grant Types: Ensure **Authorization Code** is enabled (PKCE is automatic).

### API (Resource Server)

1. Auth0 Dashboard → Applications → APIs → Create API
2. Settings:

| Field | Value |
|-------|-------|
| Name | Heimdex API |
| Identifier (audience) | `https://api.heimdex.io` |
| Signing Algorithm | RS256 |

### (Optional) Organization Claim

To embed org_id in tokens via an Auth0 Action:

```javascript
// Auth0 Dashboard → Actions → Flows → Post Login → Custom Action
exports.onExecutePostLogin = async (event, api) => {
  if (event.organization) {
    api.accessToken.setCustomClaim(
      'https://heimdex.io/org_id',
      event.organization.name
    );
  }
};
```

## 2. Environment Variables

### Frontend (services/web)

```bash
NEXT_PUBLIC_AUTH0_ENABLED=true
NEXT_PUBLIC_AUTH0_DOMAIN=heimdex-staging.auth0.com
NEXT_PUBLIC_AUTH0_CLIENT_ID=<SPA client ID from step 1>
NEXT_PUBLIC_AUTH0_AUDIENCE=https://api.heimdex.io
```

### Backend (services/api)

```bash
AUTH0_ENABLED=true
AUTH0_DOMAIN=heimdex-staging.auth0.com
AUTH0_AUDIENCE=https://api.heimdex.io
AUTH0_ORG_CLAIM=https://heimdex.io/org_id   # optional
ENVIRONMENT=staging
```

Note: `AUTH0_ALGORITHMS` defaults to `RS256` and does not need to be set.

## 3. Auth Flow

```
Browser → /login → "Continue with Heimdex" button
    ↓
Auth0 Universal Login (Authorization Code + PKCE)
    ↓
Redirect to /auth/callback?code=...&state=...
    ↓
@auth0/auth0-react handles code exchange (token stored in memory)
    ↓
Redirect to /
    ↓
API calls include Authorization: Bearer <access_token>
    ↓
Backend validates RS256 JWT via JWKS (cached 1h)
```

## 4. Backend JWT Verification

The backend fetches JWKS from `https://{AUTH0_DOMAIN}/.well-known/jwks.json` and verifies:
- Signature (RS256 via public key matching `kid`)
- Issuer == `https://{AUTH0_DOMAIN}/`
- Audience includes `AUTH0_AUDIENCE`
- Token is not expired

On first request after startup (or cache expiry), there is a one-time JWKS fetch. Keys are cached for 1 hour.

## 5. User Linking

Users must exist in the Heimdex database before they can log in via Auth0. On first Auth0 login:
1. Backend looks up user by `auth0_sub` (Auth0 subject ID)
2. If not found and email is verified, auto-links by email
3. If still not found → 401 (contact org admin)

Seed users via: `docker compose exec api python -m app.seed`

## 6. Local Testing

```bash
# 1. Set Auth0 env vars in docker-compose.yml or .env
# 2. Build and start
docker compose build api web
docker compose up -d api web

# 3. Seed database
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed

# 4. Open browser
# Auth0 mode: navigating to http://localhost:3000/login shows "Continue with Heimdex"
# Dev mode:   set AUTH0_ENABLED=false to use email/password form
```

## 7. Wildcard Subdomains

Heimdex uses subdomain-based multi-tenancy: `{org}.app.heimdexdemo.dev`.

Auth0 supports wildcard URLs in callback/origins configuration. Ensure you enter them with `*` prefix (e.g., `https://*.app.heimdexdemo.dev/auth/callback`).

Tenancy is ALWAYS derived from the Host header, even when Auth0 is enabled. The optional `AUTH0_ORG_CLAIM` is for additional validation, not primary routing.
