"""用户模型"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Date
from app.database import Base


class User(Base):
    """系统用户（单用户：房东）"""
    __tablename__ = "user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(200), nullable=False)
    wechat_webhook = Column(String(500))
    email_smtp_config = Column(Text)
    created_at = Column(Date, default=datetime.now)

    def __repr__(self):
        return f"<User {self.username}>"
