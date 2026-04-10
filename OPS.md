# OPS.md — domain-monitor-mcp Operations & Troubleshooting

This document is written for a future Opus session that needs to reinstall,
debug, or extend the domain-monitor-mcp server. It captures hard-won
knowledge from the April 2026 debugging sessions.

---

## Quick Start (fresh Mac install)

```bash
# 1. Clone
git clone https://github.com/jasoncbraatz/domain-monitor-mcp.git
cd domain-monitor-mcp

# 2. Install deps (use uv if available)
pip install -r requirements.txt
# OR
uv pip install -r requirements.txt

# 3. Add to Claude Desktop config
#    macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
#    See claude_desktop_config_example.json for the template
#    Set DOMAIN_MONITOR_EMAIL and DOMAIN_MONITOR_PASSWORD env vars

# 4. Restart Claude Desktop (full quit + relaunch)
```

---

## Architecture

```
Claude Desktop
  │
  ├─ MCP stdio transport
  │
  └─ server.py (FastMCP)
       │
       ├─ _authenticate()  → CSRF cookie + login + XSRF token rotation
       ├─ _api_get()       → GET with auto-retry on 401
       ├─ _api_post()      → POST with auto-retry on 401
       │
       ├─ Tool: domain_monitor_list_domains
       ├─ Tool: domain_monitor_get_expiring_soon
       ├─ Tool: domain_monitor_check_domain
       ├─ Tool: domain_monitor_get_account_summary
       └─ Tool: domain_monitor_add_domain
```

The server is a single-file Python script using:
- **FastMCP** (from `mcp[cli]`) for the MCP server framework
- **httpx** for async HTTP with cookie jar support
- **Pydantic** for input validation

---

## API Details (reverse-engineered)

Base URL: `https://api.domain-monitor.io`

The Nuxt frontend uses axios with baseURL `https://api.domain-monitor.io`.
The server.py uses `API_BASE = "https://api.domain-monitor.io/api"` and
appends paths like `/account/{user_id}/domains`.

### Authentication Flow

1. `GET /sanctum/csrf-cookie` — sets XSRF-TOKEN + domain_monitor_session cookies
2. `POST /login` with `{"email": "...", "password": "..."}` + X-XSRF-TOKEN header
3. Laravel rotates the XSRF token after login — must re-read from cookies
4. `GET /api/account` to resolve user_id (needed for domain endpoints)

### Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/account` | Returns user object with `id` field |
| GET | `/api/account-dashboard` | Summary: expiring domains, alerts, counts |
| GET | `/api/account/{user_id}/domains` | Paginated. Params: page, orderBy, sortBy, perPage |
| POST | `/api/account/{user_id}/domains` | **REQUIRED fields below** |

### POST /api/account/{user_id}/domains

This endpoint was the source of a painful debugging session. The payload
MUST include these fields or you get a 400 validation error:

```json
{
  "domain": "example.com",
  "alert_period": 30,
  "certificate_checks_enabled": true,
  "dns_checks_enabled": true,
  "blacklist_checks_enabled": false
}
```

**Gotcha**: `blacklist_checks_enabled: true` may fail with a 400 if the
account has exceeded its blacklist monitor limit on the current plan.
Default to `false` unless the user specifically asks for it.

### Required Headers

```
Accept: application/json
Content-Type: application/json
Origin: https://domain-monitor.io
Referer: https://domain-monitor.io/
X-Requested-With: XMLHttpRequest
X-XSRF-TOKEN: <url-decoded XSRF-TOKEN cookie value>
```

### Rate Limits

200 requests per session (from `x-ratelimit-limit` response header).

---

## Common Failures & Fixes

### "Error: Resource not found" on add_domain

**Root cause**: Missing required boolean fields in POST payload.
The API returns 400 with validation errors, but if error handling
is too generic it may report as 404-like.

**Fix**: Ensure payload includes `certificate_checks_enabled`,
`dns_checks_enabled`, and `blacklist_checks_enabled`.

### "Error: Validation failed" with blacklist message

**Root cause**: Account has exceeded blacklist monitor limit.

**Fix**: Set `blacklist_checks_enabled: false` (this is the default).

### MCP server won't start / connect

1. Check Claude Desktop logs: `~/Library/Logs/Claude/mcp-server-domain-monitor.log`
2. Verify Python path: `which python` — must match what's in claude_desktop_config.json
3. Test manually: `python /path/to/server.py` — should start without errors
4. Check deps: `pip list | grep -E 'mcp|httpx|pydantic'`

### Session expires mid-conversation

The server auto-retries once on 401. If it keeps failing:
1. Check that DOMAIN_MONITOR_EMAIL/PASSWORD are correct
2. domain-monitor.io may be down — check https://domain-monitor.io
3. The API may have changed — check browser DevTools network tab

### Debugging API changes

If the API changes, here's how to reverse-engineer the new endpoints:

1. Open https://domain-monitor.io in Chrome
2. Open DevTools > Network tab, filter by Fetch/XHR
3. Perform the action in the web UI
4. Look for requests to `api.domain-monitor.io`
5. Check the request method, URL, headers, and payload
6. Also useful: `window.$nuxt.$axios.defaults.baseURL` in console
7. User ID: `window.$nuxt.$auth.user.id` in console

---

## Version History

| Date | Change |
|------|--------|
| 2026-04-10 | Fixed add_domain: added required boolean fields to POST payload |
| 2026-04-10 | Added 400 error handling with validation detail extraction |
| 2026-04-10 | Fixed README: corrected POST endpoint from `/api/domains` to `/api/account/{user_id}/domains` |
| 2026-04-10 | Added OPS.md for future Opus sessions |
| 2026-04-09 | Initial add_domain tool (incorrect payload — missing boolean fields) |
| 2026-04-09 | Changed POST path from `/domains` to `/account/{user_id}/domains` |
| 2026-04-08 | Initial release: list, check, expiring_soon, account_summary tools |

---

## Repo Visibility

This repo is currently **public**. Consider making it private if you don't
want to expose the reverse-engineered API details. The credentials are
never committed (they're in env vars), so public is safe from a secrets
perspective.
