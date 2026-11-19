FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    qemu-system-x86 qemu-system-arm qemu-utils qemu-block-extra \
    libvirt-clients libvirt-daemon-system libvirt-daemon-driver-qemu \
    ovmf cloud-image-utils genisoimage bridge-utils iproute2 \
    cpu-checker curl jq python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Codespaces is a development/test environment. Do not assume /dev/kvm,
# systemd, TAP/bridge privileges, or nested virtualization are available.
