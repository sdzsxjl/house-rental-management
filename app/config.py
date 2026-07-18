"""应用配置"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    """全局配置单例"""

    # 安全
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    # 数据库
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'rental.db'}"
    )

    # LLM / AI
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_API_BASE: str = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
    # 视觉模型：deepseek-chat 为纯文本模型、不支持图片输入，
    # 需使用多模态模型 deepseek-flash（旧名 deepseek-v4-flash-vision-exp）
    LLM_VISION_MODEL: str = os.getenv("LLM_VISION_MODEL", "deepseek-flash")

    # 催租规则（默认：每月1号为缴费日，1号提醒，4号警告，6号逾期）
    REMINDER_GENTLE_OFFSET: int = 0   # 缴费日当天
    REMINDER_WARNING_OFFSET: int = 3  # 缴费日+3天
    REMINDER_OVERDUE_OFFSET: int = 5  # 缴费日+5天

    # ─── 通知推送配置 ─────────────────────────────────────
    # 推送到房东的渠道：
    WECOM_WEBHOOK_URL: str = os.getenv("WECOM_WEBHOOK_URL", "")       # 企业微信群机器人
    SERVERCHAN_SEND_KEY: str = os.getenv("SERVERCHAN_SEND_KEY", "")   # Server酱
    PUSHPLUS_TOKEN: str = os.getenv("PUSHPLUS_TOKEN", "")             # PushPlus
    # 直接推送到租客的渠道 ⭐：
    SMS_SECRET_ID: str = os.getenv("SMS_SECRET_ID", "")               # 腾讯云 SecretId
    SMS_SECRET_KEY: str = os.getenv("SMS_SECRET_KEY", "")             # 腾讯云 SecretKey
    SMS_SDK_APP_ID: str = os.getenv("SMS_SDK_APP_ID", "")             # 腾讯云短信应用ID
    SMS_TEMPLATE_ID: str = os.getenv("SMS_TEMPLATE_ID", "")           # 短信模板ID
    SMS_SIGN_NAME: str = os.getenv("SMS_SIGN_NAME", "")               # 短信签名
    WECOM_CORP_ID: str = os.getenv("WECOM_CORP_ID", "")               # 企业微信企业ID
    WECOM_AGENT_SECRET: str = os.getenv("WECOM_AGENT_SECRET", "")     # 企业微信应用Secret
    WECOM_AGENT_ID: str = os.getenv("WECOM_AGENT_ID", "")             # 企业微信应用AgentId

    @property
    def any_landlord_notification_enabled(self) -> bool:
        """是否有通知房东的渠道"""
        return bool(self.WECOM_WEBHOOK_URL or self.SERVERCHAN_SEND_KEY or self.PUSHPLUS_TOKEN)

    @property
    def any_tenant_notification_enabled(self) -> bool:
        """是否有直接通知租客的渠道"""
        sms_ready = bool(self.SMS_SECRET_ID and self.SMS_SECRET_KEY and self.SMS_SDK_APP_ID)
        wecom_ready = bool(self.WECOM_CORP_ID and self.WECOM_AGENT_SECRET and self.WECOM_AGENT_ID)
        return sms_ready or wecom_ready

    @property
    def any_notification_enabled(self) -> bool:
        return self.any_landlord_notification_enabled or self.any_tenant_notification_enabled

    # 文件存储
    UPLOAD_DIR: Path = BASE_DIR / "data" / "uploads"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.LLM_API_KEY)


settings = Settings()

# 确保目录存在
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(BASE_DIR / "data").mkdir(exist_ok=True)
