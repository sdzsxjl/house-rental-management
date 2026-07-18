"""房间、租客、合同模型"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, Text, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


class Room(Base):
    """房间"""
    __tablename__ = "room"

    id = Column(Integer, primary_key=True, autoincrement=True)
    floor = Column(Integer, nullable=False)
    room_number = Column(String(10), nullable=False)
    area_sqm = Column(Float)
    layout = Column(String(20), default="单间")  # 单间/一室一厅/两室一厅
    notes = Column(Text)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("floor", "room_number", name="uq_room_floor_number"),
    )

    contracts = relationship("Contract", back_populates="room")
    utility_bills = relationship("UtilityBill", back_populates="room")

    @property
    def full_room_code(self) -> str:
        """如 3-501"""
        return f"{self.floor}-{self.room_number}"

    @property
    def current_tenant(self):
        """当前在住租客"""
        active = [c for c in self.contracts if c.is_active]
        return active[0].tenant if active else None

    def __repr__(self):
        return f"<Room {self.floor}-{self.room_number}>"


class Tenant(Base):
    """租客"""
    __tablename__ = "tenant"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    phone = Column(String(20), nullable=False, unique=True)
    wechat_id = Column(String(50))
    id_card_number = Column(String(18))
    emergency_contact = Column(String(20))
    emergency_name = Column(String(50))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(Date, default=datetime.now)
    updated_at = Column(Date, default=datetime.now, onupdate=datetime.now)

    contracts = relationship("Contract", back_populates="tenant")
    payments = relationship("Payment", back_populates="tenant")
    reminders = relationship("ReminderLog", back_populates="tenant")

    @property
    def current_contract(self):
        """当前有效合同"""
        for c in self.contracts:
            if c.is_active:
                return c
        return None

    @property
    def current_room(self):
        """当前住的房间"""
        c = self.current_contract
        return c.room if c else None

    def __repr__(self):
        return f"<Tenant {self.name}>"


class Contract(Base):
    """租赁合同"""
    __tablename__ = "contract"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("room.id"), nullable=False)
    monthly_rent = Column(Float, nullable=False)
    deposit = Column(Float, nullable=False)
    payment_due_day = Column(Integer, nullable=False, default=1)
    contract_start_date = Column(Date, nullable=False)
    contract_end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True)
    contract_photo_path = Column(String(500))
    raw_ocr_text = Column(Text)
    created_at = Column(Date, default=datetime.now)
    updated_at = Column(Date, default=datetime.now, onupdate=datetime.now)

    tenant = relationship("Tenant", back_populates="contracts")
    room = relationship("Room", back_populates="contracts")
    payments = relationship("Payment", back_populates="contract")

    def __repr__(self):
        return f"<Contract {self.tenant.name} - {self.room.full_room_code}>"
