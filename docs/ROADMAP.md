# PowerBlockade Roadmap

**Current Version:** 0.4.0  
**Updated:** 2026-02-03

---

## v0.5.0 - Logging & Group-Based Policies

### GELF Output
Ship DNS query logs to Graylog/OpenSearch via GELF protocol for centralized log aggregation.

**Scope:**
- Add GELF output option to dnstap-processor
- Configuration via environment variables
- Support TCP and UDP GELF endpoints

### Group-Based RPZ
Apply different blocklists to different client groups (e.g., kids vs adults, IoT vs workstations).

**Scope:**
- Extend ClientGroup model with blocklist associations
- Generate per-group RPZ zones
- dnsdist routing based on client IP to appropriate recursor view

### Backup/Restore Config Export
Export full configuration (blocklists, settings, forward zones) as downloadable archive for migration.

**Scope:**
- Export all DB config to JSON/YAML
- Import/restore from archive
- Include RPZ files in export

---

## v0.6.0 - Operations & Security

### Auto-Deploy Secondary Nodes
One-click deployment of secondary nodes from the admin UI.

**Scope:**
- SSH key management in UI
- Remote Docker deployment via SSH
- Progress tracking and logs
- Health verification post-deploy

### Container Minimization
Reduce container image sizes and attack surface.

**Scope:**
- Distroless or scratch-based images where possible
- Multi-stage builds optimization
- Remove unnecessary packages
- Security scan integration in CI

---

## Backlog

Items that may be addressed in future versions:

| Item | Description |
|------|-------------|
| DoH/DoT Support | DNS-over-HTTPS and DNS-over-TLS via dnsdist |
| Mobile Responsive UI | Better tablet/phone experience |
| Lua Policy Tests | Automated tests for recursor/rpz.lua |
| Node Actions | Delete node, force sync, re-download package from UI |

---

## Completed (v0.4.0 and earlier)

<details>
<summary>Click to expand completed items</summary>

### v0.4.0
- Grafana Query Analytics dashboard with all panels working
- Latency Distribution barchart fix
- Postgres datasource env var expansion
- Anonymous Grafana users can query
- Version display in UI footer

### v0.3.x
- CSRF protection
- Session cookie hardening  
- Default credential validation
- Real-time query streaming (WebSocket)
- Client grouping with CIDR auto-assign
- Scheduled blocklist categories
- Query log filtering (type, blocked/allowed)
- Theme toggle (dark/light)
- Backup/restore in web UI
- Prometheus alert presets
- pb CLI upgrade system
- E2E test suite
- Service layer tests
- Human-readable timestamps
- Node status badges and metrics

### v0.2.x
- Multi-node support with sync-agent
- Grafana integration (proxied)
- Prometheus metrics
- Optional Traefik TLS

### v0.1.x
- Core DNS filtering with PowerDNS Recursor
- Blocklist management (hosts, domains, adblock formats)
- Query logging to Postgres
- Admin UI with FastAPI + Jinja2
- Forward zones
- Precache warming

</details>
