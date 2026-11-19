from apolo_vps.security import generate_password, generated_hostname
from apolo_vps.catalog import list_images


def test_password_has_required_character_classes():
    password = generate_password()
    assert len(password) == 24
    assert any(c.islower() for c in password)
    assert any(c.isupper() for c in password)
    assert any(c.isdigit() for c in password)
    assert any(c in "!@#$%^&*()-_=+" for c in password)


def test_generated_hostname_is_valid():
    assert generated_hostname().startswith("apolo-")


def test_images_are_not_enabled_without_real_files(monkeypatch, tmp_path):
    for key in ("APOLO_IMAGE_UBUNTU_2404", "APOLO_IMAGE_DEBIAN_12", "APOLO_IMAGE_ROCKY_9", "APOLO_IMAGE_WINDOWS_2022"):
        monkeypatch.delenv(key, raising=False)
    assert all(not image["enabled"] for image in list_images())
