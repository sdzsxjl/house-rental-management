"""催租面板路由 — 支持自动推送到房东和直接推送到租客"""
from datetime import date
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import Contract, Payment, ReminderLog
from app.routers.auth import get_current_user
from app.config import settings
from app.services.reminder_service import (
    get_reminder_tier, generate_reminder_text, run_daily_reminder_check,
)
from app.services.notification_service import (
    send_reminder_to_tenant_directly,
    push_to_landlord_summary,
)

router = APIRouter(prefix="/reminders", tags=["催租管理"])
templates = Jinja2Templates(directory="app/templates")


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


@router.get("")
async def reminder_panel(request: Request):
    """催租面板 — 显示所有需要催收的租客和文案"""
    if r := check_auth(request): return r
    db: Session = next(get_db())
    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"

    active_contracts = db.query(Contract).filter(Contract.is_active == True).all()

    reminders = {"gentle": [], "warning": [], "overdue": [], "total": 0}

    for contract in active_contracts:
        tier, days_overdue, due_date = get_reminder_tier(contract, today)
        if tier is None:
            continue

        paid = db.query(Payment).filter(
            Payment.tenant_id == contract.tenant_id,
            Payment.rent_month == month_key,
        ).first()
        if paid:
            continue

        text = generate_reminder_text(
            contract.tenant, contract, tier, days_overdue, due_date,
        )

        reminders[tier].append({
            "tenant": contract.tenant,
            "contract": contract,
            "room": contract.room,
            "text": text,
            "days_overdue": days_overdue,
            "due_date": due_date,
        })
        reminders["total"] += 1

    recent_logs = db.query(ReminderLog).order_by(
        ReminderLog.sent_at.desc()
    ).limit(50).all()

    return templates.TemplateResponse("reminders/list.html", {
        "request": request,
        "active_page": "reminders",
        "reminders": reminders,
        "recent_logs": recent_logs,
        "today": today,
        "month_key": month_key,
        "landlord_notify": settings.any_landlord_notification_enabled,
        "tenant_notify": settings.any_tenant_notification_enabled,
    })


@router.get("/run-check")
async def force_reminder_check(request: Request):
    """手动触发催租检查 + 自动推送汇总给房东"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    result = run_daily_reminder_check(db)

    if settings.any_landlord_notification_enabled and result["total"] > 0:
        await push_to_landlord_summary(
            result["gentle"], result["warning"], result["overdue"],
            rent_month=f"{date.today().year}-{date.today().month:02d}",
        )

    return RedirectResponse("/reminders", status_code=303)


@router.get("/send-to-tenant/{tenant_id}")
async def send_directly_to_tenant(request: Request, tenant_id: int):
    """
    直接推送催租消息给租客 ⭐
    - 如果配置了短信 → 发短信到租客手机
    - 如果配置了企微客户联系 → 发消息到租客的微信
    """
    if r := check_auth(request): return r
    db: Session = next(get_db())

    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"

    contract = db.query(Contract).filter(
        Contract.tenant_id == tenant_id,
        Contract.is_active == True,
    ).first()

    if not contract:
        return RedirectResponse("/reminders", status_code=303)

    tier, days_overdue, due_date = get_reminder_tier(contract, today)
    if tier is None:
        return RedirectResponse("/reminders?skipped=no_need", status_code=303)

    text = generate_reminder_text(contract.tenant, contract, tier, days_overdue, due_date)

    # 记录日志
    log = ReminderLog(
        tenant_id=tenant_id,
        contract_id=contract.id,
        reminder_type=tier,
        rent_month=month_key,
        message_text=text,
        sent_via="direct" if settings.any_tenant_notification_enabled else "log",
    )
    db.add(log)
    db.commit()

    # ⭐ 直接推送给租客（短信 + 企微→微信）
    results = await send_reminder_to_tenant_directly(
        tenant_name=contract.tenant.name,
        tenant_phone=contract.tenant.phone,
        tenant_wechat_id=contract.tenant.wechat_id or "",
        room_code=contract.room.full_room_code,
        reminder_text=text,
        rent_month=month_key,
        monthly_rent=contract.monthly_rent,
        due_day=contract.payment_due_day,
        days_overdue=days_overdue,
    )

    success = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    return RedirectResponse(
        f"/reminders?direct=1&sent={len(success)}&tenant={contract.tenant.name}",
        status_code=303,
    )


@router.get("/send-all-to-tenants")
async def send_all_directly_to_tenants(request: Request):
    """
    一键给所有待催租客直接发消息 ⭐
    短信 + 企微微信双通道，租客直接收到，房东零操作
    """
    if r := check_auth(request): return r
    db: Session = next(get_db())

    if not settings.any_tenant_notification_enabled:
        return RedirectResponse("/reminders?error=no_tenant_channel", status_code=303)

    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"

    active_contracts = db.query(Contract).filter(Contract.is_active == True).all()

    sent_count = 0
    skip_count = 0
    fail_count = 0

    for contract in active_contracts:
        tier, days_overdue, due_date = get_reminder_tier(contract, today)
        if tier is None:
            continue

        paid = db.query(Payment).filter(
            Payment.tenant_id == contract.tenant_id,
            Payment.rent_month == month_key,
        ).first()
        if paid:
            continue

        # 今天已发过的不重复
        already = db.query(ReminderLog).filter(
            ReminderLog.tenant_id == contract.tenant_id,
            ReminderLog.rent_month == month_key,
            ReminderLog.sent_at == today,
        ).first()
        if already:
            skip_count += 1
            continue

        text = generate_reminder_text(contract.tenant, contract, tier, days_overdue, due_date)

        log = ReminderLog(
            tenant_id=contract.tenant_id,
            contract_id=contract.id,
            reminder_type=tier,
            rent_month=month_key,
            message_text=text,
            sent_via="direct",
        )
        db.add(log)

        # ⭐ 直接推送给租客
        results = await send_reminder_to_tenant_directly(
            tenant_name=contract.tenant.name,
            tenant_phone=contract.tenant.phone,
            tenant_wechat_id=contract.tenant.wechat_id or "",
            room_code=contract.room.full_room_code,
            reminder_text=text,
            rent_month=month_key,
            monthly_rent=contract.monthly_rent,
            due_day=contract.payment_due_day,
            days_overdue=days_overdue,
        )

        if any(r.success for r in results):
            sent_count += 1
        else:
            fail_count += 1

    db.commit()

    return RedirectResponse(
        f"/reminders?direct_all=1&sent={sent_count}&skipped={skip_count}&failed={fail_count}",
        status_code=303,
    )
