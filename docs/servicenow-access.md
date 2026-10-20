# ServiceNow access management

Record for STRY0013200 (MCP-04) for the production use case, the remote MCP
server behind the Claude connector. Owner: Do Ngoc Quy. Access approver:
_to be named by the ServiceNow platform owner_. Review quarterly and whenever
the tools change.

## The integration identity

The remote server reaches ServiceNow through one **dedicated OAuth client per
environment**, used by nothing else. It is a confidential client in the
ServiceNow OAuth Application Registry. No integration user record exists:
every API call runs with the signed-in user's own token, so ServiceNow applies
that user's roles and ACLs, and the audit trail shows the real person.

| Environment | Instance | OAuth client redirect URL | Status |
| --- | --- | --- | --- |
| Development | `dev.now.woven.tech` | `https://sublevel-awhile-passive.ngrok-free.dev/auth/callback` (server on a developer Mac behind a tunnel) | Being provisioned |
| Test | _to be provisioned_ | `https://<test domain>/auth/callback` | Not provisioned |
| Production | _to be provisioned_ | `https://<production domain>/auth/callback` | Not provisioned |

## Least privilege

| Layer | Control |
| --- | --- |
| OAuth client | Holds no roles and cannot act on its own; it only lets users sign in. |
| Tokens issued to it | Limited by an auth scope (`MCP_SERVICENOW_SCOPE`, required in test and production) to the Table API and the identity API, through REST API auth scopes. A token is refused by every other API. |
| What the server calls | GET only, to `incident`, `task`, `sc_task`, `problem`, `change_request` and `kb_knowledge`, plus the identity API. No writes exist on the remote server. |
| Each user | Their existing ServiceNow roles and ACLs; the server never elevates them. Users need read access to the records they should see through Claude, nothing more. |
| Who can sign in | Approved MCP clients only (`MCP_APPROVED_CLIENTS`, default Claude); open registration is off. |
| How long | Token lifetimes in [the remote guide](remote-server.md#token-lifetimes); revocation and offboarding in [deployment](deployment.md#revocation-and-offboarding). |

## Provisioning (per environment)

1. **Request and approve** the client for the environment; record it above.
2. **Create the OAuth client.** In **System OAuth > Application Registry**,
   create an OAuth API endpoint for external clients, confidential (no PKCE),
   with the environment's redirect URL, the approved token lifespans, and
   Active checked.
3. **Limit its tokens.** Add an auth scope (for example `mcp_read`) to the
   client and map the Table API and the identity API to it with REST API auth
   scopes; set the same value in `MCP_SERVICENOW_SCOPE`.
4. **Deploy the identity API** ([`servicenow/identity_api.js`](../servicenow/identity_api.js))
   and set `MCP_IDENTITY_PATH` to its path on this instance.
5. **Store the client secret** in the environment's secret manager and give
   it to the server as `MCP_SERVICENOW_CLIENT_SECRET_FILE`, never in a file of
   settings. Set `MCP_ENVIRONMENT` (below).
6. **Validate** with `servicenow-mcp-check-remote` and a first sign-in, then
   record the result below.

## Environment and network controls

`MCP_ENVIRONMENT` is `development`, `test` or `production`. In test and
production the server refuses to start unless:

| Rule | Why |
| --- | --- |
| No secret is written in the `.env.remote` file (use `<NAME>_FILE` or the platform's secret store) | Credentials never sit in plain-text configuration |
| `MCP_SERVICENOW_SCOPE` is set | Tokens reach only the APIs the server needs |
| `MCP_ALLOW_DYNAMIC_REGISTRATION` is `false` | Only approved clients can sign in |
| `MCP_SERVICENOW_REVOKE_PATH` is set | Sign-out and offboarding end ServiceNow grants |
| (production) `MCP_PUBLIC_URL` is not a tunnel host | Production runs on its own domain, not a developer tunnel |

Development logs the same findings as warnings, so a pilot keeps running.

- **Separate per environment:** each environment has its own OAuth client,
  redirect URL, secret, signing and encryption keys. A test client cannot sign
  users in to production, because ServiceNow only redirects to the client's
  registered URL.
- **HTTPS only:** the instance and public URL must be HTTPS.
- **Network, where supported:** the server's token exchanges, identity checks
  and Table API calls come from its egress addresses. If the instance restricts
  API access by IP address, allow those addresses. Users' browsers reach
  ServiceNow's sign-in page directly, as they do today. Instance-wide IP rules
  affect every user, so use per-integration controls if your release has them.

## Validation

`servicenow-mcp-check-remote` (exit code 0 = no failures) reads only and needs
no sign-in. It checks:

- the environment policy and where each secret comes from;
- that ServiceNow recognizes the OAuth client (its sign-in page opens for the
  configured redirect URL and scope);
- that the identity API refuses anonymous calls;
- if the server is reachable, that discovery hides `/register`, advertises
  `/revoke`, and `/mcp` requires sign-in.

A first sign-in, the auth-scope refusal and the two-user access test need a
real user; the command lists them as manual steps.

### Validation log

| Date | Environment | Result | Findings and action |
| --- | --- | --- | --- |
| 2026-10-20 | Demo (`dev436597`, before the move to DEV) | **Fail** (1 failure, 4 warnings) | OAuth client recognized and identity API protected (pass). Warnings: client secret, signing and encryption keys are plain text in `.env.remote`, and no auth scope is set; all would block test and production. Failure: the running pilot predates revocation (PR #29) and still advertises open registration; redeploy once the medium PRs merge. |
| – | Development (`dev.now.woven.tech`) | Not run | Configured with secret files and `MCP_ENVIRONMENT=development`; waiting for the OAuth client and identity API. |
| – | Test | Not run | Provision first. |

## Deprovisioning

To retire the server from an environment: deactivate its OAuth client in the
Application Registry, revoke the client's tokens under **System OAuth > Manage
Tokens**, remove its secrets from the secret manager, delete the token store
(`MCP_STORAGE_DIR`), and record it here.
