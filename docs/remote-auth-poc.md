# ServiceNow end-user authorization over remote MCP

## Objective and scope

Allow users to choose an OAuth-capable remote MCP client and access ServiceNow
with their own account permissions. Deploy one Streamable HTTP endpoint over
HTTPS. Corporate SSO is used through ServiceNow's existing login integration;
ServiceNow remains the authority for roles, record ACLs, field ACLs, and API access.

This POC is a separate, read-only entry point: `python -m servicenow_mcp.servers.remote`.
It exposes `list_records` and `get_record` for `incident`, `task`, `sc_task`,
`problem`, and `change_request`, plus the read-only service-desk tools
`list_incidents`, `get_incident`, `list_knowledge_articles`, and
`get_change_status` (see [service-desk specifications](service-desk-tools.md)).
The outbound client allows only GET Table API requests to those five tables and
`kb_knowledge`. Knowledge results rely on the user's `kb_knowledge` table and
field ACLs. They don't evaluate portal user criteria. It does not grant roles, accept user IDs as
identity assertions, impersonate users, or use the local integration account.
The existing stdio entry point and write-preview tools are separate.

If HR records are in `sn_hr_core_case` rather than `incident`, that table is not
exposed by this POC. A reviewed table allowlist extension would be needed.
UI visibility alone is not a security rule: verify that record and field ACLs
actually enforce the intended restriction for REST requests.

## Architecture

```mermaid
sequenceDiagram
    participant C as Chosen MCP client
    participant B as MCP OAuth broker
    participant S as ServiceNow
    participant I as Corporate SSO IdP
    C->>B: Discover protected resource and authorization metadata
    C->>B: Identify by approved client metadata URL (CIMD), or DCR if enabled
    C->>B: Authorize with state, resource and PKCE S256
    B->>C: Browser consent for this MCP client
    B->>S: Redirect browser to oauth_auth.do
    S->>I: SSO login if needed
    I->>S: Authenticated company user
    S->>B: Authorization code at /auth/callback
    B->>S: Exchange code at oauth_token.do
    B->>B: Encrypt upstream tokens and bind to client grant
    B->>C: One-time broker authorization code
    C->>B: Exchange broker code with PKCE verifier
    B->>C: MCP access/refresh tokens (not ServiceNow tokens)
    C->>B: Tool call with MCP access token
    B->>B: Verify signature, expiry, audience and stored grant
    B->>S: Validate upstream token against authenticated identity endpoint
    S->>B: Current user ID
    B->>S: Table API read with that user's ServiceNow token
    S->>S: Enforce ACLs for current user
    S->>B: Authorized records and fields, or access error
    B->>C: Tool result
```

FastMCP 4.0.5 `OAuthProxy` implements discovery, client registration, consent,
PKCE, state, code exchange, signed MCP reference tokens, refresh, and token
lookup. We provide a ServiceNow-specific upstream token verifier. Tokens are
validated with an identity endpoint on every authenticated request, without an
identity/role cache. Tool calls create a fresh client from the verified request
context, including when synchronous tools run in a worker thread.

There are two independent trust boundaries:

| Boundary | Credential | Enforcement |
| --- | --- | --- |
| Client → MCP | Broker-issued access token for `https://mcp.example.com/mcp` | Broker signature, expiry, audience, stored grant, approved callback, upstream validation |
| MCP → ServiceNow | User's ServiceNow access token | ServiceNow authentication, API restrictions and ACLs |

Raw ServiceNow tokens cannot authenticate directly to `/mcp`. No upstream secret
is returned as a tool result. The corporate IdP's login session is not itself
a ServiceNow API credential. Each client authorization obtains a separate grant;
an existing SSO session can avoid another password prompt, but consent may still
be required. Direct IdP authorization and identity-assertion/token-exchange grants
are outside this POC.

## ServiceNow setup

Perform this setup in a test instance with corporate SSO enabled. The repository
contains the resource script, not an automatically deployed ServiceNow application.

1. Create an OAuth API endpoint for external clients in Application Registry.
   Enable the authorization-code flow and configure the **broker** redirect URI:
   `https://mcp.example.com/auth/callback`. The MCP clients' individual callbacks
   belong in the broker's allowlist, not this ServiceNow registration.
