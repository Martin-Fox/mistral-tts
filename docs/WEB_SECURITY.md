# WebUI authentication and browser security

[Documentation](README.md) · [Project overview](../README.md)

On this page:

- [WebUI password storage and migration](#webui-password-storage-and-migration)
- [WebUI sessions](#webui-sessions)
- [Request origin and browser security](#request-origin-and-browser-security)
- [Login attempt limits](#login-attempt-limits)
- [API keys in the WebUI](#api-keys-in-the-webui)

## WebUI password storage and migration

The WebUI stores salted PBKDF2-HMAC-SHA256 password hashes (600,000 iterations),
not plaintext passwords, in `storage/auth.json`. Existing plaintext files are
migrated atomically during startup; migration failure stops startup and preserves
the original file. Environment credentials are hashed in memory and do not create
an auth file until the password is changed through the WebUI. Unicode passwords
and usernames are supported. On POSIX, the credentials file has mode `0600`;
on Windows, restrict access using filesystem ACLs.

New environment credentials (when no auth file exists) and password changes
require 12-1024 characters, with at least 12 after trimming surrounding whitespace.
The actual password is preserved, including Unicode and whitespace; there is no
mandatory mix of character types. Choose a unique phrase. Existing persisted
short passwords are not rejected solely for their length at startup: after a
correct login, the server returns `requires_password_change: true` and permits
only auth status, password change and logout. The UI opens the change form;
generation, data/config reads and resume return `403`, including before upload.
Changing the password signs out all clients, then the new login has full access.
Failed persistence leaves the restricted session available for retry. Lost
passwords and credentials beyond input length bounds need operator recovery.

Persisted credentials override the environment. If the file is damaged or contains
rejected default credentials, stop the server and move `storage/auth.json` to a
private backup location, configure a unique `APP_PASSWORD`, then restart. Protect
any legacy backup because it may contain a plaintext password. Hash-only files
must not be edited as if `password_hash` were a plaintext password.

## WebUI sessions

Run the WebUI with **one worker** (`uvicorn src.web:app --workers 1`). Sessions
are process-local and are lost on restart. Multiple replicas/workers are not
supported; `WEB_CONCURRENCY` values other than `1` are rejected at startup.
Explicit server CLI worker settings must also remain `1`.

- `SESSION_TTL_SECONDS`: positive integer, default `28800` (8 hours).
  Expiry is absolute from login, not extended by activity. The server checks expiry
  independently of the cookie, including while streaming progress via SSE.
- `SESSION_COOKIE_SECURE`: `true` for HTTPS deployments, including behind a TLS
  reverse proxy; `false` (default) supports local HTTP. Invalid values stop startup.
  Secure cookies are not suitable for ordinary HTTP deployments. Use HTTPS when
  accessing the WebUI over a network; this option does not configure TLS itself.
- A successful password change signs out **all** sessions, including the current
  browser; sign in with the new password. Failed writes leave sessions valid.
  Logout revokes the current token. Expired sessions are removed during login and
  session validation. Running generation jobs continue after logout/session expiry;
  authenticated access to their progress requires a new login.

## Request origin and browser security

Every state-changing HTTP request, including login/logout, must have an `Origin`
matching the request scheme, host and port. Default ports normalize and subdomains
are not implicitly trusted. `null`, foreign or duplicated origins are rejected
with `403` **before** reading the body or reserving generation capacity. The
application does not trust raw forwarded headers; HTTPS proxies must configure
Uvicorn's trusted proxy handling as described in Operations.

Clients that omit Origin must send `X-Requested-With: Booksmith`. The WebUI adds
it automatically. For example, a non-browser client can log in with that header
and retain its session cookie. CLI/TUI do not use these HTTP routes. A bad Origin
cannot be overridden by the custom header, and originless requests marked
`Sec-Fetch-Site: cross-site` or `same-site` are rejected. Do not enable broad CORS
without reviewing this contract. Custom clients using old headerless POSTs need
to be updated; no CSRF-disable switch is provided.

Responses have `nosniff`, frame protection, no-referrer policy and a CSP allowing
scripts/connects only from the same origin. Styles retain inline CSS and the
existing Google Fonts sources for UI compatibility. Root/API responses use
`Cache-Control: no-store`. TLS/HSTS remain a reverse-proxy responsibility.
Interactive `/docs` and `/redoc` are disabled because their default CDN/inline
scripts conflict with the CSP; `/openapi.json` remains available.

## Login attempt limits

The WebUI allows **5 attempts per username and client address** and **20 attempts
per client address across all usernames** in a 5-minute fixed window. Successful
attempts count too. Exhausting either limit returns HTTP `429` with `Retry-After`
in seconds, before password hashing. Rejected attempts do not extend the window.
A different address has an independent allowance; this is not a global account
lockout. Use network-level controls for distributed brute-force attacks.

The limiter stores at most 1024 counters per process and does not evict active
limits to admit new identities. If full, attempts requiring new counters receive
`429` until space expires; existing identities still use their remaining allowance.
State is lost on restart. The single-worker requirement also applies here.

The application uses the ASGI client address and does not parse `X-Forwarded-For`
or `Forwarded` itself. For direct Uvicorn access, use `--no-proxy-headers`. Behind
a reverse proxy, use `--proxy-headers --forwarded-allow-ips=<trusted-proxy-IP>` and
prevent clients from bypassing that proxy. Never trust arbitrary forwarded headers
(`--forwarded-allow-ips='*'`) on an exposed listener. Without trusted forwarding,
users behind one proxy/NAT share the source allowance. Configure TLS separately.

## API keys in the WebUI

Keys entered in the WebUI are sent with the generation request but are no longer
saved in browser storage or restored after reloading the page. Legacy `api_key`
and `openai_key` localStorage entries are removed when the page opens and on
logout. Logout also clears and masks the key fields, even if the logout request
fails. Confirmed unauthenticated status clears them too, including after a
successful password change.

Leave the fields empty to use the server's `MISTRAL_API_KEY` / `OPENAI_API_KEY`.
The key inputs request `autocomplete="off"`; browser/password-manager behavior
is independent of the application. If browser policy blocks storage access, the
UI continues without reading or writing keys; legacy removal can only succeed
when storage access is allowed. No persistent "remember key" option is enabled.
