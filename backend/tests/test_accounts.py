import os
from datetime import timedelta

from fastapi.testclient import TestClient

from apolo_vps import accounts
from apolo_vps.main import app


def setup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLO_STATE_DB", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("APOLO_AUTH_SECRET", "test-secret-that-is-at-least-32-characters-long")
    accounts.init_db()


def test_registration_verification_login_and_free_subscription(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    sent = {}
    monkeypatch.setattr(accounts, "send_verification",
                        lambda email, name, token: sent.update(email=email, token=token))
    with TestClient(app) as client:
        registered = client.post("/api/v1/auth/register", json={
            "email":"person@example.com","display_name":"Test User",
            "password":"StrongPassword123"
        })
        assert registered.status_code == 202
        assert registered.json()["state"] == "pending_verification"
        assert client.post("/api/v1/auth/login", json={
            "email":"person@example.com","password":"StrongPassword123"
        }).status_code == 403
        verified = client.post("/api/v1/auth/verify-email", json={"token":sent["token"]})
        assert verified.status_code == 200
        login = client.post("/api/v1/auth/login", json={
            "email":"person@example.com","password":"StrongPassword123"
        })
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization":"Bearer " + token}
        plans = client.get("/api/v1/plans")
        assert plans.status_code == 200
        assert plans.json()["plans"][0]["terms_years"] == [1,2,5,10]
        subscribed = client.post("/api/v1/subscriptions", headers=headers,
                                 json={"plan_id":"free-linux","term_years":10,"auto_renew":True})
        assert subscribed.status_code == 202
        assert subscribed.json()["provisioned"] is False
        assert subscribed.json()["subscription"]["state"] == "waiting_capacity"
        assert client.get("/api/v1/subscriptions", headers=headers).json()["subscriptions"]


def test_queue_reserves_only_measured_healthy_capacity(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    with accounts.connect() as db:
        db.execute("INSERT INTO users(id,email,display_name,password_hash,role,state,created_at) VALUES('u1','u@example.com','User','hash','user','active',?)",(accounts.stamp(),))
        db.execute("INSERT INTO capacity_nodes(id,name,state,verified,free_vcpus,free_memory_mib,free_disk_gib,created_at) VALUES('n1','host','pending_verification',0,8,8192,500,?)",(accounts.stamp(),))
        db.execute("INSERT INTO subscriptions(id,user_id,plan_id,term_years,state,auto_renew,created_at,updated_at) VALUES('s1','u1','free-linux',1,'waiting_capacity',1,?,?)",(accounts.stamp(),accounts.stamp()))
        db.execute("INSERT INTO provisioning_queue(id,subscription_id,user_id,vcpus,memory_mib,disk_gib,state,created_at,updated_at) VALUES('q1','s1','u1',1,1024,20,'waiting_capacity',?,?)",(accounts.stamp(),accounts.stamp()))
        assert accounts.allocate_waiting(db) == 0
        db.execute("UPDATE capacity_nodes SET state='healthy',verified=1 WHERE id='n1'")
        assert accounts.allocate_waiting(db) == 1
        row=db.execute("SELECT state,node_id FROM provisioning_queue WHERE id='q1'").fetchone()
        node=db.execute("SELECT reserved_vcpus,reserved_memory_mib,reserved_disk_gib FROM capacity_nodes WHERE id='n1'").fetchone()
        assert row["state"] == "capacity_reserved"
        assert row["node_id"] == "n1"
        assert tuple(node) == (1,1024,20)


def test_renewal_is_deferred_when_reserved_host_is_unhealthy(monkeypatch, tmp_path):
    setup_env(monkeypatch, tmp_path)
    due = accounts.now() - timedelta(days=1)
    with accounts.connect() as db:
        db.execute("INSERT INTO users(id,email,display_name,password_hash,role,state,created_at) VALUES('u1','u@example.com','User','hash','user','active',?)",(accounts.stamp(),))
        db.execute("INSERT INTO capacity_nodes(id,name,state,verified,created_at) VALUES('n1','host','offline',0,?)",(accounts.stamp(),))
        db.execute("""INSERT INTO subscriptions(id,user_id,plan_id,term_years,state,auto_renew,renews_at,node_id,created_at,updated_at)
          VALUES('s1','u1','free-linux',1,'active',1,?,'n1',?,?)""",
          (accounts.stamp(due),accounts.stamp(),accounts.stamp()))
    result=accounts.process_due_renewals()
    assert result["deferred_for_capacity"] == 1
    with accounts.connect() as db:
        assert db.execute("SELECT state FROM subscriptions WHERE id='s1'").fetchone()["state"] == "grace"
