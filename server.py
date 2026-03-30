#!/usr/bin/env python3
"""
MCP Server for domain-monitor.io

Provides tools to query domain expiration data from domain-monitor.io,
enabling LLMs to answer questions like "what domains are expiring soon?"
without the user needing to open a browser.

Authentication uses the domain-monitor.io email/password credentials via
Laravel Sanctum session-based auth. Sessions are maintained in memory and
auto-refreshed on expiry.

Discovered API (unofficial - reverse engineered from browser network traffic):
  Base:      https://api.domain-monitor.io/api/
  Auth:      https://domain-monitor.io/api/auth/login  (POST)
  CSRF:      https://api.domain-monitor.io/sanctum/csrf-cookie  (GET)
  Dashboard: /api/account-dashboard
  Account:   /api/account
  Domains:   /api/account/{user_id}/domains
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_BASE = "https://api.domain-monitor.io/api"
AUTH_BASE = "https://domain-monitor.io"
CSRF_URL = "https://api.domain-monitor.io/sanctum/csrf-cookie"
LOGIN_URL = "https://domain-monitor.io/api/auth/login"

# Loaded from environment variables
EMAIL = os.environ.get("DOMAIN_MONITOR_EMAIL", "")
PASSWORD = os.environ.get("DOMAIN_MONITOR_PASSWORD", "")

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class _Session:
    """Holds the authenticated httpx client and user_id across tool calls."""
    client: Optional[httpx.AsyncClient] = None
    user_id: Optional[int] = None

_session = _Session()


async def _get_client() -> httpx.AsyncClient:
    """Return an authenticated httpx client, creating/refreshing as needed."""
    if _session.client is not None:
        return _session.client
    return await _authenticate()


async def _authenticate() -> httpx.AsyncClient:
    """Perform the Sanctum CSRF + login flow and store the resulting client."""
    if not EMAIL or not PASSWORD:
        raise RuntimeError(
            "Missing credentials. Set DOMAIN_MONITOR_EMAIL and "
            "DOMAIN_MONITOR_PASSWORD environment variables."
        )

    client = httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://domain-monitor.io",
            "Referer": "https://domain-monitor.io/",
        },
    )

    # Step 1: Fetch CSRF cookie (sets laravel_session + XSRF-TOKEN cookies)
    csrf_response = await client.get(CSRF_URL)
    csrf_response.raise_for_status()

    # Step 2: Extract XSRF-TOKEN from cookies for the X-XSRF-TOKEN header
    xsrf_token = client.cookies.get("XSRF-TOKEN")
    if xsrf_token:
        # URL-decode the token value
        import urllib.parse
        xsrf_token = urllib.parse.unquote(xsrf_token)
        client.headers.update({"X-XSRF-TOKEN": xsrf_token})

    # Step 3: POST login credentials
    login_response = await client.post(
        LOGIN_URL,
        json={"email": EMAIL, "password": PASSWORD},
    )

    if login_response.status_code == 422:
        raise RuntimeError("Login failed: invalid email or password.")
    if login_response.status_code not in (200, 204):
        raise RuntimeError(
            f"Login failed with status {login_response.status_code}: "
            f"{login_response.text[:200]}"
        )

    # Step 4: Fetch account to get user_id for domain queries
    account_response = await client.get(
        f"{API_BASE}/account",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    account_response.raise_for_status()
    account_data = account_response.json()
    _session.user_id = account_data.get("id")

    _session.client = client
    return client


async def _api_get(path: str, params: Optional[dict] = None) -> dict:
    """Make an authenticated GET request, retrying once on 401."""
    client = await _get_client()
    response = await client.get(f"{API_BASE}{path}", params=params)

    if response.status_code == 401:
        # Session expired — re-authenticate and retry
        _session.client = None
        _session.user_id = None
        client = await _authenticate()
        response = await client.get(f"{API_BASE}{path}", params=params)

    response.raise_for_status()
    return response.json()


def _handle_error(e: Exception) -> str:
    """Format exceptions into clear, actionable error messages."""
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 401:
            return "Error: Authentication failed. Check your DOMAIN_MONITOR_EMAIL and DOMAIN_MONITOR_PASSWORD."
        if e.response.status_code == 429:
            return "Error: Rate limit exceeded (200 req/session). Please wait and try again."
        if e.response.status_code == 404:
            return "Error: Resource not found. The domain or resource may not exist in your account."
        return f"Error: API returned status {e.response.status_code}."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. domain-monitor.io may be slow — try again."
    if isinstance(e, RuntimeError):
        return f"Error: {e}"
    return f"Error: Unexpected error — {type(e).__name__}: {e}"


def _days_until(expires_on: str) -> Optional[int]:
    """Return days until expiry from a YYYY-MM-DD string. Negative = expired."""
    try:
        expiry = date.fromisoformat(expires_on)
        return (expiry - date.today()).days
    except (ValueError, TypeError):
        return None


def _expiry_emoji(days: Optional[int]) -> str:
    """Return a visual indicator for urgency."""
    if days is None:
        return "❓"
    if days < 0:
        return "💀"  # expired
    if days <= 14:
        return "🚨"  # critical
    if days <= 30:
        return "⚠️"  # warning
    if days <= 90:
        return "📅"  # heads-up
    return "✅"  # all good


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("domain_monitor_mcp")


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class ListDomainsInput(BaseModel):
    """Input model for listing domains."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    expiring_within_days: Optional[int] = Field(
        default=None,
        description=(
            "If set, only return domains expiring within this many days. "
            "E.g. 30 = show only domains expiring in the next 30 days. "
            "Omit to return all domains."
        ),
        ge=0,
        le=3650,
    )
    sort_by: str = Field(
        default="expires_on",
        description="Sort field: 'expires_on' (default) or 'domain'.",
    )
    sort_order: str = Field(
        default="asc",
        description="Sort order: 'asc' (soonest first, default) or 'desc'.",
    )
    page: int = Field(default=1, description="Page number for pagination.", ge=1)
    per_page: int = Field(
        default=100,
        description="Number of domains per page (max 100).",
        ge=1,
        le=100,
    )


