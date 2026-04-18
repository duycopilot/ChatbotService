"""
Purpose: Action agent 
- Nhắc nhở uống thuốc
- Ghi nhận chỉ số hằng ngày
"""
from services.chat.agents.context import AgentContext


async def handle(message: str, context: AgentContext) -> str:
    _ = (message, context)
    # TODO: implement action handling
    return ""
