# APOLO VPS

Greek-gold cloud infrastructure control plane and KVM provisioning-engine foundation.

## Implemented in this stage

- React/Vite Greek-gold dashboard.
- FastAPI control-plane API.
- Optional secured host-agent service for a Linux KVM/libvirt host.
- Live libvirt hypervisor information and domain inventory.
- VM lifecycle operations: start, graceful shutdown, reboot, force stop and undefine.
- Architecture-aware OS image catalogue for Ubuntu 24.04, Debian 12 and Rocky Linux 9 (x86_64), ARM64 Linux catalog entries, Windows 11/10 x64 and ARM64, Windows 8/7 x64, and the legacy Windows Server 2022 entry. Only verified x86_64 Linux cloud images are enabled by the current provisioner; all ARM64 and Windows entries remain fail-closed until their dedicated boot, driver, unattended-install and access paths are implemented and tested.
- Cryptographically secure password and hostname generation helpers.
- SQLite-backed IPv4/IPv6 allocation helper that requires explicitly configured globally routable CIDRs.
- Tests for credential generation and fail-closed image catalogue.

## Important deployment boundary

GitHub is the source repository and CI platform; it is not a permanent KVM hypervisor. Real VM operations require a dedicated Linux server with hardware virtualization, KVM/QEMU, libvirt, storage, a bridge, public IPv4/IPv6 allocations authorized by the network provider, and verified guest images.

The public control-plane API must not access the libvirt socket directly. Deploy `apolo_vps.agent` on the hypervisor in a private management network. Expose it only through private HTTPS or a VPN. The API authenticates to it using a long random token in the `X-Apolo-Agent-Token` header. VM management endpoints also require a separate `APOLO_CONTROL_TOKEN` Bearer credential. Do not publish the agent port to the public internet.

## Host-agent installation (on the hypervisor)

Install OS packages using the hypervisor distribution's package manager. On Debian/Ubuntu, package names commonly include `qemu-kvm`, `libvirt-daemon-system`, `libvirt-clients`, `python3-libvirt`, and `qemu-utils`. Confirm package names for your release.

Then install the Python agent dependencies and run:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-agent.txt
# The venv must be created with --system-site-packages so it can import OS python3-libvirt.
export APOLO_AGENT_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn apolo_vps.agent:app --host 127.0.0.1 --port 8090
```

The example binds to loopback. For a separate API host, put the agent behind a private VPN/reverse proxy with TLS; do not bind it to a public interface without network controls.

## Control-plane configuration

Configure these environment variables in the API runtime's secret manager:

- `APOLO_PROVISIONER_URL`: private HTTPS URL for the host agent.
- `APOLO_PROVISIONER_TOKEN`: same high-entropy token configured on the agent.
- `APOLO_CORS_ORIGINS`: exact dashboard origins, comma-separated.
- `APOLO_CONTROL_TOKEN`: long random admin-only token. The dashboard sends it as a Bearer token for VM creation and lifecycle actions. Do not reuse the host-agent token.

The health endpoint reports the hypervisor ready only after a successful live agent probe. A configured URL/token alone is not considered readiness.

## Image catalogue

Set each variable to an existing, verified image path on the hypervisor:

- `APOLO_IMAGE_UBUNTU_2404`
- `APOLO_IMAGE_DEBIAN_12`
- `APOLO_IMAGE_ROCKY_9`
- `APOLO_IMAGE_WINDOWS_2022`

Windows 11/10 x64, Windows 11/10 ARM64, Windows 8/7 and Windows Server are cataloged as planned targets, not currently provisionable guests. The current libvirt domain builder hardcodes x86_64/q35 and the host agent only implements Linux cloud-init. Do not mark Windows or ARM64 images enabled until separate architecture-aware domain builders, UEFI/firmware, VirtIO drivers, unattended installation, licensing/activation, networking, remote console/RDP and integration tests are complete. Windows 11 ARM64 installation media is available from Microsoft; use only media and licenses you are authorized to use. Older Windows versions are legacy and require isolated network policies.

## Addressing

The IPAM helper requires:

- `APOLO_IPV4_CIDR`: public IPv4 network delegated to this service.
- `APOLO_IPV6_CIDR`: public IPv6 network delegated to this service.

This helper reserves addresses in SQLite; it does not configure upstream routing, switch ports, bridge interfaces, firewall rules, reverse DNS, or provider anti-spoofing. Those must be configured and tested on the real network before allocating an address to a guest. Never use random addresses or private RFC1918 addresses as public VPS addresses.

## Current safety gate

Linux VPS creation now runs through the host agent: the API reserves an IPv4/IPv6 pair, the agent generates a one-time password, renders cloud-init and static network configuration, creates a QCOW2 overlay, defines and starts the libvirt domain, then returns the password once. Metadata is persisted without plaintext passwords. This requires host, image, gateway, bridge, storage and public IP pool configuration. Windows and ARM64 guests are intentionally disabled in the image catalog until their separate provisioners and real-hypervisor acceptance tests are complete.

## Tests

```bash
cd backend
pip install -e '.[test]'
pytest
```

## Security

- Keep libvirt and agent management ports private.
- Use TLS/VPN between control plane and agent.
- Store secrets only in a secret manager; never commit tokens.
- Passwords must be generated server-side and shown once; do not log or store plaintext.
- Restrict lifecycle actions by tenant ownership and audit every operation before exposing the API to users.
- Do not claim a VM is running unless libvirt confirms its state.


## GitHub Codespaces QEMU development host

The repository includes a Codespaces devcontainer that installs real QEMU system
emulators for x86_64 and AArch64, QEMU utilities, libvirt client/daemon packages,
OVMF firmware and cloud-image tools. On creation it runs
`bash scripts/codespaces-hypervisor-preflight.sh`, which reports whether the
Codespaces instance actually exposes KVM, libvirt system access and TUN/TAP.

This is a **development and compatibility-test environment**, not a promise of
production VPS hosting. Codespaces runs inside a GitHub-managed VM and its
container has limited access to the outer VM host. The devcontainer does not
request privileged mode and does not attempt to change host networking. If
`/dev/kvm` is unavailable, QEMU can use TCG software emulation for controlled
tests; performance may be slow, especially for cross-architecture guests.
Without TUN/TAP and control of public routing, guests cannot be offered as
internet-reachable VPSs with dedicated public IP addresses.

GitHub documents a maximum Codespaces lifetime of 12 hours, even when active.
Therefore Codespaces cannot be treated as an always-on, persistent production
hypervisor. Keep the control-plane source and persistent state in durable
services; use Codespaces for development, builds and short-lived QEMU tests.
Before any production claim, run the preflight in the actual Codespace and
validate guest boot, storage persistence, network reachability and lifecycle
operations.

To start: open this repository on GitHub, choose **Code → Codespaces → Create
codespace on main**, wait for the devcontainer build, then inspect the
`APOLO VPS / GitHub Codespaces QEMU preflight` output in the creation terminal.


## Runtime environment manager (initial implementation)

The control plane now includes a durable SQLite registry for runtime-environment
requests, with resource sizing (vCPU, RAM and disk), provider identity, lifecycle
state, runtime ID, error details and an external persistent-disk URI. New requests
are recorded as `waiting_capacity`; this is intentionally not reported as a
running VPS. The API exposes:

- `POST /api/v1/environments/requests` — authenticated request registration.
- `GET /api/v1/environments` — list durable environment metadata (optionally
  filtered with `?vps_id=...`).
- `POST /api/v1/environments/{environment_id}/transition` — authenticated
  lifecycle transition. An environment cannot be marked running/stopped/recovering
  without a durable external `disk_uri`.

This is the persistence and orchestration foundation, not a completed cloud
provider integration. It does not yet create GitHub Codespaces, run a background
scheduler, provision external object storage, migrate a live VM between runtimes,
or measure provider billing. A provider worker must be implemented and connected
before queued requests can become active. GitHub Codespaces is a short-lived
development runtime only; its 12-hour cap and host/network restrictions make it
unsuitable as a permanent VPS host. Never treat a newly created Codespace as
automatic continuation of the previous VM: recovery requires an independently
persisted disk image and a compatible authorized compute host.

### Environment API example

```http
POST /api/v1/environments/requests
Authorization: Bearer <APOLO_CONTROL_TOKEN>
Content-Type: application/json

