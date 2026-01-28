# PowerBlockade

Modern, performant DNS filtering stack built around **PowerDNS Recursor** with full query logging, metrics (Prometheus/Grafana), and optional multi-node redundancy.

Modern dark UI, multi-node support, Docker-first.

## Quick start (single-node)

### Option 1: Use pre-built images (faster, no build)

1. Set your GitHub username or org where images are hosted:

```bash
export POWERBLOCKADE_REPO=powerblockade  # Replace with your GitHub hosting repo
```

2. Generate `.env`:

```bash
./scripts/init-env.sh
```

3. Start the stack with pre-built images:

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

[Read more about pre-built images](docs/USING_PREBUILT_IMAGES.md)

### Option 2: Build locally (for development)

1. Generate `.env`:

```bash
./scripts/init-env.sh
```

2. Start the stack and build images:

```bash
docker compose up -d --build
```

3. Access:

- Admin UI: http://localhost:${ADMIN_PORT:-8080}
- Grafana: http://localhost:3000
- OpenSearch Dashboards: http://localhost:5601
- DNS (dnsdist frontend): UDP/TCP 53 on the host (see compose)
- Recursor API + metrics: http://localhost:8082 (Recursor listens internally for DNS on 5300)

## Access

- Admin UI: http://localhost:${ADMIN_PORT:-8080}
- Grafana: http://localhost:3000
- Prometheus: http://localhost:9091
- Recursor API + metrics: http://localhost:8082
- DNS (dnsdist frontend): UDP/TCP 53 on the host

### First Login

Default credentials (set in `.env`):
- Username: `admin` (or `ADMIN_USERNAME`)
- Password: your `ADMIN_PASSWORD` value

## Repo layout

- `admin-ui/` FastAPI + Jinja2 UI + PostgreSQL config store
- `dnstap-processor/` Go service that ingests dnstap and ships to OpenSearch (and optional GELF)
- `recursor/` Recursor config mounted into the PowerDNS container
- `opensearch/` Index template + ILM policy
- `prometheus/` Prometheus config
- `grafana/` Provisioning and dashboards

## Security notes (prod)

- Set strong values in `.env` (do not commit it).
- Admin password is bootstrapped from `ADMIN_PASSWORD` on first run.

## Optional networking (prod)

- **macvlan “appliance mode” (Linux wired):** run `dnsdist` on a real LAN IP (no port publishing)
  - See: `docs/networking-macvlan.md`

## Optional services

OpenSearch is **internal-only** by default.

- Enable OpenSearch Dashboards:

```bash
docker compose --profile dashboards up -d
```

- Expose OpenSearch on the host (e.g. for remote shipping / HA later):

```bash
docker compose --profile opensearch-public up -d
```
