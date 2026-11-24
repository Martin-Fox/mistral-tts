# WebUI deployment security

[Documentation](README.md) · [Project overview](../README.md)

The supported model is one account, one worker and one replica. LAN access still
requires authentication and a strong unique password. Anyone using the shared
account can access its jobs and use server-side provider keys; it is not a
multi-user isolation boundary.

## LAN deployment checked on 2026-11-18

Read-only, unauthenticated checks of the operator's LAN endpoint showed:

| Request | Result |
| --- | --- |
| `GET /` | 200, UI available over HTTP |
| `GET /api/auth/status` | 200, `authenticated: false` |
| `GET /api/config` | 401 |
| Empty `POST /api/generate` | 401; no generation submitted |
| `GET /api/tasks` | 404 |

The current checkout defines `/api/tasks`. Its absence suggests a different
deployed version or routing configuration. These checks do not establish the
image digest, cookie flags after login, router/firewall rules or public
reachability. No credentials, uploads or provider calls were used. There were
no running containers on the development host; the remote Docker daemon and
deployment configuration were not available for inspection.

## Publish only where intended

The Docker listener must bind `0.0.0.0` inside its container. Restrict the host
publication separately. For host-only access or a host reverse proxy:

```bash
docker run -d --name mistral-tts \
  -p 127.0.0.1:8091:8000 \
  --env-file "$PWD/.env" \
  -v "$PWD/storage:/app/storage" \
  mistral-tts:reviewed
```

For deliberate LAN access, replace `127.0.0.1` with the host's LAN interface IP.
Avoid publishing on all host interfaces. Disable router port forwarding/UPnP
exposure for this port and verify access rules on the Docker host. Docker port
publication can interact with host firewall rules; test from both an allowed
and a disallowed network rather than assuming a firewall rule covers Docker.

These are examples for creating a replacement container, not commands to run
alongside an existing one with the same name. Record the old image and back up
stopped whole-storage data before replacing a deployment, as described in
[Operations](OPERATIONS.md). Recreating a container interrupts unfinished jobs
and clears sessions. No automatic paid work resumes after restart.

## HTTP and HTTPS

For ordinary HTTP in a trusted LAN, `SESSION_COOKIE_SECURE=false` permits the
browser to send the session cookie. The application cannot encrypt HTTP traffic:
passwords, sessions, documents and keys are exposed to an observer on that path.
HTTPS is recommended in LAN as well, particularly on shared Wi-Fi. Keeping this
setting false does not disable HttpOnly, SameSite or server-side session expiry.

For HTTPS, use a configured TLS reverse proxy and
`SESSION_COOKIE_SECURE=true`. Keep the plain backend private, redirect client
HTTP to HTTPS and verify the certificate in a real browser. Do not set Secure
on an HTTP-only endpoint and expect login to work.

The default Docker command and desktop launcher use no forwarded-header trust.
If a proxy is installed, opt in with `--proxy-headers` and
`--forwarded-allow-ips=ACTUAL_PROXY_SOURCE_IP`. It must overwrite client-supplied
forwarding headers. Never use `*` on a reachable backend. A host proxy's address
as seen by a bridged container is often its gateway, not `127.0.0.1`.

For an existing Nginx HTTPS virtual host, the following location illustrates
limits compatible with the default application budgets. Certificate paths,
hostname, trusted proxy IP and network routing remain deployment-specific:

```nginx
location / {
    client_max_body_size 32m;
    client_body_timeout 15s;
    proxy_pass http://127.0.0.1:8091;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header Connection "";
    proxy_request_buffering on;
    proxy_buffering off;
    proxy_read_timeout 60s;
}
```

This is not a complete TLS virtual host and is unnecessary for the current
direct LAN setup. `client_body_timeout` limits idle reads, not total upload time.
With proxy request buffering, the application's 120-second total body deadline
starts when the proxy forwards the body; add proxy/edge total-duration limits
if that threat model requires them. SSE emits events every 0.5 seconds; disabling
response buffering keeps progress visible. Adjust proxy limits together with
application budgets when intentionally accepting larger/slower uploads.

## Request protection in the image

- Anonymous generate/resume requests get `401` before body reception, storage
  checks and queue admission. A valid session is checked again by the endpoint.
- Authenticated generate/resume bodies have a 32 MiB limit, including form
  overhead. Other bodies, including auth/config JSON and forms, have a 64 KiB
  limit. Both apply before parsing, including chunked transfer or understated
  Content-Length; exceeding the limit returns `413`.
