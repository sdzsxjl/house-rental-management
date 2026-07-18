"""合同管理路由"""
import shutil
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request, Form, UploadFile, File, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import Contract, Tenant, Room
from app.routers.auth import get_current_user
from app.config import settings
from app.services.contract_parser import parse_contract_photo

router = APIRouter(prefix="/contracts", tags=["合同管理"])
templates = Jinja2Templates(directory="app/templates")


def check_auth(request: Request):
    if not get_current_user(request):
        return RedirectResponse("/login", status_code=303)
    return None


@router.get("")
async def contract_list(request: Request):
    """合同列表"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    contracts = db.query(Contract).order_by(
        Contract.is_active.desc(), Contract.contract_end_date.desc()
    ).limit(100).all()

    active_count = sum(1 for c in contracts if c.is_active)
    tenants = db.query(Tenant).filter(Tenant.is_active == True).order_by(Tenant.name).all()
    rooms = db.query(Room).filter(Room.is_active == True).order_by(Room.floor, Room.room_number).all()

    return templates.TemplateResponse("contracts/list.html", {
        "request": request,
        "active_page": "contracts",
        "contracts": contracts,
        "active_count": active_count,
        "tenants": tenants,
        "rooms": rooms,
        "llm_enabled": settings.llm_enabled,
    })


@router.post("/parse")
async def parse_contract(
    request: Request,
    file: UploadFile = File(...),
):
    """AI 解析合同照片"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    # 保存上传文件
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    save_path = settings.UPLOAD_DIR / f"contract_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # AI 解析
    contract_data = parse_contract_photo(str(save_path))

    # 获取房间下拉选项
    rooms = db.query(Room).filter(Room.is_active == True).order_by(Room.floor, Room.room_number).all()

    return templates.TemplateResponse("contracts/parse_result.html", {
        "request": request,
        "active_page": "contracts",
        "contract_data": contract_data,
        "rooms": rooms,
        "photo_path": str(save_path),
    })


@router.post("/create")
async def create_contract(
    request: Request,
    tenant_id: int = Form(...),
    room_id: int = Form(...),
    monthly_rent: float = Form(...),
    deposit: float = Form(0),
    payment_due_day: int = Form(1),
    contract_start: str = Form(...),
    contract_end: str = Form(...),
    db: Session = Depends(get_db),
):
    """创建/续签合同"""
    if r := check_auth(request): return r

    # 停用旧合同
    old_contracts = db.query(Contract).filter(
        Contract.tenant_id == tenant_id,
        Contract.is_active == True,
    ).all()
    for c in old_contracts:
        c.is_active = False

    contract = Contract(
        tenant_id=tenant_id,
        room_id=room_id,
        monthly_rent=monthly_rent,
        deposit=deposit,
        payment_due_day=payment_due_day,
        contract_start_date=datetime.strptime(contract_start, "%Y-%m-%d").date(),
        contract_end_date=datetime.strptime(contract_end, "%Y-%m-%d").date(),
    )
    db.add(contract)
    db.commit()

    return RedirectResponse("/contracts", status_code=303)


@router.get("/{contract_id}/terminate")
async def terminate_contract(request: Request, contract_id: int):
    """终止合同"""
    if r := check_auth(request): return r
    db: Session = next(get_db())

    contract = db.query(Contract).filter(Contract.id == contract_id).first()
    if contract:
        contract.is_active = False
        db.commit()

    return RedirectResponse("/contracts", status_code=303)
