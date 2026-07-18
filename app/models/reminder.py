"""催租日志模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class ReminderLog(Base):
    """催租记录"""
    __tablename__ = "reminder_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=False)
    contract_id = Column(Integer, ForeignKey("contract.id"), nullable=False)
    reminder_type = Column(String(20), nullable=False)  # gentle/warning/overdue
    rent_month = Column(String(7), nullable=False)  # "2026-07"
    message_text = Column(Text, nullable=False)
    sent_via = Column(String(20), default="log")  # wechat/email/sms/log
    sent_at = Column(Date, default=datetime.now)
    response_status = Column(String(20), nullable=True)  # replied/paid/ignored

    tenant = relationship("Tenant", back_populates="reminders")

    def __repr__(self):
        return f"<Reminder {self.reminder_type} to {self.tenant.name} for {self.rent_month}>"
