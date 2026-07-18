"""仪表盘首页"""
from datetime import date, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import Tenant, Room, Contract, Payment
from app.routers.auth import get_current_user
from app.services.report_service import get_dashboard_stats

router = APIRouter(tags=["仪表盘"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(request: Request):
    """仪表盘首页"""
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)

    db: Session = next(get_db())
    stats = get_dashboard_stats(db)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "stats": stats,
    })
