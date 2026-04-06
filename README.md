<!-- mcp-name: io.github.jasoncbraatz/domain-monitor-mcp -->

# domain-monitor-mcp

An unofficial MCP (Model Context Protocol) server for [domain-monitor.io](https://domain-monitor.io), enabling AI assistants like Claude to query your domain expiration data directly — no browser required.

> **Note**: This is a community project, not officially supported by domain-monitor.io. It uses the internal API discovered by inspecting browser network traffic. If you're the domain-monitor.io developer and would like to collaborate on an official MCP server or public API, please open an issue — we'd love to work with you!

---

## What it does

Once installed, you can ask Claude things like:

- *"Any domains expiring in the next 30 days?"*
- *"When does braatz.io expire?"*
- *"Give me a domain health overview"*
- *"List all my domains sorted by expiry date"*
- *"Add newdomain.com to domain monitor with a 60-day alert"*

No more digging through emails that landed in spam or SMS alerts that got filtered. Just ask.

---

## Tools provided

| Tool | Description |
|------|-------------|
| `domain_monitor_get_expiring_soon` | Quick check — domains expiring within your alert window |
| `domain_monitor_list_domains` | Full paginated list with optional filter by days-until-expiry |
| `domain_monitor_check_domain` | Look up a specific domain by name |
| `domain_monitor_get_account_summary` | Account stats, subscription status, and active alerts |
| `domain_monitor_add_domain` | Add a new domain to monitoring with a configurable alert period |

---

## Installation

### Option A: Install from PyPI (recommended)

```bash
pip install domain-monitor-mcp
```

Or with [uv](https://docs.astral.sh/uv/) (faster):

```bash
uv pip install domain-monitor-mcp
```

Then add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "domain-monitor": {
      "command": "domain-monitor-mcp",
      "env": {
        "DOMAIN_MONITOR_EMAIL": "your@email.com",
        "DOMAIN_MONITOR_PASSWORD": "yourpassword"
      }
    }
  }
}
```

Or run directly with uvx (no install needed):

```json
{
  "mcpServers": {
    "domain-monitor": {
      "command": "uvx",
      "args": ["domain-monitor-mcp"],
      "env": {
        "DOMAIN_MONITOR_EMAIL": "your@email.com",
        "DOMAIN_MONITOR_PASSWORD": "yourpassword"
      }
    }
  }
}
```

### Option B: Clone from source

#### Prerequisites

- Python 3.10+
- A [domain-monitor.io](https://domain-monitor.io) account (free or paid)
- Claude Desktop (or any MCP-compatible client)

#### 1. Clone this repo

```bash
git clone https://github.com/jasoncbraatz/domain-monitor-mcp.git
cd domain-monitor-mcp
```

#### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Or with uv (faster):

```bash
uv pip install -r requirements.txt
```

#### 3. Configure Claude Desktop

Add the following to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "domain-monitor": {
      "command": "python",
      "args": ["/absolute/path/to/domain-monitor-mcp/server.py"],
      "env": {
        "DOMAIN_MONITOR_EMAIL": "your@email.com",
        "DOMAIN_MONITOR_PASSWORD": "yourpassword"
      }
    }
  }
}
```

> Replace `/absolute/path/to/domain-monitor-mcp/server.py` with the actual path where you cloned this repo.

#### 4. Restart Claude Desktop

After saving the config, fully quit and relaunch Claude Desktop. The `domain-monitor` tools will appear in Claude's tool list.

---

## Authentication

This server authenticates using your domain-monitor.io email and password via Laravel Sanctum session auth — the same mechanism the website uses under the hood. Sessions are maintained in memory and automatically refreshed if they expire.

**Your credentials are never stored to disk** — they live only in the environment variables you configure above, and only in memory while the server is running.

---

## How it works (for the curious / developers)

domain-monitor.io is a Nuxt.js SPA backed by a Laravel API. The API lives at `https://api.domain-monitor.io/`. Authentication follows the standard Laravel Sanctum CSRF + session cookie flow:

1. `GET https://api.domain-monitor.io/sanctum/csrf-cookie` — sets `XSRF-TOKEN` + `domain_monitor_session` cookies
2. `POST https://api.domain-monitor.io/login` with `{email, password}` + `X-XSRF-TOKEN` header — authenticates
3. Subsequent requests to `https://api.domain-monitor.io/api/*` use the session cookies + refreshed XSRF token

Key endpoints used:
- `GET /api/account` — account info + user ID
- `GET /api/account-dashboard` — summary with expiring domains and alerts
- `GET /api/account/{user_id}/domains` — paginated domain list with expiry data
- `POST /api/domains` — add a new domain to monitoring

The API rate limit is 200 requests per session (observed from `x-ratelimit-limit` response headers).

---

## Contributing

PRs welcome! Some ideas for future improvements:

- ~~Add domain to monitoring~~ Done (`domain_monitor_add_domain`)
- Support for uptime monitor queries
- Webhook/notification preference management
- Support for the domain availability checker

**Note on deletions:** Removing a domain from monitoring is intentionally not supported here — that's a destructive action best done through the domain-monitor.io web UI where you can see exactly what you're removing. A little friction before deleting things is a feature, not a bug.

If you're the domain-monitor.io developer and want to add official API token support, this project would love to adopt it — just open an issue!

---

## Disclaimer

This project is not affiliated with, endorsed by, or officially supported by domain-monitor.io. It was built by reverse-engineering the browser network traffic. Use at your own risk. The API may change without notice.

## License

MIT
