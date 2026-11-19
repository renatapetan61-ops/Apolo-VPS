#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo/root on the dedicated Debian/Ubuntu KVM host." >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y qemu-kvm qemu-utils libvirt-daemon-system libvirt-clients python3-libvirt python3-venv python3-pip cloud-image-utils openssl bridge-utils
systemctl enable --now libvirtd || systemctl enable --now virtqemud
mkdir -p /var/lib/libvirt/images/apolo-vps
chmod 0750 /var/lib/libvirt/images/apolo-vps
if [[ ! -e /dev/kvm ]]; then
  echo "ERROR: /dev/kvm missing. Enable VT-x/AMD-V and nested virtualization if applicable." >&2
  exit 2
fi
echo "KVM/libvirt packages installed."
echo "Network was NOT modified: configure and test a dedicated bridge and provider-routed public IPv4/IPv6 before provisioning."
echo "Use a Python venv created with --system-site-packages to import OS package python3-libvirt."