2. Record the client ID/secret in `.env.remote`. No user access or refresh token
   belongs in that file.
3. Create a Scripted REST API with an authenticated GET resource `/me`. The
   example expected path is `/api/x_mcp_poc/identity/me`; ServiceNow's generated
   namespace may differ. Put the actual path in `POC_IDENTITY_PATH`.
4. Require authentication at both API and resource levels, and ensure the
   endpoint's REST access rules permit the test users. Do not require admin or
   grant broad user-table read access. Use [poc_identity.js](../servicenow/poc_identity.js).
   It returns only the current caller's ID and username, checks their active flag,
   and rejects guests. Configure OAuth endpoint restrictions/scopes, if used on
   your instance, to allow both this endpoint and the intended Table API reads,
including `kb_knowledge`.
5. Verify the identity response with a personal OAuth token:
   `{"result":{"sys_id":"<32 lowercase hex characters>","user_name":"user.a"}}`.
   ServiceNow adds the `result` envelope around `response.setBody`; the script
   intentionally supplies the inner object. Unauthenticated requests must fail.
6. Verify end-user ACLs independently with direct Table API calls. Do not change
   roles merely to make the POC work. API access may be more restrictive than UI
   access because of web-service and endpoint restrictions.

### Restrict what the broker's tokens can call

Without a scope restriction, a user's token from the OAuth app can call any
ServiceNow API that user may use. Before production, limit it to the two APIs
the broker needs: the Table API and the identity Scripted REST API.

1. On the OAuth app, add a dedicated auth scope, for example `mcp_read`.
2. Create a **REST API Auth Scope** record for the Table API and one for the
   identity API, each with that auth scope. Exact module names vary by release;
   search the ServiceNow docs for "REST API auth scope".
3. Set `POC_SERVICENOW_SCOPE=mcp_read` in `.env.remote` and restart the broker.
   It then requests exactly that scope at every sign-in; MCP clients cannot
   request ServiceNow scopes themselves.
4. Verify: sign in again, and confirm the tools still work and that the same
   token is refused by an API outside the scope.

Auth scopes work per API, not per table. The broker's outbound client limits
Table API reads to the six tables it uses, and ServiceNow ACLs still apply.

The broker is a confidential ServiceNow OAuth client and authenticates with its
client secret. Upstream PKCE forwarding defaults to false: some ServiceNow
releases treat a PKCE challenge as public-client mode and reject a client secret
at token exchange. Enable `POC_FORWARD_PKCE=true` only after verifying that your
instance supports PKCE together with confidential clients. Client-to-broker PKCE,
consent and state validation remain required in either mode. The broker does not
forward the MCP `resource` indicator to ServiceNow,
whose OAuth endpoint is not assumed to implement MCP resource indicators.
The POC requests no additional OAuth scopes. Instance-specific scope setups must
be validated before use; the POC does not infer roles from OAuth scope strings.

## Run the POC

Use Python 3.11+ and a dedicated environment with the remote extra:

```bash
python3 -m venv .venv-remote
.venv-remote/bin/python -m pip install -e ".[remote]"
cp -n .env.remote.example .env.remote
```

Generate independent keys, place the outputs in `POC_SIGNING_KEY` and
`POC_ENCRYPTION_KEY`, and protect `.env.remote` with mode 600. Do not share outputs:

```bash
.venv-remote/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'
.venv-remote/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
chmod 600 .env.remote
```

Set the instance, public HTTPS origin (without `/mcp`), client credentials,
identity path, and approved client callbacks. `POC_ALLOWED_REDIRECT_URIS` is a
comma-separated list of exact HTTPS or loopback HTTP callback URLs. There is no
default wildcard. Use the actual callback documented or used by each client.
Environment variables override `.env.remote`. Run from the directory containing
that file, or set `MCP_REMOTE_ENV_FILE` to its absolute path. For a reproducible
remote runtime in `.venv`, use `uv sync --locked --no-dev --extra remote`.

```bash
.venv-remote/bin/python -m servicenow_mcp.servers.remote
```

