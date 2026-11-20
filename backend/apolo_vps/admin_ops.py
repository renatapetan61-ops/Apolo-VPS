from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from .accounts import admin_user, connect, init_db, stamp, now, audit

router = APIRouter()

class ActivateSubscription(BaseModel):
    instance_id: str = Field(min_length=4, max_length=80)

@router.post("/admin/subscriptions/{subscription_id}/activate")
def activate_subscription(subscription_id: str, payload: ActivateSubscription,
                           admin=Depends(admin_user)):
    init_db()
    with connect() as db:
        sub = db.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
        if not sub:
            raise HTTPException(404, "Assinatura não encontrada.")
        if sub["state"] != "capacity_reserved" or not sub["node_id"]:
            raise HTTPException(409, "A assinatura precisa ter capacidade reservada antes da ativação.")
        node = db.execute("SELECT * FROM capacity_nodes WHERE id=?", (sub["node_id"],)).fetchone()
        if not node or node["state"] != "healthy" or not node["verified"]:
            raise HTTPException(409, "O host reservado não está saudável e verificado.")
        has_inventory = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instances'").fetchone()
        if not has_inventory:
            raise HTTPException(409, "O inventário de VPS ainda não foi inicializado.")
        instance = db.execute("SELECT id FROM instances WHERE id=?", (payload.instance_id,)).fetchone()
        if not instance:
            raise HTTPException(409, "A instância não existe no inventário do APOLO VPS; não é possível ativar a assinatura.")
        started = now()
        renews = started + timedelta(days=365 * int(sub["term_years"]))
        db.execute("""UPDATE subscriptions SET state='active',instance_id=?,starts_at=?,renews_at=?,updated_at=?
                      WHERE id=?""",
                   (payload.instance_id, stamp(started), stamp(renews), stamp(started), subscription_id))
        db.execute("""UPDATE provisioning_queue SET state='provisioned',updated_at=?
                      WHERE subscription_id=?""", (stamp(started), subscription_id))
        audit(db, admin["id"], "subscription.activated", subscription_id,
              {"instance_id": payload.instance_id, "renews_at": stamp(renews)})
    return {"subscription_id": subscription_id, "state": "active",
            "instance_id": payload.instance_id, "renews_at": stamp(renews),
            "provisioned": True}

