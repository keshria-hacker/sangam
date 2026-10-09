"""
api_routes/automations_routes.py — scheduled tasks + triggers (Phase 5).
"""
import uuid
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..automations import parse_schedule, validate_automation
from ..database import get_db
from ..models import Automation
from .common import router


class AutomationIn(BaseModel):
    name: str
    trigger: str  # 'daily' | 'hourly' | 'weekly' | cron expression
    action: str  # 'agent' | 'chat'
    config: dict = {}  # {task, model, ...}
    enabled: bool = True


@router.post("/automations", status_code=201)
async def create_automation(payload: AutomationIn, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    err = validate_automation(payload.trigger, payload.action)
    if err:
        raise HTTPException(status_code=422, detail=err)
    auto = Automation(
        id=f"auto-{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        name=payload.name[:200],
        trigger=payload.trigger,
        action=payload.action,
        config_json=__import__("json").dumps(payload.config),
        enabled=payload.enabled,
        created_at=datetime.now(UTC),
    )
    # Compute next run
    auto.next_run = parse_schedule(payload.trigger)
    db.add(auto)
    await db.commit()
    return {"id": auto.id}


@router.get("/automations")
async def list_automations(db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    autos = (await db.execute(
        select(Automation).where(Automation.user_id == user.id)
        .order_by(desc(Automation.created_at))
    )).scalars().all()
    return {"automations": [
        {"id": a.id, "name": a.name, "trigger": a.trigger, "action": a.action,
         "enabled": a.enabled, "config": __import__("json").loads(a.config_json or "{}"),
         "last_run": a.last_run.isoformat() if a.last_run else None,
         "next_run": a.next_run.isoformat() if a.next_run else None}
        for a in autos
    ]}


@router.get("/automations/{automation_id}")
async def get_automation(automation_id: str, db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    auto = await db.get(Automation, automation_id)
    if not auto or auto.user_id != user.id:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {
        "id": auto.id, "name": auto.name, "trigger": auto.trigger,
        "action": auto.action, "enabled": auto.enabled,
        "config": __import__("json").loads(auto.config_json or "{}"),
        "last_run": auto.last_run.isoformat() if auto.last_run else None,
        "next_run": auto.next_run.isoformat() if auto.next_run else None,
    }


@router.put("/automations/{automation_id}")
async def update_automation(automation_id: str, payload: AutomationIn,
                            db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    auto = await db.get(Automation, automation_id)
    if not auto or auto.user_id != user.id:
        raise HTTPException(status_code=404, detail="Automation not found")
    err = validate_automation(payload.trigger, payload.action)
    if err:
        raise HTTPException(status_code=422, detail=err)
    auto.name = payload.name[:200]
    auto.trigger = payload.trigger
    auto.action = payload.action
    auto.config_json = __import__("json").dumps(payload.config)
    auto.enabled = payload.enabled
    auto.next_run = parse_schedule(payload.trigger)
    await db.commit()
    return {"ok": True}


@router.delete("/automations/{automation_id}")
async def delete_automation(automation_id: str, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    auto = await db.get(Automation, automation_id)
    if not auto or auto.user_id != user.id:
        raise HTTPException(status_code=404, detail="Automation not found")
    await db.delete(auto)
    await db.commit()
    return {"ok": True}


@router.post("/automations/{automation_id}/run")
async def run_automation_now(automation_id: str, db: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user)):
    """Trigger an automation immediately."""
    auto = await db.get(Automation, automation_id)
    if not auto or auto.user_id != user.id:
        raise HTTPException(status_code=404, detail="Automation not found")
    from ..automations import execute_automation
    result = await execute_automation(auto, db)
    return result
