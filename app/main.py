"""FastAPI 应用工厂"""
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

from app.database import engine, Base, SessionLocal
from app.routers import (
    auth, dashboard, tenants, payments, bank, contracts, reminders, settings, billing,
)
from app.services.reminder_service import run_daily_reminder_check
from app.services.notification_service import (
    push_to_landlord_summary, send_reminder_to_tenant_directly,
)
from app.config import settings as app_settings

# ─── 定时任务 ────────────────────────────────────────────

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def daily_reminder_job():
    """每日 9:00 自动催租：通知房东 + 直接催租客"""
    db = SessionLocal()
    try:
        result = run_daily_reminder_check(db)
        total = result["total"]

        if total > 0:
            gentle = result["gentle"]
            warning = result["warning"]
            overdue = result["overdue"]
            print(f"[催租] {total} 条: 温和={len(gentle)} 警告={len(warning)} 逾期={len(overdue)}")

            loop = asyncio.new_event_loop()
            try:
                # 1. 推送汇总给房东
                if app_settings.any_landlord_notification_enabled:
                    loop.run_until_complete(
                        push_to_landlord_summary(
                            gentle, warning, overdue,
                            rent_month=f"{__import__('datetime').date.today().year}-{__import__('datetime').date.today().month:02d}",
                        )
                    )
                    print("[催租] 已推送汇总给房东")

                # 2. 直接推送给租客（短信 + 企微→微信）
                if app_settings.any_tenant_notification_enabled:
                    all_reminders = overdue + warning + gentle
                    sent = 0
                    for r in all_reminders:
                        if r["tenant"].phone:
                            results = loop.run_until_complete(
                                send_reminder_to_tenant_directly(
                                    tenant_name=r["tenant"].name,
                                    tenant_phone=r["tenant"].phone,
                                    tenant_wechat_id=r["tenant"].wechat_id or "",
                                    room_code=r["room"].full_room_code,
                                    reminder_text=r["text"],
                                    rent_month=f"{__import__('datetime').date.today().year}-{__import__('datetime').date.today().month:02d}",
                                    monthly_rent=r["contract"].monthly_rent,
                                    due_day=r["contract"].payment_due_day,
                                    days_overdue=r["days_overdue"],
                                )
                            )
                            if any(r for r in results if r.success):
                                sent += 1
                    print(f"[催租] 已直接推送给 {sent}/{len(all_reminders)} 个租客")
            finally:
                loop.close()
        else:
            print("[催租] 今日无需催收")
    except Exception as e:
        print(f"[催租] 异常: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(daily_reminder_job, "cron", hour=9, minute=0, id="daily_reminder")
    scheduler.start()
    parts = ["定时催租 (每日 09:00)"]
    if app_settings.any_landlord_notification_enabled:
        parts.append("通知房东 ✓")
    if app_settings.any_tenant_notification_enabled:
        parts.append("直推租客 ✓")
    print(f"[系统] {' · '.join(parts)}")
    yield
    scheduler.shutdown(wait=False)


# ─── 应用 ────────────────────────────────────────────────

Base.metadata.create_all(bind=engine)

app = FastAPI(title="房屋租赁收租管理系统", version="1.0.0", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

for m in [auth, dashboard, tenants, payments, contracts, reminders, bank, settings, billing]:
    app.include_router(m.router)
