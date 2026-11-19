from apolo_vps.catalog import list_images


def test_catalog_exposes_requested_windows_versions_but_fails_closed(tmp_path, monkeypatch):
    image = tmp_path / "licensed-windows.iso"
    image.write_bytes(b"test-fixture")
    for key in (
        "APOLO_IMAGE_WINDOWS_11_X64",
        "APOLO_IMAGE_WINDOWS_10_X64",
        "APOLO_IMAGE_WINDOWS_11_ARM64",
        "APOLO_IMAGE_WINDOWS_10_ARM64",
        "APOLO_IMAGE_WINDOWS_8_X64",
        "APOLO_IMAGE_WINDOWS_7_X64",
        "APOLO_IMAGE_WINDOWS_2022",
    ):
        monkeypatch.setenv(key, str(image))
    monkeypatch.setenv("APOLO_WINDOWS_TEMPLATE", str(image))

    images = {item["id"]: item for item in list_images()}
    expected = {
        "windows-11-x64": "x86_64",
        "windows-10-x64": "x86_64",
        "windows-11-arm64": "aarch64",
        "windows-10-arm64": "aarch64",
        "windows-8-x64": "x86_64",
        "windows-7-x64": "x86_64",
    }
    for image_id, architecture in expected.items():
        assert images[image_id]["architecture"] == architecture
        assert images[image_id]["enabled"] is False
        assert "Planned catalog entry" in images[image_id]["note"]


def test_catalog_enables_only_verified_supported_x64_linux(tmp_path, monkeypatch):
    image = tmp_path / "ubuntu-cloud.qcow2"
    image.write_bytes(b"test-fixture")
    monkeypatch.setenv("APOLO_IMAGE_UBUNTU_2404", str(image))

    images = {item["id"]: item for item in list_images()}
    assert images["ubuntu-24.04"]["enabled"] is True
    assert images["ubuntu-24.04"]["architecture"] == "x86_64"
    assert images["ubuntu-24.04-arm64"]["enabled"] is False
