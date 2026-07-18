"""AI 合同照片解析服务"""
import json
import base64
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from app.config import settings


class ContractData(BaseModel):
    """AI 解析返回的合同数据"""
    tenant_name: str = ""
    phone: str = ""
    room_number: str = ""  # 如 "3-501"
    monthly_rent: float = 0
    deposit: float = 0
    payment_due_day: int = 1
    contract_start: str = ""  # "2026-01-01"
    contract_end: str = ""    # "2026-12-31"
    id_card: str = ""


def parse_contract_photo(image_path: str) -> Optional[ContractData]:
    """
    上传合同照片 → AI 提取结构化数据
    """
    if not settings.llm_enabled:
        return None

    from openai import OpenAI

    # 读取图片并转 base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    ext = Path(image_path).suffix.lower()
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")

    prompt = """请从这份中文房屋租赁合同中提取以下信息，以 JSON 格式返回：

{
    "tenant_name": "租客姓名",
    "phone": "租客手机号码",
    "room_number": "房间号（如3-501）",
    "monthly_rent": 月租金数字,
    "deposit": 押金数字,
    "payment_due_day": 每月缴费日数字,
    "contract_start": "合同开始日期(YYYY-MM-DD)",
    "contract_end": "合同结束日期(YYYY-MM-DD)",
    "id_card": "身份证号"
}

注意：
- 如果某个字段找不到，留空字符串或0
- 数字字段不要加单位
- 只返回JSON，不要其他文字
- 日期格式必须是 YYYY-MM-DD"""

    try:
        client = OpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
        )
        resp = client.chat.completions.create(
            model=settings.LLM_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                ],
            }],
            max_tokens=800,
            temperature=0.1,
        )
        text = resp.choices[0].message.content.strip()

        # 提取 JSON
        if "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        data = json.loads(text)
        return ContractData(**data)

    except Exception as e:
        print(f"合同解析失败: {e}")
        return None
