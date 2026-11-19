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
