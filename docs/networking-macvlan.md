# macvlan “appliance mode” (optional, Linux wired)

This project’s default deployment uses a normal Docker bridge network and publishes DNS on the host (`:53/tcp` + `:53/udp`).

If you prefer a more appliance-like setup on **Linux with a wired interface**, you can run `dnsdist` on a **real LAN IP** using Docker’s `macvlan` driver.

This is **not required** and is best treated as an advanced option.

## What you get

- `dnsdist` appears on your LAN as its own “device” (unique MAC + IP).
- LAN clients use `dnsdist` directly (no `ports:` publishing needed).
- `recursor`, `admin-ui`, `postgres`, etc. stay on the internal compose network.

## When you should NOT use macvlan

- Your host is on **Wi‑Fi** (`wlan0`) (macvlan is often problematic on Wi‑Fi). Prefer wired, or consider `ipvlan` L2.
- You don’t want the operational complexity (host ↔ macvlan caveat below).

## Key caveat: host ↔ macvlan containers

By default, Linux prevents the **host** from talking directly to containers on a macvlan network. That means your host may not be able to reach the `dnsdist` LAN IP.

This is expected. Workarounds:
- Don’t use `dnsdist` as the host’s resolver (only LAN clients).
- Add a small host “shim” interface (instructions below).

## Recommended approach: compose override file

Keep the main `docker-compose.yml` unchanged and create an environment-specific override file.

Create `docker-compose.macvlan.yml` alongside `docker-compose.yml`:

```yaml
services:
  dnsdist:
    # With macvlan, LAN clients reach dnsdist at its LAN IP.
    # Don’t publish host ports for DNS.
    ports: []

    # Attach to BOTH networks:
    # - lan (macvlan) for the LAN IP
    # - default (bridge) so dnsdist can reach recursor at 172.30.0.10:5300
    networks:
      lan:
        ipv4_address: 192.168.1.53
      default: {}

networks:
  lan:
    driver: macvlan
    driver_opts:
      parent: eth0
    ipam:
      config:
        - subnet: 192.168.1.0/24
          gateway: 192.168.1.1
```

Then run:

```bash
docker compose -f docker-compose.yml -f docker-compose.macvlan.yml up -d
```

### Choosing values

- `parent`: your wired interface (`eth0`, `eno1`, `ens18`, etc.)
- `subnet`/`gateway`: your LAN
- `ipv4_address`: a **static** IP you will configure as DNS in DHCP/router (recommended)

## Host shim (optional)

If you want the **host** to be able to reach the `dnsdist` LAN IP, create a macvlan shim on the host.

Example (adjust interface + IPs):

```bash
# Create a macvlan interface on the host
sudo ip link add macvlan0 link eth0 type macvlan mode bridge

# Assign an unused LAN IP to the host-side shim
sudo ip addr add 192.168.1.254/32 dev macvlan0

sudo ip link set macvlan0 up

# Route only the dnsdist container IP via the shim
sudo ip route add 192.168.1.53/32 dev macvlan0
```

To make this persistent, use your distro’s network management (systemd-networkd / NetworkManager) to recreate these at boot.

## Notes / gotchas

- Your switch/router must allow an extra MAC address for the container.
- Make sure nothing else is binding `:53` on the LAN IP (it’s a distinct IP, so typically fine).
- If you must run on Wi‑Fi, prefer `ipvlan` L2 over `macvlan`.