The process binds to `127.0.0.1:8000`. Terminate TLS using a reverse proxy on the
same host. A minimal Caddy configuration is provided in
[Caddyfile.poc](../deploy/Caddyfile.poc); replace its hostname with your configured
public origin and provision DNS/network access. All OAuth paths and `/.well-known`
paths must be proxied, not just `/mcp`. Preserve the public Host header.
HTTPS applies to both the browser authorization routes and MCP endpoint.

The POC uses stateless HTTP with JSON responses for these request/response tools.
It has no GET notification stream and no legacy `/sse` endpoint. OAuth grant
state is persistent even though MCP transport sessions are stateless.

## Token lifetimes

Three lifetimes apply. Get the values approved by security before production
and record the approved settings here.

| Lifetime | Set by | Default | Effect |
| --- | --- | --- | --- |
| ServiceNow access token | OAuth app **Access Token Lifespan** in ServiceNow | 1,800 s (30 min) | The broker refreshes it transparently. Every request is also checked against the identity endpoint, so revoking a user takes effect on their next request. |
| Client sign-in (broker refresh token) | `POC_SESSION_LIFETIME_SECONDS` | 86,400 s (24 h) | How long Claude stays signed in before the user signs in again. Allowed range: 1 hour to 30 days. ServiceNow returns no refresh-token expiry, so this setting decides. |
| ServiceNow refresh token | OAuth app **Refresh Token Lifespan** in ServiceNow | 8,640,000 s (100 days) | An upper bound: if it expires first, the next refresh fails and the user signs in again. Set it at or above the sign-in lifetime. |

The broker's `fallback_access_token_expiry_seconds=300` is used only if a
ServiceNow token response ever omits `expires_in`.

## Claude pilot on macOS with an HTTPS tunnel

Use a test instance and confirm your organization permits ServiceNow data to pass
through Claude and the tunnel provider. Claude connects from Anthropic's cloud,
even when using Claude Desktop, so a localhost URL or a Mac-only VPN route is not
enough. Your Mac must be able to reach ServiceNow; the browser must also reach
ServiceNow and its SSO provider. Keep the Mac awake and connected during the pilot.

Install ngrok and authenticate the agent locally using its dashboard instructions.
Never paste its account token into chat or commit it. Use the stable dev domain
assigned to your ngrok account, replacing `your-assigned-domain.ngrok-free.app`
below with the actual hostname. No Caddy instance or owned domain is required.

Keep these three URLs distinct:

| Setting | Value |
| --- | --- |
| `POC_PUBLIC_URL` | `https://your-assigned-domain.ngrok-free.app` |
| ServiceNow OAuth application redirect | `https://your-assigned-domain.ngrok-free.app/auth/callback` |
| `POC_ALLOWED_REDIRECT_URIS` | `https://claude.ai/api/mcp/auth_callback` |

Use the confidential ServiceNow client and authenticated identity resource from
the setup above. Keep `POC_FORWARD_PKCE=false` unless upstream compatibility is
verified. Give `POC_STORAGE_DIR` an absolute path to a directory with mode 700;
keep the independent signing/encryption keys and mode-600 environment file stable
across restarts. Do not overwrite an existing configuration or use the local
stdio server's user tokens as remote credentials.

From the repository root, install the locked environment and check the remote
authentication slice before exposing it:

```bash
uv sync --locked --all-extras --group dev
uv run --locked pytest -q tests/test_remote_auth.py tests/test_environment.py
uv run --locked python -m servicenow_mcp.servers.remote
```

In a separate terminal, forward the whole origin, not just `/mcp`:

```bash
ngrok http http://127.0.0.1:8000 --url https://your-assigned-domain.ngrok-free.app --inspect=false
```

Preserve the public Host header and Authorization header. Do not add ngrok Basic
Auth or another OAuth login in front of the broker. `--inspect=false` disables
local HTTP inspection; review provider-side traffic capture and retention too.
Keep OAuth query strings, codes, tokens, headers, and response bodies out of logs.

Check the public endpoint without extra bypass headers:

```bash
PUBLIC_URL=https://your-assigned-domain.ngrok-free.app
curl --fail --silent --show-error "$PUBLIC_URL/.well-known/oauth-protected-resource/mcp"
curl --fail --silent --show-error "$PUBLIC_URL/.well-known/oauth-authorization-server"
curl --include --silent --show-error "$PUBLIC_URL/mcp" \
   -H 'Content-Type: application/json' \
   -H 'Accept: application/json, text/event-stream' \
   --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"pilot-preflight","version":"1.0"}}}'
```