class CheckDomainInput(BaseModel):
    """Input model for checking a specific domain."""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    domain: str = Field(
        ...,
        description="The domain name to check, e.g. 'example.com'.",
        min_length=3,
        max_length=253,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="domain_monitor_list_domains",
    annotations={
        "title": "List Monitored Domains with Expiry Dates",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def domain_monitor_list_domains(params: ListDomainsInput) -> str:
    """List all domains being monitored on domain-monitor.io with their expiration dates.

    Returns domains sorted by expiry date (soonest first by default). Optionally
    filter to only show domains expiring within a given number of days.

    Args:
        params (ListDomainsInput): Validated input parameters containing:
            - expiring_within_days (Optional[int]): Filter to domains expiring within N days (default: all)
            - sort_by (str): Sort field — 'expires_on' or 'domain' (default: 'expires_on')
            - sort_order (str): 'asc' or 'desc' (default: 'asc', soonest first)
            - page (int): Page number (default: 1)
            - per_page (int): Results per page, 1–100 (default: 100)

    Returns:
        str: Markdown-formatted table of domains with expiry dates and urgency indicators.

    Examples:
        - "What domains are expiring soon?" → use expiring_within_days=30
        - "List all my domains" → use defaults (returns all, sorted soonest first)
        - "Show domains expiring in the next 90 days" → expiring_within_days=90
    """
    try:
        data = await _api_get(
            f"/account/{_session.user_id}/domains",
            params={
                "page": params.page,
                "orderBy": f"domains.{params.sort_by}",
                "sortBy": params.sort_order,
                "perPage": params.per_page,
            },
        )

        model = data.get("model", {})
        domains = model.get("data", [])
        total = model.get("total", 0)

        # Client-side filter by days if requested
        if params.expiring_within_days is not None:
            cutoff = date.today() + timedelta(days=params.expiring_within_days)
            domains = [
                d for d in domains
                if d.get("expires_on") and date.fromisoformat(d["expires_on"]) <= cutoff
            ]

        if not domains:
            filter_note = (
                f" expiring within {params.expiring_within_days} days"
                if params.expiring_within_days is not None
                else ""
            )
            return f"No domains found{filter_note}."

        lines = ["# Domain Monitor — Monitored Domains", ""]
        if params.expiring_within_days is not None:
            lines.append(f"*Filtered: expiring within **{params.expiring_within_days} days***\n")
        lines.append(f"Showing {len(domains)} of {total} total domains.\n")
        lines.append(f"| Status | Domain | Expires | Days Left | Registrar |")
        lines.append(f"|--------|--------|---------|-----------|-----------|")

        for d in domains:
            days = _days_until(d.get("expires_on"))
            emoji = _expiry_emoji(days)
            days_str = f"{days}d" if days is not None else "unknown"
            if days is not None and days < 0:
                days_str = f"EXPIRED ({abs(days)}d ago)"
            registrar = d.get("registrar_name") or "—"
            expires = d.get("expires_on") or "unknown"
            lines.append(
                f"| {emoji} | {d['domain']} | {expires} | {days_str} | {registrar} |"
            )

        lines.append("")
        lines.append("**Legend:** 🚨 Critical (≤14d) | ⚠️ Warning (≤30d) | 📅 Heads-up (≤90d) | ✅ OK | 💀 Expired")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="domain_monitor_get_expiring_soon",
    annotations={
        "title": "Get Domains Expiring Soon",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def domain_monitor_get_expiring_soon() -> str:
    """Get a quick summary of domains expiring within the next 30 days.

    This is the fastest way to check "what needs my attention right now?"
    Returns only domains flagged as expiring soon by domain-monitor.io,
    along with account-level alert counts.

    Returns:
        str: Markdown summary of urgent domains and alert counts.

    Examples:
        - "Any domains expiring soon?" → call this tool
        - "What needs renewing?" → call this tool
        - "Domain health check" → call this tool
    """
    try:
        data = await _api_get("/account-dashboard")
        model = data.get("model", {})
        user = model.get("user", {})
        alerts = model.get("alerts", [])

        domains_expiring = user.get("domains_expiring_count", 0)
        domains_total = user.get("domains_count", 0)
        expiring_domains = user.get("domains", [])  # dashboard returns only expiring ones

        lines = ["# 🚨 Domain Monitor — Expiring Soon", ""]
        lines.append(f"**{domains_expiring} of {domains_total} domains** are expiring within your alert window.\n")

        if not expiring_domains:
            lines.append("✅ No domains expiring imminently — you're good!")
        else:
            lines.append("| Status | Domain | Expires | Days Left |")
            lines.append("|--------|--------|---------|-----------|")
            for d in expiring_domains:
                days = _days_until(d.get("expires_on"))
                emoji = _expiry_emoji(days)
                days_str = f"{days}d" if days is not None else "unknown"
                expires = d.get("expires_on") or "unknown"
                lines.append(f"| {emoji} | {d['domain']} | {expires} | {days_str} |")

        if alerts:
            lines.append("\n## Account Alerts")
            for alert in alerts:
                variant_emoji = "🔴" if alert.get("variant") == "danger" else "🔵"
                lines.append(f"- {variant_emoji} **{alert['label']}**: {alert['subtitle']}")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="domain_monitor_check_domain",
    annotations={
        "title": "Check a Specific Domain's Expiry Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def domain_monitor_check_domain(params: CheckDomainInput) -> str:
    """Check the expiry status of a specific domain being monitored.

    Looks up a domain by name across your monitored domains and returns its
    full expiry details. Case-insensitive search.

    Args:
        params (CheckDomainInput): Validated input containing:
            - domain (str): The domain name to check, e.g. 'example.com'

    Returns:
        str: Markdown-formatted domain details, or a message if not found.

    Examples:
        - "When does example.com expire?" → domain="example.com"
        - "Is braatz.io expiring soon?" → domain="braatz.io"
        - "Check woodcomputer.com" → domain="woodcomputer.com"

    Error Handling:
        - Returns "not found" message if domain isn't in your monitored list
        - Returns auth error if credentials are invalid
    """
    try:
        # Fetch all domains (up to 100) sorted by expiry to find the match
        data = await _api_get(
            f"/account/{_session.user_id}/domains",
            params={
                "page": 1,
                "orderBy": "domains.expires_on",
                "sortBy": "asc",
                "perPage": 100,
            },
        )

        model = data.get("model", {})
        domains = model.get("data", [])
        total = model.get("total", 0)

        # Search across all pages if needed
        target = params.domain.lower().strip()
        match = next((d for d in domains if d["domain"].lower() == target), None)

        # If not found on first page and there are more pages, keep searching
        if not match and total > 100:
            last_page = model.get("last_page", 1)
            for page in range(2, last_page + 1):
                page_data = await _api_get(
                    f"/account/{_session.user_id}/domains",
                    params={
                        "page": page,
                        "orderBy": "domains.expires_on",
                        "sortBy": "asc",
                        "perPage": 100,
                    },
                )
                page_domains = page_data.get("model", {}).get("data", [])
                match = next((d for d in page_domains if d["domain"].lower() == target), None)
                if match:
                    break

        if not match:
            return (
                f"Domain **{params.domain}** is not in your monitored domains list.\n"
                f"You are monitoring {total} domains in total.\n"
                f"Use `domain_monitor_list_domains` to see all monitored domains."
            )

        days = _days_until(match.get("expires_on"))
        emoji = _expiry_emoji(days)

        lines = [f"# {emoji} {match['domain']}", ""]

        if days is None:
            lines.append("**Expiry date**: Unknown")
        elif days < 0:
            lines.append(f"**Status**: 💀 **EXPIRED** {abs(days)} days ago!")
        elif days == 0:
            lines.append("**Status**: 🚨 **EXPIRES TODAY!**")
        elif days <= 14:
            lines.append(f"**Status**: 🚨 Critical — expires in **{days} days**")
        elif days <= 30:
            lines.append(f"**Status**: ⚠️ Warning — expires in **{days} days**")
        elif days <= 90:
            lines.append(f"**Status**: 📅 Heads-up — expires in **{days} days**")
        else:
            lines.append(f"**Status**: ✅ Good — expires in {days} days")

        lines.append(f"**Expires on**: {match.get('expires_on', 'unknown')}")
        if match.get("created_on"):
            lines.append(f"**Registered**: {match['created_on']}")
        if match.get("registrar_name"):
            lines.append(f"**Registrar**: {match['registrar_name']}")
        lines.append(f"**Alert period**: {match.get('alert_period', 30)} days before expiry")
        lines.append(f"**Monitor status**: {match.get('status', 'unknown')}")
        if match.get("crawled_at"):
            lines.append(f"**Last checked**: {match['crawled_at']}")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="domain_monitor_get_account_summary",
    annotations={
        "title": "Get Account Summary and Stats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def domain_monitor_get_account_summary() -> str:
    """Get a high-level summary of your domain-monitor.io account.

    Returns total domain count, expiring counts, subscription status,
    and active alerts. Good for a quick "how's everything looking?" check.

    Returns:
        str: Markdown-formatted account overview.

    Examples:
        - "Give me a domain health overview" → call this tool
        - "How many domains am I monitoring?" → call this tool
        - "Is my subscription active?" → call this tool
    """
    try:
        data = await _api_get("/account-dashboard")
        model = data.get("model", {})
        user = model.get("user", {})
        alerts = model.get("alerts", [])

        lines = ["# Domain Monitor — Account Summary", ""]
        lines.append(f"**Account**: {user.get('full_name', 'Unknown')} ({user.get('email', '')})")
        lines.append(f"**Timezone**: {user.get('timezone', 'Unknown')}")
        lines.append(f"**Subscription**: {'✅ Active' if user.get('is_subscribed') else '❌ Inactive'}")
        lines.append("")
        lines.append("## Domain Stats")
        lines.append(f"- **Total domains monitored**: {user.get('domains_count', 0)}")
        lines.append(f"- **Expiring soon**: {user.get('domains_expiring_count', 0)}")
        lines.append(f"- **Disabled**: {user.get('domains_disabled_count', 0)}")
        lines.append("")
        lines.append("## Uptime Monitor Stats")
        lines.append(f"- **Total monitors**: {user.get('monitors_count', 0)}")
        lines.append(f"- **Down**: {user.get('monitors_down_count', 0)}")
        lines.append(f"- **Paused**: {user.get('monitors_paused_count', 0)}")

        if alerts:
            lines.append("\n## Active Alerts")
            for alert in alerts:
                variant_emoji = "🔴" if alert.get("variant") == "danger" else "🔵"
                lines.append(f"- {variant_emoji} **{alert['label']}**: {alert['subtitle']}")
        else:
            lines.append("\n✅ No active alerts.")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
