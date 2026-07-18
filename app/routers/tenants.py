"""租客管理路由"""
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import Tenant, Room, Contract, Payment
from app.routers.auth import get_current_user

router = APIRouter(prefix="/tenants", tags=["租客管理"])
templates = Jinja2Templates(directory="app/templates")


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


@router.get("")
async def tenant_list(request: Request):
    """租客列表"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    tenants = db.query(Tenant).filter(Tenant.is_active == True).order_by(Tenant.name).all()
    rooms = db.query(Room).filter(Room.is_active == True).order_by(Room.floor, Room.room_number).all()

    return templates.TemplateResponse("tenants/list.html", {
        "request": request,
        "active_page": "tenants",
        "tenants": tenants,
        "rooms": rooms,
    })


@router.get("/{tenant_id}")
async def tenant_detail(request: Request, tenant_id: int):
    """租客详情"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    tenant = db.query(Tenant).options(
        joinedload(Tenant.contracts).joinedload(Contract.room),
        joinedload(Tenant.payments),
    ).filter(Tenant.id == tenant_id).first()

    if not tenant:
        return templates.TemplateResponse("tenants/list.html", {
            "request": request, "error": "租客不存在"
        })

    return templates.TemplateResponse("tenants/detail.html", {
        "request": request,
        "active_page": "tenants",
        "tenant": tenant,
    })


@router.post("/add")
async def add_tenant(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    wechat_id: str = Form(""),
    floor: int = Form(...),
    room_number: str = Form(...),
    monthly_rent: float = Form(...),
    deposit: float = Form(0),
    payment_due_day: int = Form(1),
    contract_start: str = Form(...),
    contract_end: str = Form(...),
    db: Session = Depends(get_db),
):
    """添加租客（同时创建合同关联房间）"""
    if r := check_auth(request): return r

    from datetime import datetime

    # 查找或创建房间
    room = db.query(Room).filter(
        Room.floor == floor, Room.room_number == room_number
    ).first()
    if not room:
        room = Room(floor=floor, room_number=room_number)
        db.add(room)
        db.flush()

    # 创建租客
    tenant = Tenant(
        name=name,
        phone=phone,
        wechat_id=wechat_id,
    )
    db.add(tenant)
    db.flush()

    # 创建合同
    contract = Contract(
        tenant_id=tenant.id,
        room_id=room.id,
        monthly_rent=monthly_rent,
        deposit=deposit,
        payment_due_day=payment_due_day,
        contract_start_date=datetime.strptime(contract_start, "%Y-%m-%d").date(),
        contract_end_date=datetime.strptime(contract_end, "%Y-%m-%d").date(),
    )
    db.add(contract)
    db.commit()

    return RedirectResponse("/tenants", status_code=303)


@router.post("/{tenant_id}/edit")
async def edit_tenant(
    request: Request,
    tenant_id: int,
    name: str = Form(...),
    phone: str = Form(...),
    wechat_id: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """编辑租客信息"""
    if r := check_auth(request): return r

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant:
        tenant.name = name
        tenant.phone = phone
        tenant.wechat_id = wechat_id
        tenant.notes = notes
        db.commit()

    return RedirectResponse(f"/tenants/{tenant_id}", status_code=303)


@router.get("/{tenant_id}/delete")
async def delete_tenant(request: Request, tenant_id: int):
    """删除租客（软删除）"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant:
        tenant.is_active = False
        # 同时停用合同
        for contract in tenant.contracts:
            if contract.is_active:
                contract.is_active = False
        db.commit()

    return RedirectResponse("/tenants", status_code=303)
