"""账单管理路由"""
from datetime import date, datetime
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import Room, Tenant, Contract, UtilityBill
from app.routers.auth import get_current_user

router = APIRouter(prefix="/billing", tags=["账单管理"])
templates = Jinja2Templates(directory="app/templates")

WATER_UNIT_PRICE = 6.0   # 水费单价（元/方）
ELEC_UNIT_PRICE = 1.0    # 电费单价（元/度）


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


def _prev_month(bill_month: str) -> str:
    """计算上一个月"""
    year, month = int(bill_month[:4]), int(bill_month[5:7])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def _calc_bill(bill: UtilityBill) -> None:
    """根据读数计算用量和费用"""
    bill.water_usage = max(0, bill.water_current_reading - bill.water_previous_reading)
    bill.water_fee = round(bill.water_usage * bill.water_unit_price, 2)
    bill.electricity_usage = max(0, bill.electricity_current_reading - bill.electricity_previous_reading)
    bill.electricity_fee = round(bill.electricity_usage * bill.electricity_unit_price, 2)
    bill.total_amount = round(bill.water_fee + bill.electricity_fee + bill.monthly_rent, 2)
    bill.status = "calculated"


def _build_worksheet(db: Session, bill_month: str) -> list[dict]:
    """构建工作表数据"""
    prev = _prev_month(bill_month)
    rooms = db.query(Room).filter(Room.is_active == True).order_by(Room.floor, Room.room_number).all()

    current_bills = {
        b.room_id: b
        for b in db.query(UtilityBill).filter(UtilityBill.bill_month == bill_month).all()
    }
    prev_bills = {
        b.room_id: b
        for b in db.query(UtilityBill).filter(UtilityBill.bill_month == prev).all()
    }

    rows = []
    for room in rooms:
        cur = current_bills.get(room.id)
        prv = prev_bills.get(room.id)
        tenant = room.current_tenant
        active_contracts = [c for c in room.contracts if c.is_active]
        contract = active_contracts[0] if active_contracts else None

        rows.append({
            "room": room,
            "tenant": tenant,
            "bill": cur,
            "monthly_rent": contract.monthly_rent if contract else 0.0,
            "contract_id": contract.id if contract else None,
            "water_prev": (cur.water_previous_reading if cur else (prv.water_current_reading if prv else 0.0)),
            "water_cur": cur.water_current_reading if cur else None,
            "water_usage": cur.water_usage if cur and cur.status != "draft" else None,
            "water_fee": cur.water_fee if cur and cur.status != "draft" else None,
            "elec_prev": (cur.electricity_previous_reading if cur else (prv.electricity_current_reading if prv else 0.0)),
            "elec_cur": cur.electricity_current_reading if cur else None,
            "elec_usage": cur.electricity_usage if cur and cur.status != "draft" else None,
            "elec_fee": cur.electricity_fee if cur and cur.status != "draft" else None,
            "total": cur.total_amount if cur and cur.status != "draft" else None,
        })
    return rows


