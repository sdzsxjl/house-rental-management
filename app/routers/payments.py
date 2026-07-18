"""缴费管理路由"""
from datetime import datetime, date
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import Tenant, Contract, Payment
from app.routers.auth import get_current_user

router = APIRouter(prefix="/payments", tags=["缴费管理"])
templates = Jinja2Templates(directory="app/templates")


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


@router.get("")
async def payment_list(request: Request):
    """缴费记录列表"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    payments = db.query(Payment).order_by(Payment.rent_month.desc(), Payment.payment_date.desc()).limit(200).all()

    return templates.TemplateResponse("payments/list.html", {
        "request": request,
        "active_page": "payments",
        "payments": payments,
    })


@router.get("/arrears")
async def arrears_list(request: Request):
    """欠费清单"""
    if r := check_auth(request): return r
    db: Session = next(get_db())
    today = date.today()
    month_key = f"{today.year}-{today.month:02d}"

    active_contracts = db.query(Contract).filter(Contract.is_active == True).all()
    arrears = []

    for contract in active_contracts:
        paid = db.query(Payment).filter(
            Payment.tenant_id == contract.tenant_id,
            Payment.rent_month == month_key
        ).first()
        if not paid:
            # 计算逾期天数
            due_day = contract.payment_due_day
            due_date = date(today.year, today.month, min(due_day, 28))
            if today.day <= due_day:
                days_overdue = 0
                status = "pending"  # 还没到缴费日
            else:
                days_overdue = today.day - due_day
                if days_overdue <= 3:
                    status = "gentle"
                elif days_overdue <= 5:
                    status = "warning"
                else:
                    status = "overdue"
            arrears.append({
                "tenant": contract.tenant,
                "room": contract.room,
                "contract": contract,
                "days_overdue": days_overdue,
                "status": status,
                "month_key": month_key,
            })

    # 按逾期天数从高到低排序
    arrears.sort(key=lambda x: x["days_overdue"], reverse=True)

    return templates.TemplateResponse("payments/arrears.html", {
        "request": request,
        "active_page": "payments",
        "arrears": arrears,
        "month_key": month_key,
    })


@router.post("/add")
async def add_payment(
    request: Request,
    tenant_id: int = Form(...),
    rent_month: str = Form(...),
    amount: float = Form(...),
    payment_method: str = Form("manual"),
    payment_date: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """添加缴费记录"""
    if r := check_auth(request): return r

    # rent_month 可能是 "2026-07" 或 "2026-07-01"
    if len(rent_month) > 7:
        rent_month = rent_month[:7]

    contract = db.query(Contract).filter(
        Contract.tenant_id == tenant_id,
        Contract.is_active == True
    ).first()

    if not contract:
        return RedirectResponse("/tenants", status_code=303)

    pay_date = datetime.strptime(payment_date, "%Y-%m-%d").date()

    # 计算是否逾期
    is_arrears = False
    days_late = 0
    if contract:
        rm_year, rm_month = int(rent_month[:4]), int(rent_month[5:7])
        due_day = min(contract.payment_due_day, 28)
        due_date = date(rm_year, rm_month, due_day)
        if pay_date > due_date:
            is_arrears = True
            days_late = (pay_date - due_date).days

    payment = Payment(
        tenant_id=tenant_id,
        contract_id=contract.id,
        amount=amount,
        rent_month=rent_month,
        payment_date=pay_date,
        payment_method=payment_method,
        is_arrears=is_arrears,
        days_late=days_late,
        notes=notes,
    )
    db.add(payment)
    db.commit()

    return RedirectResponse(f"/tenants/{tenant_id}", status_code=303)


@router.get("/{payment_id}/delete")
async def delete_payment(request: Request, payment_id: int):
    """删除缴费记录"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if payment:
        tid = payment.tenant_id
        db.delete(payment)
        db.commit()
        return RedirectResponse(f"/tenants/{tid}", status_code=303)

    return RedirectResponse("/payments", status_code=303)
