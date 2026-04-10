# Changelog

All notable changes to domain-monitor-mcp will be documented in this file.

## [1.2.0] - 2026-04-10

### Fixed
- **add_domain now works** — POST payload was missing 3 required boolean fields (`certificate_checks_enabled`, `dns_checks_enabled`, `blacklist_checks_enabled`). The API returned 400 validation errors, which were masked by the generic error handler as "Resource not found."
- **400 error handling** — added a dedicated handler for HTTP 400 responses that extracts validation details from the Laravel error response body (message, errors, metadata fields). Previously, 400s fell through to the generic handler.

### Changed
- **Authentication switched from JWT to Laravel Sanctum** — the domain-monitor.io API moved from JWT Bearer tokens to CSRF cookie + session-based auth. The server now follows the full Sanctum flow: `GET /sanctum/csrf-cookie` → `POST /login` → session cookies + XSRF token rotation.
- **blacklist_checks_enabled defaults to False** — the free/lower-tier plans have a limit of 5 blacklist monitors. Defaulting to True would cause unexpected 400 errors for users near their limit.

### Added
- `__version__` variable for programmatic version checking
- Configurable monitoring toggles in `add_domain`: `certificate_checks_enabled`, `dns_checks_enabled`, `blacklist_checks_enabled`
- OPS.md — full reinstall/troubleshooting guide for future sessions

## [1.1.0] - 2026-04-09

### Added
- `domain_monitor_add_domain` tool — add new domains to monitoring directly from Claude
- Input cleanup for add_domain — strips `http://`, `https://`, `www.` prefixes and trailing slashes
- POST endpoint support (`/api/account/{user_id}/domains`)

### Changed
- Corrected domain list endpoint from `/api/domains` to `/api/account/{user_id}/domains`

## [1.0.0] - 2026-04-08

### Added
- Initial release
- `domain_monitor_list_domains` — paginated domain list with expiry dates
- `domain_monitor_get_expiring_soon` — quick summary of domains expiring within alert window
- `domain_monitor_check_domain` — look up a specific domain's expiry status
- `domain_monitor_get_account_summary` — account stats and alerts overview
- JWT Bearer token authentication with automatic refresh on 401
- Markdown-formatted output with emoji urgency indicators
