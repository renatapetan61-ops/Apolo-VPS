#!/usr/bin/env bash
set -u

ok=0
warn=0
fail=0
report() {
  local label="$1" state="$2" detail="$3"
  printf '%-28s %-8s %s\n' "$label" "$state" "$detail"
  case "$state" in PASS) ((ok+=1));; WARN) ((warn+=1));; FAIL) ((fail+=1));; esac
}

echo "APOLO VPS / GitHub Codespaces QEMU preflight"
echo "Kernel: $(uname -srmo)"
echo "Architecture: $(uname -m)"
echo "UID: $(id -u) ($(id -un))"
echo

for binary in qemu-system-x86_64 qemu-system-aarch64 qemu-img virsh cloud-localds; do
  if command -v "$binary" >/dev/null 2>&1; then
    report "$binary" PASS "$(command -v "$binary")"
  else
    report "$binary" FAIL "not installed"
  fi
done

if [[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]]; then
  report "/dev/kvm" PASS "read/write access available"
else
  report "/dev/kvm" WARN "KVM acceleration unavailable; use QEMU TCG for development tests only"
fi

if command -v qemu-system-x86_64 >/dev/null 2>&1; then
  if qemu-system-x86_64 -accel help 2>&1 | grep -q '^tcg$'; then
    report "QEMU TCG" PASS "software emulation available"
  else
    report "QEMU TCG" WARN "could not confirm TCG accelerator"
  fi
fi

if command -v virsh >/dev/null 2>&1 && virsh -c qemu:///system list --all >/tmp/apolo-virsh.out 2>&1; then
  report "libvirt system connection" PASS "qemu:///system responds"
else
  report "libvirt system connection" WARN "daemon/socket permissions may be unavailable in Codespaces"
  sed -n '1,2p' /tmp/apolo-virsh.out 2>/dev/null || true
fi

if [[ -w /dev/net/tun ]]; then
  report "TUN/TAP device" PASS "writable"
else
  report "TUN/TAP device" WARN "no writable TUN/TAP; bridged/public guest networking not available"
fi

echo
printf 'Summary: %s PASS, %s WARN, %s FAIL\n' "$ok" "$warn" "$fail"
echo "This diagnostic does not certify Codespaces as a production VPS host."
echo "Production requires persistent compute, supported virtualization, stable storage, routable IPs and network control."
