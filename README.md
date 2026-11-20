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

### Host agent endpoints and shared persistent storage

The host agent implements these authenticated routes (header: `X-Apolo-Agent-Token`):

- `GET /agent/v1/capacity`: reads live libvirt CPU/memory data and free space on the persistent volume.
- `POST /agent/v1/disks/ensure`: creates or validates a QCOW2 overlay on the shared volume.
- `POST /agent/v1/environments/restore`: defines or restarts a libvirt domain with that disk attached.
- `GET /agent/v1/runtimes/{runtime_id}`: reads domain state and attached disk from libvirt XML.

Required host-only settings:

- `APOLO_PERSISTENT_STORAGE_MOUNT`: mountpoint of an NFS/NFS4 shared export. The agent refuses ordinary local directories and non-NFS filesystems.
- `APOLO_ENVIRONMENT_BASE_IMAGE`: verified x86_64 Linux cloud image **stored inside the same NFS export**, for example `/srv/apolo-persistent/images/ubuntu-24.04-server-cloudimg-amd64.img`. The agent rejects a host-local backing image: a QCOW2 overlay references its backing file, so the base image must remain reachable at the identical path after host replacement.
- `APOLO_LIBVIRT_BRIDGE`: preconfigured bridge on the hypervisor.

The host agent checks the base image format with `qemu-img info`, supports QCOW2 and raw backing images, creates the overlay using the detected format, and verifies that the resulting QCOW2 metadata points to the exact shared backing-image path. Keep the image immutable and publish updates as versioned files; do not overwrite an image while running overlays depend on it.

### Host agent systemd service

The repository includes `deploy/apolo-vps-agent.service`. Review its service user, `libvirt`/`kvm` group membership, NFS mount path and binary paths before installation. The service binds to loopback on port 8090; expose it to the control plane only through a private VPN or TLS reverse proxy. Create `/etc/apolo-vps/agent.env` with at least:

```bash
APOLO_AGENT_TOKEN=<long-random-secret>
APOLO_PERSISTENT_STORAGE_MOUNT=/srv/apolo-persistent
APOLO_ENVIRONMENT_BASE_IMAGE=/srv/apolo-persistent/images/ubuntu-24.04-server-cloudimg-amd64.img
APOLO_LIBVIRT_BRIDGE=br-vps
APOLO_LIBVIRT_URI=qemu:///system
```

Protect that file with root ownership and mode 0600, grant the service account only the required libvirt and NFS permissions, then install and inspect the service:

```bash
sudo install -o root -g root -m 0600 /path/to/agent.env /etc/apolo-vps/agent.env
sudo install -m 0644 deploy/apolo-vps-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now apolo-vps-agent
sudo systemctl status apolo-vps-agent
```

Do not copy a production token into the repository, issue tracker or chat. The control-plane worker must use the same token in `APOLO_PROVISIONER_TOKEN`, stored in its own secret manager.

The NFS export must be provisioned, mounted at boot, monitored and backed up by the infrastructure operator. A successful mount check does not prove replication, backup, failover or a recovery-point objective. New environment VMs use the configured cloud image as a backing image; guest cloud-init credentials/network bootstrap for this separate environment workflow still needs integration before exposing these environments as user-ready VPSs.

To test on the actual host, configure these values, run the agent behind private HTTPS/VPN, configure the worker with the matching token, submit a small environment request, verify the domain and NFS-backed disk, stop the domain, then submit a recovery request and confirm the same disk URI is attached after restart. Do not run this acceptance test against a production disk without a snapshot/backup.

### What is and is not live yet

The worker orchestration and its test doubles are implemented. The host agent now implements the four worker endpoints. Its persistent-disk adapter accepts only an operator-mounted NFS/NFS4 volume and verifies the mount with findmnt; it creates QCOW2 overlays from APOLO_ENVIRONMENT_BASE_IMAGE, defines/starts a libvirt domain, and independently inspects the domain and attached disk. This is implementation code, not proof that a production NFS service or hypervisor has been configured. The real host, NFS server/export, network bridge, base image, private TLS/VPN route, and integration test have not been connected or validated. Live billing and automatic monitoring/recovery scheduling also remain unimplemented. Until those integrations
exist and a real runtime is independently verified, jobs remain queued or fail
closed; no VPS should be advertised as provisioned. GitHub Actions CI validates
code, not host capacity, public networking, durable storage, or VM boot.


