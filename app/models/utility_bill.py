"""水电账单模型"""
from datetime import date
from sqlalchemy import (
    Column, Integer, Float, String, Date, Text, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


class UtilityBill(Base):
    """水电账单 — 每房间每月一条记录"""
    __tablename__ = "utility_bill"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("room.id"), nullable=False)
    bill_month = Column(String(7), nullable=False)  # "2026-07"

    # 水表
    water_previous_reading = Column(Float, default=0.0)
    water_current_reading = Column(Float, default=0.0)
    water_usage = Column(Float, default=0.0)
    water_unit_price = Column(Float, default=6.0)
    water_fee = Column(Float, default=0.0)
    water_photo_path = Column(String(500))

    # 电表
    electricity_previous_reading = Column(Float, default=0.0)
    electricity_current_reading = Column(Float, default=0.0)
    electricity_usage = Column(Float, default=0.0)
    electricity_unit_price = Column(Float, default=1.0)
    electricity_fee = Column(Float, default=0.0)
    electricity_photo_path = Column(String(500))

    # 房租 + 总额
    monthly_rent = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)

    status = Column(String(20), default="draft")  # draft / calculated / shared
    notes = Column(Text)
    created_at = Column(Date, default=date.today)
    updated_at = Column(Date, default=date.today, onupdate=date.today)

    __table_args__ = (
        UniqueConstraint("room_id", "bill_month", name="uq_bill_room_month"),
    )

    room = relationship("Room", back_populates="utility_bills")

    def __repr__(self):
        return f"<UtilityBill {self.room.full_room_code if self.room else '?'} {self.bill_month}>"
