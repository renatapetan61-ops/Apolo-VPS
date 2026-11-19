# APOLO VPS

Greek-gold cloud infrastructure control plane. Independent implementation inspired by VPS hosting portals.

## Current status

This repository starts the **control-plane foundation**:
- Responsive Greek-gold dashboard (React + Vite).
- VPS inventory and create-instance UI.
- FastAPI control-plane API contract.
- Explicit provider readiness checks; no fabricated IPs, credentials, or VM states.

**Important:** the application does not create a virtual machine merely by generating credentials. Real instances require a reachable Linux hypervisor with KVM/QEMU, libvirt, configured storage, bridged networking, routable IPv4/IPv6, and approved OS cloud images. Until a provider is configured, create requests return HTTP 503 rather than pretending a VPS exists.

## Stack

- Frontend: React, Vite, TypeScript-ready JavaScript, Lucide icons.
- API: Python 3.12+, FastAPI, Pydantic.
- Planned hypervisor adapter: KVM/QEMU + libvirt.
- Planned guest initialization: cloud-init.
- Planned persistence: PostgreSQL.
- Planned edge: Nginx + HTTPS.

## Development

### Frontend
```bash
npm install
npm run dev
```

Set `VITE_API_BASE_URL` to the API URL (defaults to `http://localhost:8000`).

### API
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn apolo_vps.main:app --reload --host 0.0.0.0 --port 8000
```

## Real provisioning prerequisites

1. Dedicated Linux host with hardware virtualization enabled.
2. KVM/QEMU and libvirt daemon installed and healthy.
3. Dedicated storage pool and verified OS image catalogue.
4. Bridge/network configuration with provider-authorized public IPv4 and IPv6 allocation.
5. Restricted provisioning service identity; never expose the libvirt socket to the public API.
6. Secret management, audit logging, quotas, and abuse controls.

Do not expose libvirt, SSH, or hypervisor management ports to the public internet. Use a private control channel between API and host agent.

## VPS record fields

- Computer name
- Username
- Password (write-only at creation; encrypted secret storage, reveal-once policy)
- IPv4
- IPv6
- Location
- Operating system
- Lifecycle status and timestamps

## Security principles

- Never commit credentials, API tokens, private keys, or real customer secrets.
- Passwords must be generated server-side using a cryptographically secure RNG.
- Store secrets encrypted with a managed key; redact them from logs.
- Do not show a VM as running until the hypervisor confirms its state.
- IP addresses must come from the configured network allocator, never random placeholders.

## License

Project licensing is to be selected by the repository owner before public distribution.