## APOLO Free Cloud accounts, plans and renewals (software stage)

The API now exposes account registration, email verification, bearer sessions, a free Linux plan, subscription requests, a capacity wait queue, host capacity inventory, admin views, audit events, and a scheduled renewal worker.

### Required API secrets and mail delivery

Set these in the API secret manager (never commit them):

- `APOLO_AUTH_SECRET`: at least 32 random characters; signs 12-hour account sessions.
- `APOLO_BOOTSTRAP_ADMIN_TOKEN`: at least 32 random characters; used once to promote the first verified account to admin. Remove it immediately after bootstrap.
- `APOLO_EMAIL_SMTP_HOST`, `APOLO_EMAIL_SMTP_PORT`, `APOLO_EMAIL_SMTP_USER`, `APOLO_EMAIL_SMTP_PASSWORD`, `APOLO_EMAIL_FROM`: SMTP delivery for email verification. Port 465 uses SMTP over SSL; other ports use STARTTLS.
- `APOLO_STATE_DB`: durable SQLite database path shared by API and renewal job.

A registration remains `pending_verification` until the email token is confirmed. Do not expose verification tokens in API responses or logs. Without SMTP configuration the API intentionally refuses to complete the registration flow.

### Account and plan endpoints

- `POST /api/v1/auth/register` — create a pending account.
- `POST /api/v1/auth/verify-email` — verify the token delivered by email.
- `POST /api/v1/auth/login` — obtain a 12-hour bearer session.
- `GET /api/v1/auth/me` — current account.
- `GET /api/v1/plans` — enabled free plans and available term choices.
- `POST /api/v1/subscriptions` — request the free plan for 1, 2, 5 or 10 years; it may enter the capacity queue.
- `GET /api/v1/subscriptions` — current account subscriptions.
- `PATCH /api/v1/subscriptions/{id}/auto-renew` — enable or disable free renewal.

### Admin endpoints

- `POST /api/v1/admin/bootstrap` — one-time first-admin promotion; requires a verified bearer session and `X-Apolo-Bootstrap-Token`.
- `GET /api/v1/admin/overview`, `/users`, `/subscriptions`, `/audit` — administration views.
- `POST /api/v1/admin/nodes` — register a host node (not capacity eligible yet).
- `POST /api/v1/admin/nodes/{id}/probe` — measure capacity from the configured private HTTPS host agent.
- `POST /api/v1/admin/queue/reconcile` — reserve measured free capacity for waiting requests.
- `POST /api/v1/admin/subscriptions/{id}/activate` — start the subscription term only after the referenced VPS is present in the instance inventory.

The current host-agent configuration represents one host. The API prevents registering that same configured agent as multiple capacity nodes, which would otherwise double-count resources. Multi-node enrollment requires a dedicated per-node credential/secret-manager design before it is enabled.

### Queue and provisioning truth

Queue states are `waiting_capacity`, `capacity_reserved`, and `provisioned`. A reservation is not a running VPS. The admin activation endpoint verifies that the supplied instance ID exists in the APOLO instance inventory and that the reserved host is still healthy. Public tenant-to-VM provisioning and secure credential delivery still require a further integration milestone; the existing legacy VM create endpoint remains protected by its separate control token.

### Automatic free renewals

Install the systemd timer on the durable API host after reviewing user, paths and database permissions:

```bash
sudo install -m 0644 deploy/apolo-vps-renewal.service /etc/systemd/system/
sudo install -m 0644 deploy/apolo-vps-renewal.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now apolo-vps-renewal.timer
systemctl list-timers apolo-vps-renewal.timer
```

The worker renews only subscriptions in `active` state with a healthy verified capacity node. If capacity is unavailable, the subscription enters `grace`; no paid conversion occurs. The scheduler must run against the same durable `APOLO_STATE_DB` as the API. Renewal is not a guarantee of unfunded compute for ten years: the service must reserve or commit resources for every advertised term.

### Current implementation boundary

The backend foundation is implemented, but it is not yet a public production cloud: configure SMTP and secrets, complete security review/rate limiting and tenant ownership for the legacy VM lifecycle routes, connect a real verified host, finish guest provisioning from subscriptions, and run real end-to-end VM recovery tests before accepting public customers.
