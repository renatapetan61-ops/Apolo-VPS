from apolo_vps.ipam import IPAllocator


def test_ipam_allocates_single_provider_assigned_addresses(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLO_IPV4_CIDR", "8.8.8.8/32")
    monkeypatch.setenv("APOLO_IPV6_CIDR", "2606:4700::1/128")
    allocator = IPAllocator(str(tmp_path / "ipam.sqlite3"))
    assert allocator.allocate("vm-one") == ("8.8.8.8", "2606:4700::1")
    allocator.release("vm-one")
    assert allocator.allocate("vm-two") == ("8.8.8.8", "2606:4700::1")
