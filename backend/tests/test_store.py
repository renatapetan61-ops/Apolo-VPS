from apolo_vps.store import InstanceStore


def test_store_roundtrip(tmp_path):
    store = InstanceStore(str(tmp_path / "state.sqlite3"))
    record = {"id":"vm-1","name":"apolo-test","username":"ubuntu","os":"ubuntu-24.04",
              "ipv4":"8.8.8.8","ipv6":"2606:4700::1","state":"running"}
    store.save(record)
    assert store.get_by_name("apolo-test")["ipv4"] == "8.8.8.8"
    assert store.list()[0]["id"] == "vm-1"
    store.delete("vm-1")
    assert store.list() == []