- Body reception has a 120-second total and 15-second idle deadline. A timeout
  returns `408` and releases the spool/slot. Generation, queue waits, downloads
  and SSE are not restricted to 120 seconds by these body deadlines.
- `MAX_JSON_REQUEST_BYTES`, `MAX_REQUEST_BYTES`,
  `REQUEST_BODY_TIMEOUT_SECONDS` and `REQUEST_BODY_IDLE_TIMEOUT_SECONDS` can be
  changed with positive integer environment values; invalid values prevent
  startup. Restart/recreate the container after changing settings.
- Usernames have a 256-character limit, passwords a 1024-character limit and
  model IDs a 100-character limit. Existing usernames/passwords beyond these
  bounds need operator-assisted credential replacement; never copy them into logs.

## Record and verify the deployed artifact

Run these on the Docker host, replacing the container name if necessary. They
show image identity and published ports without dumping environment secrets:

```bash
docker inspect --format '{{.Config.Image}} {{.Image}} {{json .NetworkSettings.Ports}}' mistral-tts
docker image inspect --format '{{.Id}} {{json .RepoDigests}}' IMAGE_ID_FROM_PREVIOUS_COMMAND
```

Keep the immutable ID/digest, source revision and selected non-secret security
settings with release records. A mutable tag or a matching UI page does not
prove the deployed source version. Locally built images may have no RepoDigest;
record their image ID and checkout revision instead. Do not expose the Docker
API to obtain this information remotely.

After deploying a reviewed image, verify:

1. The expected image ID/digest is running and only the intended interface is
   published; disallowed network access and backend bypass are blocked.
2. Anonymous generate/resume/config requests are rejected; real login works,
   and cookies have HttpOnly/SameSite plus Secure when using HTTPS.
3. Oversized control bodies get `413`. Test upload timeout/queue behavior only
   in a disposable environment; do not run a denial-of-service probe on a live
   service.
4. A synthetic local job can upload, stream SSE, download audio and resume after
   an intentional restart. Use the offline Docker smoke suite for fake provider
   work; it does not require sending real API keys or buying generation.

The code changes do not update an existing running container. The LAN checks
above remain a snapshot of the previous deployment until its operator rebuilds
and replaces it and records the acceptance results.

## Implementation verification (2026-11-18)

On branch `fix/web-request-security`, the complete offline suite passed:
**540 tests**, including 35 new request-security cases. Ruff passed. The runtime
Docker smoke suite passed **7 checks**, including real HTTP auth/upload, synthetic
audio, SSE, download and restart. The portable Unicode-checkout smoke passed
its selected **112 tests**; these overlap the full suite and are not additional
coverage counts. No paid provider requests or production writes were performed.

The local build is tagged `mistral-tts:security-1-2`; it is not published or
installed on the LAN host. This change addresses plan items 1–2 and does not
claim to remove the dependency/FFmpeg vulnerabilities reserved for later items.
It follows PROJECT.md's single-worker model and retains the audio pipeline,
resume contract and SDK pin without new dependencies.

The subsequent [media/dependency refresh](audit/SECURITY_REMEDIATION_2_3_2026-11-18.md)
has not been built into an image, by operator instruction. The tag above still
identifies the earlier request-protection build, not the latest source changes.

The [password/CSRF/XML stage](audit/SECURITY_REMEDIATION_5_2026-11-18.md) also remains
source-only. Before a future upgrade, configure a 12-1024-character environment
password if there is no persisted auth file. A persisted short password gives
only a change-password session. The browser adds the write-request header
automatically; non-browser HTTP integrations must send
`X-Requested-With: Booksmith` if they omit Origin. HTTPS proxies must establish
the actual scheme through explicitly trusted Uvicorn proxy settings.

The [SDK/native update](audit/SECURITY_DEPENDENCY_UPDATES_2026-11-18.md) selects
Mistral 2.10.1 and patched OpenTelemetry in the locks. Dockerfile now prepares
an audio-only FFmpeg 9.0.2 without libxml2; local native tests passed, but this
stage has not built/published an image or changed the LAN deployment either.


### Current authorized release: 1.0.5

The operator subsequently authorized building and publishing the updated image.
`marcinlis82/mistral-tts:1.0.5` (and `latest`, pointing at the same manifest) is
published for linux/amd64; earlier paragraphs record stage-specific verification
and the older local image. See the
[1.0.5 release checks and exact digest](audit/RELEASE_1.0.5_2026-11-24.md) and the
[1.0.4 remaining CVEs](audit/RELEASE_1.0.4_2026-11-18.md).
The LAN deployment has not been changed by publishing this image.
