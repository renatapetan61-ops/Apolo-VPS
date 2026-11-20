# APOLO Free Cloud — Provider Blueprint

## Product objective

Build APOLO Free Cloud as an independent cloud/VPS provider operated by the APOLO platform. The service may offer free Linux VPS instances with remote access, persistent disks, lifecycle controls, monitoring, and automatic free renewals. Windows, dedicated public IPv4, and high-availability guarantees remain unavailable until their licensing, capacity, networking, and operational requirements are met.

This repository contains the control plane and host-agent software. It does not itself supply physical compute, electricity, storage, transit, IP address allocations, or datacenter facilities. A VM must never be advertised as provisioned or running unless a real authorized host confirms it.

## Free-term and renewal policy

- Offer selectable free terms of 1, 2, 5, or 10 years only when the capacity pool has enough funded/committed resources for that term.
- The default term should be 1 year. Renewal is free and automatic when the account remains eligible, the user has not opted out, the service complies with the acceptable-use policy, and the capacity/funding reserve covers the next term.
- Send renewal notices 30 days and 7 days before the term boundary; record every renewal decision and notify the account.
- Never charge a payment method, silently convert a free plan to paid, or promise an unfunded 10-year term.
- If renewal capacity is unavailable, place the instance in a clearly disclosed grace/queue state and preserve its persistent disk for a published retention period. Do not delete user data without notice and policy.
- Publish resource quotas, network limitations, support level, backup policy, maintenance windows, and retention period before signup. Do not advertise IPv4 unless an authorized upstream provider delegates routable addresses and routing is verified.
- Free renewal is a service policy, not a claim that underlying infrastructure is cost-free.

## Proposed platform architecture

1. **Public control plane** — account registration, MFA, tenant isolation, VPS catalog, lifecycle API, quota checks, audit events, and renewal scheduler.
2. **Capacity registry** — inventory of independently enrolled compute nodes; records architecture, CPU/RAM/disk capacity, virtualization support, region, health, and provider authorization.
3. **Node agent** — authenticated host service that reports measured capacity and performs allowlisted libvirt operations. Management traffic must use private HTTPS or VPN; never expose libvirt or agent ports publicly.
4. **Persistent storage** — independently mounted durable block/file storage, snapshots, integrity checks, quotas, and documented recovery. Local ephemeral host disks are not a persistent VPS disk.
5. **Network plane** — isolated tenant networks, firewall policy, anti-spoofing, abuse controls, IPv6 first where delegated, and IPv4 only from a real authorized allocation.
6. **Scheduler** — places requests only on healthy compatible nodes with sufficient reserved capacity; queues requests rather than fabricating capacity.
7. **Renewal service** — idempotent scheduled renewal, eligibility evaluation, capacity reservation, notices, audit trail, opt-out, and grace handling.
8. **Operations** — monitoring, alerting, backups, security updates, incident response, abuse handling, and published status page.

## Initial delivery phases

### Phase 0 — Honest software foundation
- Keep the current libvirt-agent path as the first real compute adapter.
- Add provider/node registration, measured capacity inventory, and health state.
- Add a free-plan catalog and subscription/term state machine.
- Add renewal scheduler with idempotency keys, notices, opt-out, and capacity reservation.
- Add tenant ownership and audit enforcement before public signup.

### Phase 1 — One real pilot node
- Enroll one authorized Linux x86-64 KVM/libvirt host.
- Verify /dev/kvm, libvirt, bridge/firewall, NFS or equivalent durable storage, base image, backups, and private agent connectivity.
- Run create/write/shutdown/restore tests and verify the same disk and marker data.
- Do not publish public VPS signup until security and isolation tests pass.

### Phase 2 — Sustainable free capacity
- Add additional owned, donated, sponsored, or community-contributed nodes under explicit agreements.
- Track actual power, network, storage, replacement, and operations costs.
- Set free quotas from measured spare capacity and a reserve for renewals/recovery.
- Publish the maximum number of free instances supportable without risking existing users.

### Phase 3 — Broader catalog
- Add ARM64 and Windows only after dedicated provisioners, authorized images/licenses, firmware/drivers, guest networking, remote access, and real integration tests are complete.
- Add IPv4 only when address allocation and upstream routing are contractually authorized and tested.

## Launch gates

The service is not production-ready until all of these are evidenced:
- At least one persistent host is enrolled and independently health-checked.
- KVM/libvirt and network isolation tests pass on that host.
- Persistent storage survives host restart/replacement and recovery tests.
- A real guest can boot, receive credentials securely, reach only its authorized network, and be managed by its tenant.
- Renewal logic is tested for duplicate events, expired subscriptions, opt-out, capacity exhaustion, and recovery.
- Quotas, privacy, acceptable use, abuse response, backups, retention, and incident contacts are published.
- Free capacity is funded or contractually committed for the advertised renewal term.

## Current repository boundary

The existing APOLO VPS repository already contains a FastAPI control plane, React dashboard, libvirt host agent, persistent-disk checks, environment worker, and systemd templates. These are software foundations, not an operational provider. No real host, storage export, public network allocation, or funded capacity is assumed by this blueprint.