@router.get("")
async def worksheet_page(request: Request, month: str = None):
    """账单工作表"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    if not month:
        today = date.today()
        month = f"{today.year}-{today.month:02d}"

    rows = _build_worksheet(db, month)

    # 汇总
    totals = {"water": 0.0, "elec": 0.0, "rent": 0.0, "grand": 0.0}
    for row in rows:
        if row["water_fee"] is not None:
            totals["water"] += row["water_fee"]
        if row["elec_fee"] is not None:
            totals["elec"] += row["elec_fee"]
        totals["rent"] += row["monthly_rent"]
        if row["total"] is not None:
            totals["grand"] += row["total"]

    return templates.TemplateResponse("billing/worksheet.html", {
        "request": request,
        "active_page": "billing",
        "month": month,
        "prev_month": _prev_month(month),
        "rows": rows,
        "totals": totals,
        "water_unit_price": WATER_UNIT_PRICE,
        "elec_unit_price": ELEC_UNIT_PRICE,
    })


@router.post("/save")
async def save_readings(
    request: Request,
    month: str = Form(...),
    db: Session = Depends(get_db),
):
    """保存读数（接收 form 表单批量提交）"""
    if r := check_auth(request): return r

    form = await request.form()
    prev_month = _prev_month(month)

    for key in form:
        # key 格式: water_3 或 elec_3 (room_id)
        if key.startswith("water_"):
            room_id = int(key.replace("water_", ""))
            val = float(form[key])
        elif key.startswith("elec_"):
            room_id = int(key.replace("elec_", ""))
            val = float(form[key])
        else:
            continue

        # 继续处理电表读数时才创建/更新账单
        if not key.startswith("elec_"):
            continue

        water_val_str = form.get(f"water_{room_id}")
        water_val = float(water_val_str) if water_val_str else None
        elec_val = val

        if water_val is None and elec_val is None:
            continue

        bill = db.query(UtilityBill).filter(
            UtilityBill.room_id == room_id,
            UtilityBill.bill_month == month,
        ).first()

        if bill is None:
            bill = UtilityBill(room_id=room_id, bill_month=month)
            db.add(bill)

        # 上月读数
        prev_bill = db.query(UtilityBill).filter(
            UtilityBill.room_id == room_id,
            UtilityBill.bill_month == prev_month,
        ).first()

        bill.water_previous_reading = prev_bill.water_current_reading if prev_bill else 0.0
        bill.electricity_previous_reading = prev_bill.electricity_current_reading if prev_bill else 0.0
        bill.water_unit_price = WATER_UNIT_PRICE
        bill.electricity_unit_price = ELEC_UNIT_PRICE

        if water_val is not None:
            bill.water_current_reading = water_val
        if elec_val is not None:
            bill.electricity_current_reading = elec_val

        # 房租
        contract = db.query(Contract).filter(
            Contract.room_id == room_id, Contract.is_active == True
        ).order_by(Contract.created_at.desc()).first()
        bill.monthly_rent = contract.monthly_rent if contract else 0.0

        _calc_bill(bill)
        db.flush()

    db.commit()
    return RedirectResponse(f"/billing?month={month}", status_code=303)


@router.post("/calculate")
async def recalculate_all(
    request: Request,
    month: str = Form(...),
    db: Session = Depends(get_db),
):
    """重算指定月份全部账单"""
    if r := check_auth(request): return r

    bills = db.query(UtilityBill).filter(UtilityBill.bill_month == month).all()
    for b in bills:
        _calc_bill(b)
    db.commit()

    return RedirectResponse(f"/billing?month={month}", status_code=303)


@router.get("/{bill_id}")
async def bill_detail(request: Request, bill_id: int):
    """账单详情"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    bill = db.query(UtilityBill).options(
        joinedload(UtilityBill.room),
    ).filter(UtilityBill.id == bill_id).first()

    if not bill:
        return RedirectResponse("/billing", status_code=303)

    # 生成分享文本
    room = bill.room
    tenant = room.current_tenant if room else None
    year, month = bill.bill_month[:4], bill.bill_month[5:7]
    share_text = "\n".join([
        f"【{year}年{int(month)}月 水电房租账单】",
        f"房间：{room.full_room_code if room else '-'}  租客：{tenant.name if tenant else '-'}",
        "-------------------------------",
        f"水费：¥{bill.water_fee:.2f} (上月{bill.water_previous_reading}→本月{bill.water_current_reading}，用量{bill.water_usage}方×{bill.water_unit_price}元)",
        f"电费：¥{bill.electricity_fee:.2f} (上月{bill.electricity_previous_reading}→本月{bill.electricity_current_reading}，用电{bill.electricity_usage}度×{bill.electricity_unit_price}元)",
        f"房租：¥{bill.monthly_rent:.2f}",
        "-------------------------------",
        f"合计：¥{bill.total_amount:.2f}",
    ])

    return templates.TemplateResponse("billing/detail.html", {
        "request": request,
        "active_page": "billing",
        "bill": bill,
        "share_text": share_text,
    })


@router.get("/{bill_id}/delete")
async def delete_bill(request: Request, bill_id: int):
    """删除账单"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    bill = db.query(UtilityBill).filter(UtilityBill.id == bill_id).first()
    month = bill.bill_month if bill else None
    if bill:
        db.delete(bill)
        db.commit()

    redirect = f"/billing?month={month}" if month else "/billing"
    return RedirectResponse(redirect, status_code=303)