Discovery must return JSON, with `resource` exactly equal to the public `/mcp`
URL and public HTTPS issuer/endpoint URLs. The authorization metadata must
advertise S256 PKCE and `client_id_metadata_document_supported: true`; it lists a
`registration_endpoint` only when dynamic registration is enabled (see "Approved
clients"). The unauthenticated MCP POST must
return `401` with a `WWW-Authenticate` resource-metadata pointer. An HTML warning,
localhost redirect, or host-validation error is not a successful preflight.
Claude allows 10 seconds for discovery, registration, and token exchange, and
30 seconds for refresh requests.

The ngrok free tier can show an initial warning for HTML browser traffic. Visit
the public origin and acknowledge the warning before beginning a fresh sign-in;
API traffic should not need a custom bypass header. If the warning blocks the
OAuth flow, use a tunnel tier without the interstitial rather than disabling
broker authentication.

In Claude, open **Customize > Connectors > Add custom connector**. For a managed
organization, an authorized administrator first adds the connector under
**Organization settings > Connectors**. Enter the exact public URL with `/mcp`
and no trailing slash. Choose OAuth sign-in and **Register automatically** for
the OAuth client. Leave fixed request credentials unset: the ServiceNow client
ID and secret belong only in the broker configuration, not in Claude.

Complete broker consent and ServiceNow sign-in, then enable the connector for a
conversation. Only the six read tools should be available: `list_records`,
`get_record`, `list_incidents`, `get_incident`,
`list_knowledge_articles`, and `get_change_status`. Complete
the two-user ACL, refresh, revocation, and restart checks below before accepting
the pilot; passing mock tests is not proof of live Claude or ServiceNow access.

When finished, disconnect the connector and stop the tunnel and server. Revoke
upstream grants explicitly when required; disconnecting Claude alone does not
prove ServiceNow grant revocation. If the public hostname changes, update both
`POC_PUBLIC_URL` and the ServiceNow callback, restart the broker, and re-add and
reauthorize the Claude connector. This single-worker tunnel setup is a pilot,
not a production deployment.

## Approved clients

Only approved MCP clients can sign in. A client identifies itself either by a
client ID metadata document (CIMD), an HTTPS URL describing it, which is how
Claude connects, or by dynamic client registration (DCR) at `/register`.

| Setting | Default | Effect |
| --- | --- | --- |
| `POC_APPROVED_CLIENTS` | `https://claude.ai/oauth/mcp-oauth-client-metadata` | Comma-separated exact HTTPS metadata URLs. Any other URL is rejected before it is fetched. |
| `POC_ALLOW_DYNAMIC_REGISTRATION` | `false` | `true` re-enables `/register` for any client. Use it only for a client that cannot use CIMD. |

- The approval check runs on every client lookup: `/authorize`, token exchange
  and refresh. Removing a client from the list ends its existing sign-ins at
  their next refresh.
- FastMCP would otherwise treat a request carrying the ServiceNow OAuth app's
  own client ID as an implicit client. That ID is not a secret, so the broker
  rejects it.
- The client callback allow-list (`POC_ALLOWED_REDIRECT_URIS`) still applies
  on top of this policy.

## Connect a client

Choose a client supporting Streamable HTTP and OAuth authorization code with
PKCE, and approve it first (see "Approved clients"). Configure:

```text
URL:       https://mcp.example.com/mcp
Transport: Streamable HTTP
Auth:      OAuth / automatic discovery
```

The client discovers the broker, opens consent, and redirects through ServiceNow
SSO. It stores its own MCP tokens. Never paste a ServiceNow password/token into
chat or configure a shared API token as an alternative authentication method.
Client configuration syntax and network reachability differ: cloud-hosted clients
need the endpoint reachable from their cloud, while local clients connect from
the user's device. Client compatibility must be tested individually; supporting
MCP tools alone does not guarantee OAuth support.

Useful endpoints:

| Path | Purpose |
| --- | --- |
| `/mcp` | Protected Streamable HTTP tools |
| `/.well-known/oauth-protected-resource/mcp` | Resource metadata |
| `/.well-known/oauth-authorization-server` | Broker metadata |
| `/register` | Dynamic client registration; present only when `POC_ALLOW_DYNAMIC_REGISTRATION=true` |
| `/authorize`, `/consent`, `/token` | Browser authorization and token exchange |
| `/auth/callback` | ServiceNow → broker callback |

## Verification and limits

For the full automated suite, install the locked development environment with
`uv sync --locked --all-extras --group dev` and run `uv run --locked pytest -q`. The automated tests use fake
ServiceNow responses; they do not create live records or change instance roles.
They exercise actual HTTP discovery/consent/callback/token routes, PKCE failure,
code replay, tampering, audience validation, direct upstream-token rejection,
approved callbacks, concurrent user contexts, upstream refresh, revocation,
encrypted storage and restart continuity, and propagated API access errors.
They verify credential routing, not the correctness of your live ACL rules.

Before accepting the live POC, use two non-admin users with different ACLs:

| Check | Expected |
| --- | --- |
| A lists incidents without an HR filter | Only ACL-readable records/fields returned |
| A searches incidents and knowledge with `list_incidents` / `list_knowledge_articles` | Only records A can read in ServiceNow |
| A gets a forbidden record by known sys_id | No protected record returned |
| A requests a forbidden field explicitly | No protected field returned |
| A and B read concurrently, including through different clients | Each gets only their authorized data |
| A's ServiceNow token is revoked/account disabled | Subsequent requests fail closed; B still works |
| Client refreshes its MCP grant | Same user's upstream credential remains bound |
| Broker restarts with the same keys/store | Existing unexpired grants still work |
| Client attempts a write | No write tool exists; outbound client also rejects non-GET requests |

No live SSO, client GUI, HTTPS deployment, or instance ACL verification is implied
by passing the mock tests. The Scripted REST resource needs instance deployment
and verification, including namespace and authentication settings.

Local state is encrypted with an explicit independent Fernet key under
`POC_STORAGE_DIR` (default `.oauth-poc`, ignored by Git). Keep keys stable across
restarts and back up keys/store together in protected storage. Losing either
requires reauthorization; rotating keys without migration also requires it.
Run one worker: file storage and process-local refresh locks are not a distributed
authorization database. Use restrictive directory permissions; the launcher sets
umask 077. Keep OAuth query strings, secrets, codes and authorization headers out
of proxy/access/debug logs. The sample proxy does not enable access logging.

Production follow-ups: reviewed shared storage with distributed refresh locking,
audit correlation without sensitive payloads, and client compatibility. Secrets,
key rotation, rate limits, client approval, log redaction, OAuth scopes and
revocation are covered in [deployment](deployment.md) and the sections above.
Write support additionally requires binding previews to the authenticated user,
adapting the existing session-based confirmation mechanism for stateless HTTP,
and enforcing user authorization again at confirmation time.

### Token exchange troubleshooting

If ServiceNow returns `server_error: access_denied`, verify the registered callback
matches the current public origin plus `/auth/callback`, the app is active, and
the local client secret is the actual secret rather than a masked display value.
For this broker, the ServiceNow application should be a confidential client.
If instance OAuth logs report a client-secret failure in public-client mode,
ensure `POC_FORWARD_PKCE=false` and restart the broker. Start a fresh client
authorization; old authorization codes cannot be reused. Never grant admin or
change record ACLs to resolve a token-exchange error.

## References

- [MCP authorization](https://modelcontextprotocol.io/specification/latest/basic/authorization)
- [MCP transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [FastMCP OAuth proxy](https://gofastmcp.com/servers/auth/oauth-proxy)
- [ServiceNow SSO authorization workflow](https://www.servicenow.com/docs/r/platform-security/authentication/authorization-workflow.html)
- [ServiceNow REST API security](https://www.servicenow.com/docs/r/api-reference/rest-api-explorer/c_RESTAPI.html)
- [ServiceNow scripted REST response envelope](https://www.servicenow.com/docs/r/api-reference/rest-api-explorer/c_SpecifyContentType.html)
