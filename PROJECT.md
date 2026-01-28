# PowerBlockade

**A modern, performant, user-friendly DNS filtering stack with full query logging, metrics, and multi-node redundancy.**

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Components](#components)
4. [Database Schema](#database-schema)
5. [Admin UI Specification](#admin-ui-specification)
6. [API Endpoints](#api-endpoints)
7. [Secondary Node Management](#secondary-node-management)
8. [GELF Integration](#gelf-integration)
9. [Configuration Reference](#configuration-reference)
10. [Development Phases](#development-phases)
11. [Directory Structure](#directory-structure)

---

## Project Overview

### Goals

- Replace Pi-hole with a modern, faster architecture
- PowerDNS Recursor as the core DNS engine
- Full query logging with built-in search + analytics (PostgreSQL-first)
- Metrics and dashboards (Prometheus + Grafana)
- User-friendly web interface for all management tasks
- Multi-node redundancy with easy secondary deployment
- Support for Pi-hole compatible blocklists
- Split DNS support for internal/AD domains
- Optional GELF output to external Graylog servers
- Configurable log retention

### Non-Goals (For Now)

- DHCP server (future enhancement)
- DoH/DoT termination (future enhancement)
- Per-client blocklist policies (future enhancement)

### Target Environment

- Home networks (primary focus)
- Small business / homelab
- Architecture supports scaling to MSP deployments

---

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PRIMARY NODE                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         User Interfaces                             │    │
│  │   ┌──────────────┐  ┌──────────────┐                                 │    │
│  │   │   Admin UI   │  │   Grafana    │                                 │    │
│  │   │    :8080     │  │    :3000     │                                 │    │
│  │   └──────────────┘  └──────────────┘                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                          Data Stores                                │    │
│  │   ┌────────────┐    ┌────────────┐                                 │    │
│  │   │ PostgreSQL │    │ Prometheus │                                 │    │
│  │   │ (config +  │    │ (metrics)  │                                 │    │
│  │   │  query logs│    └────────────┘                                 │    │
│  │   └────────────┘                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         DNS Layer                                   │    │
│  │                              ▲                                      │    │
│  │                              │ dnstap                               │    │
│  │   ┌──────────────────────────┴──────────────────────────────────┐   │    │
│  │   │                  dnstap-processor                           │   │    │
│  │   │      (enriches, ships to Primary API → Postgres + GELF)     │   │    │
│  │   └──────────────────────────▲──────────────────────────────────┘   │    │
│  │                              │                                      │    │
│  │   ┌──────────────────────────┴──────────────────────────────────┐   │    │
│  │   │                  PowerDNS Recursor                          │   │    │
│  │   │                        :53                                  │   │    │
│  │   │  ┌─────────┐  ┌─────────────┐  ┌──────────────────┐         │   │    │
│  │   │  │  Cache  │  │  RPZ Zones  │  │  Forward Zones   │         │   │    │
│  │   │  │         │  │ (blocklists)│  │   (split DNS)    │         │   │    │
│  │   │  └─────────┘  └─────────────┘  └──────────────────┘         │   │    │
│  │   └─────────────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│                           Config Sync (Syncthing/rsync)                     │
│                                      │                                      │
└──────────────────────────────────────┼──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SECONDARY NODE                                   │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  PowerDNS Recursor :53                                              │   │
│   │  (synced RPZ zones, synced forward-zones)                           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              │ dnstap                                       │
│                              ▼                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  dnstap-processor → ships to Primary API (Postgres) (+ optional GELF)│   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **DNS Query Flow:**
   - Client sends query to Recursor (:53)
   - Recursor checks cache → RPZ zones → forward zones → recursive resolution
   - Response returned to client
   - Query logged via dnstap

2. **Logging Flow (PostgreSQL-first):**
   - Recursor streams all queries via dnstap to dnstap-processor
   - dnstap-processor enriches (reverse DNS, blocklist identification)
   - Enriched logs POSTed to the Primary Admin UI API
   - Primary writes events to PostgreSQL (partitioned) and maintains rollups for analytics
   - Optionally sent to external GELF endpoint (filtered)

3. **Config Flow:**
   - Admin UI writes config to PostgreSQL
   - Blocklist manager downloads lists, converts to RPZ, writes zone files
   - Admin UI triggers Recursor reload via API
   - Config changes synced to secondary nodes

---

## Components

### 1. PowerDNS Recursor

**Purpose:** Core DNS resolution engine

**Key Features Used:**
- Recursive resolution with DNSSEC validation
- Caching (configurable size and TTLs)
- RPZ (Response Policy Zones) for blocklist filtering
- Forward zones for split DNS
- dnstap for query logging
- REST API for control and stats
- Prometheus metrics endpoint

**Configuration Highlights:**
```lua
-- /etc/pdns-recursor/recursor.conf

# Network
local-address=0.0.0.0
local-port=53
allow-from=0.0.0.0/0, ::/0

# Performance
threads=4
pdns-distributes-queries=yes
max-cache-entries=1000000
max-packetcache-entries=500000

# RPZ (blocklists)
lua-config-file=/etc/pdns-recursor/rpz.lua

# Forward zones loaded from file
forward-zones-file=/etc/pdns-recursor/forward-zones.conf

# dnstap
dnstap=yes
dnstap-log-queries=yes
dnstap-log-responses=yes
dnstap-socket=/var/run/dnstap/dnstap.sock

# API
webserver=yes
webserver-address=0.0.0.0
webserver-port=8082
webserver-allow-from=0.0.0.0/0
api-key=${API_KEY}

# Prometheus
prometheus-listen-address=0.0.0.0:9090
```

**RPZ Lua Configuration:**
```lua
-- /etc/pdns-recursor/rpz.lua

rpzFile("/etc/pdns-recursor/rpz/blocklist-combined.rpz", {
    policyName="blocklist-combined",
    defpol=Policy.NXDOMAIN
})

rpzFile("/etc/pdns-recursor/rpz/whitelist.rpz", {
    policyName="whitelist",
    defpol=Policy.PASSTHRU
})
```

---

### 2. Admin UI

**Purpose:** User-friendly web interface for all management tasks

**Technology Stack (current direction):**
- Backend: Python with FastAPI
- Frontend: Server-rendered templates (Jinja2)
- Styling: Tailwind CSS (dark theme)
- Interactivity: htmx (near-real-time updates)
- Charts: Chart.js
- Auth: Basic username/password (session-based)
- Database: PostgreSQL

**Features:**
- Dashboard with real-time stats
- Blocklist management (add, remove, enable, disable, update)
- Whitelist/blacklist manual entries
- Client list with reverse DNS and query links
- Forward zone management (split DNS)
- Node management (secondary node generator, health monitoring)
- GELF output configuration
- Settings (cache, retention, upstream, auth)

---

### 3. dnstap-processor

**Purpose:** Receives dnstap stream, enriches, and ships to outputs

**Technology:** Go (for performance)

**Processing Pipeline:**
1. Receive dnstap message from Unix socket
2. Parse DNS query/response
3. Enrich:
   - Reverse DNS lookup for client IP → hostname
   - Determine if blocked (check response)
   - Identify which blocklist caused block (from RPZ policy name)
   - Add node identifier
4. Format for outputs
5. Ship to Primary API → PostgreSQL (always)
6. Ship to GELF (if enabled and passes filter)

**Configuration (via env or config file):**
```yaml
dnstap:
  socket: /var/run/dnstap/dnstap.sock

enrichment:
  reverse_dns: true
  reverse_dns_timeout: 100ms
  cache_ttl: 3600

primary:
  url: http://admin-ui:8080
  api_key: <node key>
  bulk_size: 500
  flush_interval: 5s

gelf:
  enabled: false
  endpoint: udp://graylog.example.com:12201
  transport: udp  # udp, tcp, tcp+tls
  filter_mode: blocked_only  # all, blocked_only, specific_lists
  blocklist_filter: []  # list names when filter_mode=specific_lists
  rate_limit: 0  # 0 = unlimited

node:
  name: primary
```

---

### 4. OpenSearch

**Status:** Not part of the current MVP plan.

OpenSearch was an early suggestion for query log storage/search and dashboards. The current plan is **PostgreSQL-first** for configuration and query logs/analytics (lighter-weight for home/rPi deployments). OpenSearch may become an optional advanced backend later.

**Optional later:** Add an OpenSearch backend for advanced free-text search and dashboards. This is intentionally deferred until real users request it.

---

### 5. PostgreSQL

**Purpose:** Configuration storage for Admin UI

**Version:** 15+

---

### 6. Prometheus

**Purpose:** Metrics collection

**Scrape Targets:**
- PowerDNS Recursor (:9090/metrics)
- Admin UI (/metrics)
- Node Exporter (optional)

---

### 7. Grafana

**Purpose:** Metrics visualization and dashboards

**Provisioned Dashboards:**
- DNS Overview (QPS, latency, cache hit rate)
- Blocking Stats (blocked queries, top blocked, by list)
- Client Activity (top clients, query patterns)
- Node Health (multi-node status, sync status)

**Data Sources:**
- Prometheus (metrics)

---

### 8. Advanced Search (Optional later)

The MVP includes built-in query log search and analytics backed by PostgreSQL.

Optional later integrations may include OpenSearch Dashboards and advanced search backends.

---

## Database Schema

```sql
-- ============================================
-- PowerBlockade PostgreSQL Schema
-- ============================================

-- Authentication
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

-- Blocklists
CREATE TABLE blocklists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    format VARCHAR(50) NOT NULL,  -- 'hosts', 'domains', 'adblock', 'rpz'
    enabled BOOLEAN DEFAULT true,
    update_frequency_hours INT DEFAULT 24,
    last_updated TIMESTAMP,
    last_update_status VARCHAR(20),  -- 'success', 'failed'
    last_error TEXT,
    entry_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(url)
);

-- Preset blocklists (shipped with app, user enables)
CREATE TABLE blocklist_presets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url TEXT NOT NULL,
    format VARCHAR(50) NOT NULL,
    description TEXT,
    category VARCHAR(100),  -- 'ads', 'tracking', 'malware', 'adult', 'social'
    recommended BOOLEAN DEFAULT false
);

-- Manual whitelist/blacklist entries
CREATE TABLE manual_entries (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    entry_type VARCHAR(10) NOT NULL,  -- 'allow', 'block'
    comment TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100),
    UNIQUE(domain)
);

-- Forward zones (split DNS)
CREATE TABLE forward_zones (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    servers TEXT NOT NULL,  -- comma-separated IPs
    description TEXT,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(domain)
);

-- Secondary nodes
CREATE TABLE nodes (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    api_key VARCHAR(64) NOT NULL UNIQUE,
    ip_address VARCHAR(45),
    last_seen TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'active', 'offline', 'error'
    last_error TEXT,
    version VARCHAR(20),
    config_version INT DEFAULT 0,
    queries_total BIGINT DEFAULT 0,
    queries_blocked BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- GELF output configuration
CREATE TABLE gelf_config (
    id SERIAL PRIMARY KEY,
    enabled BOOLEAN DEFAULT false,
    endpoint TEXT,
    transport VARCHAR(10) DEFAULT 'udp',  -- 'udp', 'tcp', 'tcp+tls'
    tls_verify BOOLEAN DEFAULT true,
    tls_ca_cert TEXT,
    tls_client_cert TEXT,
    tls_client_key TEXT,
    filter_mode VARCHAR(20) DEFAULT 'blocked_only',  -- 'all', 'blocked_only', 'specific_lists'
    rate_limit_per_sec INT DEFAULT 0,  -- 0 = unlimited
    updated_at TIMESTAMP DEFAULT NOW()
);

-- GELF blocklist filters (which lists trigger GELF output)
CREATE TABLE gelf_blocklist_filters (
    id SERIAL PRIMARY KEY,
    gelf_config_id INT REFERENCES gelf_config(id) ON DELETE CASCADE,
    blocklist_id INT REFERENCES blocklists(id) ON DELETE CASCADE,
    UNIQUE(gelf_config_id, blocklist_id)
);

-- Application settings
CREATE TABLE settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    value_type VARCHAR(20) DEFAULT 'string',  -- 'string', 'int', 'bool', 'json'
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Config version tracking (for node sync)
CREATE TABLE config_versions (
    id SERIAL PRIMARY KEY,
    component VARCHAR(50) NOT NULL UNIQUE,  -- 'rpz', 'forwardzones', 'settings'
    version INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Audit log (optional, for tracking changes)
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    user_id INT REFERENCES users(id),
    action VARCHAR(50) NOT NULL,  -- 'create', 'update', 'delete'
    entity_type VARCHAR(50) NOT NULL,  -- 'blocklist', 'manual_entry', 'forward_zone', etc.
    entity_id INT,
    details JSONB
);

-- ============================================
-- Default Data
-- ============================================

-- Default admin user (password: admin - MUST be changed)
INSERT INTO users (username, password_hash) VALUES 
('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.VTtYQ3');

-- Default settings
INSERT INTO settings (key, value, value_type, description) VALUES
('cache_max_entries', '1000000', 'int', 'Maximum cache entries in Recursor'),
('cache_max_ttl', '86400', 'int', 'Maximum TTL for cached entries (seconds)'),
('log_retention_days', '30', 'int', 'Days to retain query logs in PostgreSQL'),
('upstream_servers', '8.8.8.8,8.8.4.4', 'string', 'Upstream DNS servers (if not recursive)'),
('dnssec_validation', 'true', 'bool', 'Enable DNSSEC validation'),
('site_title', 'PowerBlockade', 'string', 'Site title shown in UI');

-- Default config versions
INSERT INTO config_versions (component, version) VALUES
('rpz', 1),
('forwardzones', 1),
('settings', 1);

-- Preset blocklists (popular lists)
INSERT INTO blocklist_presets (name, url, format, description, category, recommended) VALUES
('StevenBlack Unified', 'https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts', 'hosts', 'Unified hosts file with base adware + malware', 'ads', true),
('StevenBlack Unified + Fakenews', 'https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/fakenews/hosts', 'hosts', 'Unified hosts + fakenews extensions', 'ads', false),
('StevenBlack Unified + Gambling', 'https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/gambling/hosts', 'hosts', 'Unified hosts + gambling extensions', 'ads', false),
('OISD Basic', 'https://abp.oisd.nl/basic/', 'adblock', 'OISD basic blocklist', 'ads', true),
('OISD Full', 'https://abp.oisd.nl/', 'adblock', 'OISD full blocklist (aggressive)', 'ads', false),
('AdGuard DNS Filter', 'https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt', 'adblock', 'AdGuard DNS filter', 'ads', false),
('EasyList', 'https://easylist.to/easylist/easylist.txt', 'adblock', 'EasyList ad blocking', 'ads', false),
('EasyPrivacy', 'https://easylist.to/easylist/easyprivacy.txt', 'adblock', 'EasyPrivacy tracking protection', 'tracking', true),
('Dan Pollock hosts', 'https://someonewhocares.org/hosts/hosts', 'hosts', 'Dan Pollock maintained hosts file', 'ads', false),
('URLhaus Malware', 'https://urlhaus.abuse.ch/downloads/hostfile/', 'hosts', 'URLhaus malware blocklist', 'malware', true),
('Phishing Army', 'https://phishing.army/download/phishing_army_blocklist.txt', 'domains', 'Phishing domain blocklist', 'malware', true),
('NoTracking', 'https://raw.githubusercontent.com/notracking/hosts-blocklists/master/hostnames.txt', 'domains', 'NoTracking blocklist', 'tracking', false);
```

---

## Admin UI Specification

### Authentication

- Session-based authentication
- bcrypt password hashing
- Session timeout: 24 hours (configurable)
- Single user initially (admin), multi-user possible later

### Pages

#### 1. Login (`/login`)
- Username/password form
- Redirect to dashboard on success

#### 2. Dashboard (`/`)
- **Stats Cards:**
  - Total queries (24h)
  - Blocked queries (24h)
  - Block percentage
  - Cache hit rate
  - Active clients
  - Node status (if secondaries configured)
  
- **Charts:**
  - Queries over time (line chart, 24h)
  - Blocked vs allowed (pie chart)
  - Top 10 blocked domains (bar chart)
  - Top 10 clients (bar chart)

- **Quick Actions:**
  - Flush cache
  - Update blocklists now
  - Disable blocking (temporary bypass)

#### 3. Blocklists (`/blocklists`)
- **List View:**
  - Table: Name, URL, Format, Entries, Last Updated, Status, Enabled toggle
  - Actions: Edit, Delete, Update Now
  
- **Add Blocklist:**
  - Form: Name, URL, Format (dropdown), Update Frequency
  - Test URL button (validates and shows entry count preview)
  
- **Preset Blocklists:**
  - Tabbed or sidebar section
  - Shows available presets with descriptions
  - One-click enable

#### 4. Whitelist / Blacklist (`/entries`)
- **Tabs:** Whitelist | Blacklist
- **Table:** Domain, Comment, Added Date, Actions
- **Add Entry:** Domain input, Comment, Type (allow/block)
- **Bulk Import:** Textarea or file upload for multiple domains

#### 5. Clients (`/clients`)
- **Table:** IP Address, Hostname, Total Queries, Blocked Queries, Last Seen
- **Click row:** Opens built-in query history for that client
- **Hostname Resolution:**
  - Automatic reverse DNS
  - Manual override option (store in DB)

#### 6. Forward Zones (`/forwardzones`)
- **Table:** Domain, Servers, Description, Enabled toggle
- **Add Zone:**
  - Domain (e.g., `ad.contoso.com`)
  - DNS Servers (comma-separated IPs)
  - Description
- **Common Presets:** Button to add common patterns (e.g., `*.local` → router)

#### 7. Nodes (`/nodes`)
- **Primary Node Info:**
  - Status, uptime, version
  - Config version
  
- **Secondary Nodes Table:**
  - Name, IP, Status, Last Seen, Config Version, Queries, Actions
  
- **Add Secondary Node:**
  - Opens modal/wizard
  - Enter: Node name, Expected IP (optional)
  - Generates: API key, docker-compose.yaml, .env file, README
  - Download as ZIP or display with copy buttons
  
- **Node Details:**
  - Health history
  - Sync status
  - Remove node option

#### 8. GELF Output (`/gelf`)
- **Enable/Disable Toggle**
- **Configuration Form:**
  - Endpoint URL
  - Transport: UDP / TCP / TCP+TLS
  - TLS settings (if TCP+TLS): CA cert, client cert, client key
  - Filter Mode: All / Blocked Only / Specific Lists
  - Blocklist selection (multi-select, shown if Specific Lists)
  - Rate Limit (events/sec, 0 for unlimited)
- **Test Connection Button**
- **Status:** Last sent, errors

#### 9. Query Log (`/logs`)
- **Built-in search** (MVP):
  - Search by domain, client IP, time range
  - Filters: blocked-only, failures-only
  - Show results in table

*(Optional later: advanced search/dashboards integrations.)*

#### 10. Settings (`/settings`)
- **DNS Settings:**
  - Cache size
  - Max TTL
  - DNSSEC validation toggle
  - Upstream servers (if using forwarding mode)
  
- **Logging:**
  - Retention period (days)
  - Log level
  
- **Authentication:**
  - Change password
  - Session timeout
  
- **System:**
  - Site title
  - Timezone
  - Restart Recursor button
  - Export config (backup)
  - Import config (restore)

---

## API Endpoints

### Authentication

```
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

### Dashboard

```
GET /api/dashboard/stats
GET /api/dashboard/charts/queries?period=24h
GET /api/dashboard/charts/blocked?period=24h
GET /api/dashboard/charts/top-blocked?limit=10
GET /api/dashboard/charts/top-clients?limit=10
```

### Blocklists

```
GET    /api/blocklists
POST   /api/blocklists
GET    /api/blocklists/{id}
PUT    /api/blocklists/{id}
DELETE /api/blocklists/{id}
POST   /api/blocklists/{id}/update      # Trigger update now
GET    /api/blocklists/presets
POST   /api/blocklists/presets/{id}/enable
POST   /api/blocklists/test-url         # Validate URL, return entry count
```

### Manual Entries (Whitelist/Blacklist)

```
GET    /api/entries?type=allow|block
POST   /api/entries
DELETE /api/entries/{id}
POST   /api/entries/bulk                 # Bulk import
```

### Clients

```
GET /api/clients
GET /api/clients/{ip}
PUT /api/clients/{ip}/name              # Manual hostname override
```

### Forward Zones

```
GET    /api/forwardzones
POST   /api/forwardzones
PUT    /api/forwardzones/{id}
DELETE /api/forwardzones/{id}
```

### Nodes

```
GET    /api/nodes
POST   /api/nodes                        # Register new node
GET    /api/nodes/{id}
DELETE /api/nodes/{id}
POST   /api/nodes/generate               # Generate secondary package
GET    /api/nodes/{id}/health
```

### Node Sync (Called by secondary nodes)

```
POST   /api/node-sync/register           # Secondary registers with primary
GET    /api/node-sync/config             # Get current config (RPZ files, forward zones)
POST   /api/node-sync/heartbeat          # Health check from secondary
GET    /api/node-sync/rpz/{filename}     # Download RPZ zone file
```

### GELF Configuration

```
GET  /api/gelf
PUT  /api/gelf
POST /api/gelf/test                      # Test connection
```

### Settings

```
GET  /api/settings
PUT  /api/settings
POST /api/settings/flush-cache
POST /api/settings/reload-config
POST /api/settings/restart-recursor
GET  /api/settings/export
POST /api/settings/import
```

### System

```
GET /api/system/health
GET /api/system/version
```

---

## Secondary Node Management

### Node Package Contents

When admin generates a secondary node package:

**docker-compose.yaml:**
```yaml
version: '3.8'

services:
  recursor:
    image: powerdns/pdns-recursor-48:latest
    container_name: powerblockade-recursor
    restart: unless-stopped
    ports:
      - "53:53/udp"
      - "53:53/tcp"
    volumes:
      - ./config/recursor.conf:/etc/pdns-recursor/recursor.conf:ro
      - ./config/rpz.lua:/etc/pdns-recursor/rpz.lua:ro
      - ./config/forward-zones.conf:/etc/pdns-recursor/forward-zones.conf:ro
      - ./rpz:/etc/pdns-recursor/rpz:ro
      - dnstap-socket:/var/run/dnstap
    networks:
      - powerblockade

  dnstap-processor:
    image: powerblockade/dnstap-processor:latest
    container_name: powerblockade-dnstap
    restart: unless-stopped
    environment:
      - NODE_NAME=${NODE_NAME}
      - PRIMARY_URL=${PRIMARY_URL}
      - PRIMARY_API_KEY=${PRIMARY_API_KEY}
      - OPENSEARCH_URL=${OPENSEARCH_URL}
      - GELF_ENABLED=${GELF_ENABLED:-false}
      - GELF_ENDPOINT=${GELF_ENDPOINT:-}
    volumes:
      - dnstap-socket:/var/run/dnstap
    depends_on:
      - recursor
    networks:
      - powerblockade

  sync-agent:
    image: powerblockade/sync-agent:latest
    container_name: powerblockade-sync
    restart: unless-stopped
    environment:
      - NODE_NAME=${NODE_NAME}
      - PRIMARY_URL=${PRIMARY_URL}
      - PRIMARY_API_KEY=${PRIMARY_API_KEY}
    volumes:
      - ./config:/config
      - ./rpz:/rpz
    networks:
      - powerblockade

volumes:
  dnstap-socket:

networks:
  powerblockade:
```

**.env:**
```bash
NODE_NAME=secondary-1
PRIMARY_URL=https://192.168.1.10:8080
PRIMARY_API_KEY=generated-64-char-key
OPENSEARCH_URL=https://192.168.1.10:9200

# Optional: GELF output (inherits from primary or override)
GELF_ENABLED=false
GELF_ENDPOINT=
```

**README.md:**
```markdown
# PowerBlockade Secondary Node: secondary-1

## Quick Start

1. Ensure Docker and Docker Compose are installed
2. Copy this folder to your secondary server
3. Review and update `.env` if needed
4. Run: `docker-compose up -d`

## Configuration

The sync-agent will automatically:
- Register with the primary node
- Download current blocklist/RPZ files
- Download forward zone configuration
- Keep configuration in sync with primary

DNS queries will be logged to the primary's PostgreSQL instance.

## Verification

Check status: `docker-compose ps`
View logs: `docker-compose logs -f`

The node should appear as "active" in the primary's Nodes page within 60 seconds.
```

### Sync Agent Behavior

1. **On Startup:**
   - POST to `/api/node-sync/register` with API key and node info
   - GET `/api/node-sync/config` to get current config version
   - Download all RPZ files
   - Generate recursor.conf and forward-zones.conf
   - Signal Recursor to reload

2. **Periodic (every 60s):**
   - POST `/api/node-sync/heartbeat` with stats
   - Check config version
   - If changed, download updated config and reload

3. **On Config Change (webhook, optional):**
   - Primary notifies secondary of change
   - Secondary pulls updated config immediately

---

## GELF Integration

### Message Format

```json
{
  "version": "1.1",
  "host": "powerblockade-primary",
  "short_message": "DNS query blocked: ads.doubleclick.net",
  "full_message": "Client 192.168.1.50 (johns-laptop.local) queried ads.doubleclick.net (A) - BLOCKED by StevenBlack-unified",
  "timestamp": 1706112600.123,
  "level": 6,
  "_client_ip": "192.168.1.50",
  "_client_name": "johns-laptop.local",
  "_query_name": "ads.doubleclick.net",
  "_query_type": "A",
  "_response_code": "NXDOMAIN",
  "_blocked": true,
  "_blocklist_name": "StevenBlack-unified",
  "_response_time_ms": 2,
  "_node": "powerblockade-primary",
  "_powerblockade_version": "1.0.0"
}
```

### Filter Modes

1. **All:** Every query shipped to GELF
2. **Blocked Only:** Only queries that were blocked (most common for alerting)
3. **Specific Lists:** Only queries blocked by selected blocklists (e.g., only malware list hits)

---

## Configuration Reference

### Environment Variables (Primary)

```bash
# Database
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=powerblockade
POSTGRES_USER=powerblockade
POSTGRES_PASSWORD=changeme

# Query logs (MVP)
# PostgreSQL is used for configuration + query logs.

# (Optional later)
# OpenSearch
# OPENSEARCH_URL=http://opensearch:9200

# Recursor API
RECURSOR_API_URL=http://recursor:8082
RECURSOR_API_KEY=changeme

# Admin UI
ADMIN_SECRET_KEY=changeme-random-string
ADMIN_PORT=8080

# Optional
LOG_LEVEL=INFO
TIMEZONE=America/Los_Angeles
```

### Environment Variables (Secondary)

```bash
NODE_NAME=secondary-1
PRIMARY_URL=https://primary-ip:8080
PRIMARY_API_KEY=generated-key

# Optional GELF override
GELF_ENABLED=false
GELF_ENDPOINT=
```

---

## Development Phases

### Phase 1: Core DNS + Postgres Logging (Week 1-2)

**Deliverables:**
- [ ] docker-compose.yml with Recursor, PostgreSQL (config + query logs)
- [ ] Recursor configuration (caching, DNSSEC, API, metrics, dnstap)
- [ ] Basic RPZ zone loading (manual test file)
- [ ] Forward zones working
- [ ] Prometheus scraping Recursor metrics
- [ ] dnstap-processor skeleton (receives, ships to primary API)
- [ ] Postgres query log schema + retention

**Success Criteria:**
- DNS resolution works
- Blocked domain returns NXDOMAIN
- Forward zones route correctly
- Metrics visible in Prometheus

---

### Phase 2: Logging + Analytics UI (Week 3)

**Deliverables:**
- [ ] dnstap-processor enrichment (reverse DNS, blocklist ID)
- [ ] Postgres ingest working (primary + secondary)
- [ ] GELF output implementation (disabled by default)
- [ ] Built-in Admin UI query log + analytics views

**Success Criteria:**
- All queries visible in PostgreSQL
- Can search by domain, client, time
- GELF output works when enabled

---

### Phase 3: Admin UI - MVP (Week 4-6)

**Deliverables:**
- [ ] FastAPI project structure
- [ ] PostgreSQL schema and migrations
- [ ] Authentication (login/logout/session)
- [ ] Dashboard page with stats
- [ ] Blocklists CRUD
- [ ] Blocklist processor (download, convert, generate RPZ)
- [ ] Whitelist/blacklist entries
- [ ] Recursor reload integration
- [ ] Basic Grafana dashboards

**Success Criteria:**
- Can log in
- Can add/remove blocklists via UI
- Blocklists update and Recursor reloads
- Dashboard shows real stats

---

### Phase 4: Admin UI - Complete (Week 7-8)

**Deliverables:**
- [ ] Clients page
- [ ] Forward zones management
- [ ] Settings page
- [ ] Query log page (link or embed)
- [ ] Preset blocklists
- [ ] UI polish and mobile responsiveness
- [ ] Cache flush and manual controls

**Success Criteria:**
- Full feature parity with spec
- Responsive design works on tablet/phone
- All settings configurable via UI

---

### Phase 5: Multi-Node & GELF (Week 9-10)

**Deliverables:**
- [ ] Nodes management page
- [ ] Secondary node package generator
- [ ] Sync agent container
- [ ] Node registration and heartbeat APIs
- [ ] Config sync mechanism
- [ ] GELF configuration page
- [ ] GELF filter modes
- [ ] Node health monitoring

**Success Criteria:**
- Can generate and deploy secondary node
- Secondary syncs config automatically
- Secondary logs appear in primary PostgreSQL
- GELF output works with filters

---

### Phase 6: Documentation & Polish (Week 11)

**Deliverables:**
- [ ] Installation guide
- [ ] Configuration reference
- [ ] User guide
- [ ] API documentation
- [ ] Troubleshooting guide
- [ ] GitHub repo setup (README, LICENSE, CONTRIBUTING)

**Success Criteria:**
- New user can deploy from docs
- All features documented

---

## Directory Structure

```
powerblockade/
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── README.md
├── LICENSE
├── CONTRIBUTING.md
│
├── admin-ui/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py
│   │   │   ├── blocklist.py
│   │   │   ├── entry.py
│   │   │   ├── forward_zone.py
│   │   │   ├── node.py
│   │   │   ├── gelf_config.py
│   │   │   └── settings.py
│   │   ├── schemas/
│   │   │   └── ...
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── dashboard.py
│   │   │   ├── blocklists.py
│   │   │   ├── entries.py
│   │   │   ├── clients.py
│   │   │   ├── forwardzones.py
│   │   │   ├── nodes.py
│   │   │   ├── gelf.py
│   │   │   └── settings.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── blocklist_manager.py
│   │   │   ├── rpz_generator.py
│   │   │   ├── recursor_api.py
│   │   │   ├── client_resolver.py
│   │   │   ├── node_generator.py
│   │   │   ├── metrics.py
│   │   │   └── opensearch.py
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── login.html
│   │   │   ├── dashboard.html
│   │   │   ├── blocklists.html
│   │   │   ├── entries.html
│   │   │   ├── clients.html
│   │   │   ├── forwardzones.html
│   │   │   ├── nodes.html
│   │   │   ├── gelf.html
│   │   │   └── settings.html
│   │   └── static/
│   │       ├── css/
│   │       ├── js/
│   │       └── img/
│   └── tests/
│       └── ...
│
├── dnstap-processor/
│   ├── Dockerfile
│   ├── go.mod
│   ├── go.sum
│   ├── main.go
│   ├── config/
│   │   └── config.go
│   ├── dnstap/
│   │   └── receiver.go
│   ├── enricher/
│   │   └── enricher.go
│   ├── outputs/
│   │   ├── opensearch.go
│   │   └── gelf.go
│   └── models/
│       └── event.go
│
├── sync-agent/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── agent.py
│
├── recursor/
│   ├── Dockerfile
│   ├── recursor.conf
│   ├── rpz.lua
│   └── forward-zones.conf.template
│
├── opensearch/
│   ├── opensearch.yml
│   ├── index-template.json
│   └── ilm-policy.json
│
├── grafana/
│   ├── provisioning/
│   │   ├── dashboards/
│   │   │   └── dashboards.yml
│   │   └── datasources/
│   │       └── datasources.yml
│   └── dashboards/
│       ├── dns-overview.json
│       ├── blocking-stats.json
│       └── node-health.json
│
├── prometheus/
│   └── prometheus.yml
│
└── docs/
    ├── installation.md
    ├── configuration.md
    ├── user-guide.md
    ├── api-reference.md
    ├── secondary-nodes.md
    ├── gelf-integration.md
    └── troubleshooting.md
```

---

## License

MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