{
  "vps_id": "vm-example",
  "provider": "github-codespaces",
  "vcpus": 2,
  "memory_mib": 2048,
  "disk_gib": 30
}
```

The response is `202 Accepted` with `provisioned: false` and state
`waiting_capacity`. This is an honest queued request, not a created VM.


## Environment Provider Worker

The API now has a separate long-running worker process. Run it on the same
persistent API host (or another trusted worker host) with the same
`APOLO_STATE_DB` database path:

```bash
cd backend
python -m pip install -e .
python -m apolo_vps.environment_worker
```

For a Linux deployment, `deploy/apolo-vps-worker.service` is a systemd unit
template. Review its user, paths and environment-file location before enabling
it. Do not run the worker in GitHub Actions or a Codespace as a permanent
daemon; those are temporary execution environments.

### Provider selection and execution contract

- `APOLO_ENABLED_PROVIDERS` is an explicit server-side allowlist. The worker
  currently registers only `libvirt-agent` when the HTTPS agent URL and token
  are configured.
- `github-codespaces` requests are rejected by the worker policy. Codespaces
  remains a short-lived development workspace, not a VM host or recovery target.
- The agent must implement authenticated endpoints:
  - `GET /agent/v1/capacity`: `state: "ok"`, `authorized: true`, and
    `available_vcpus`, `available_memory_mib`, `available_disk_gib`.
  - `POST /agent/v1/disks/ensure`: provision or return an externally durable
    disk; response must include `durable: true` and a stable `disk_uri`.
  - `POST /agent/v1/environments/restore`: attach the disk and request runtime
    creation; response must include `accepted: true` and `runtime_id`.
  - `GET /agent/v1/runtimes/{runtime_id}`: independently report
    `state: "running"` and the exact attached `disk_uri`.
- The worker atomically leases one queued request, checks authorization and
  capacity, ensures persistent storage, requests restore, and performs an
  independent runtime check. It changes the state to `running` only after all
  checks succeed. Insufficient capacity returns the request to the queue;
  unsupported providers or contract violations fail closed.
- SQLite stores metadata and disk references only. It is not a remote disk
  service. The host agent must connect to real persistent storage (for example,
  an object/block storage system with snapshots and access controls) and must
  guarantee that `disk_uri` survives host replacement.

### What is and is not live yet

The worker orchestration and its test doubles are implemented. The real
host-agent endpoints listed above, external storage backend, live billing
meter, automatic monitoring/recovery scheduler, and a production host have
not been connected or validated in this repository. Until those integrations
exist and a real runtime is independently verified, jobs remain queued or fail
closed; no VPS should be advertised as provisioned. GitHub Actions CI validates
code, not host capacity, public networking, durable storage, or VM boot.
