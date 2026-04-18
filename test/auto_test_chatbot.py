#!/usr/bin/env python3
"""
Usage:
    python auto_test_chatbot.py
    python auto_test_chatbot.py --conversation-id <uuid>
    python auto_test_chatbot.py --chatbot-url http://host:8111 --vllm-url http://host:8380

Environment Variables:
    CHATBOT_URL   - Chatbot API base URL (default: http://localhost:8111)
    VLLM_URL      - vLLM server URL (default: http://localhost:8380)
"""

import argparse
import asyncio
import logging
import os
import signal
import json
import random
from datetime import datetime

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("auto_test")

SYSTEM_PROMPT = """\
Bạn là một bệnh nhân Việt Nam đang lo lắng về vấn đề tăng huyết áp. \
Nhiệm vụ của bạn là đặt câu hỏi cho bác sĩ/chatbot y tế.

Quy tắc:
- Chỉ trả về DUY NHẤT câu hỏi, không giải thích thêm gì.
- Câu hỏi phải tự nhiên, giống người thật hỏi (có thể dùng ngôn ngữ đời thường).
- Đa dạng chủ đề xoay quanh tăng huyết áp: triệu chứng, thuốc, chế độ ăn, tập thể dục, \
biến chứng, chỉ số huyết áp, khi nào cần đi khám, tương tác thuốc, stress, v.v.
- Nếu được cung cấp câu trả lời trước đó của chatbot, hãy hỏi tiếp theo ngữ cảnh đó \
(hỏi sâu hơn, hỏi liên quan, hoặc chuyển sang khía cạnh khác).
- Độ dài câu hỏi ngắn gọn, 1-3 câu.
"""

FIRST_QUESTION_PROMPT = """\
Hãy đặt một câu hỏi ngẫu nhiên về tăng huyết áp cho bác sĩ. \
Chỉ trả về câu hỏi, không giải thích."""

FOLLOWUP_PROMPT_TEMPLATE = """\
Câu hỏi trước đó của bạn:
"{previous_question}"

Chatbot đã trả lời:
"{chatbot_response}"

Dựa vào câu trả lời trên, hãy đặt một câu hỏi tiếp theo (hỏi sâu hơn, hoặc chuyển sang \
khía cạnh liên quan khác về tăng huyết áp). Chỉ trả về câu hỏi, không giải thích."""

PERSONAS = [
    "Bạn là người lớn tuổi 65, mới phát hiện tăng huyết áp.",
    "Bạn là nhân viên văn phòng 35 tuổi, hay stress, được bác sĩ cảnh báo huyết áp cao.",
    "Bạn là phụ nữ mang thai, lo lắng về tiền sản giật.",
    "Bạn là người đang uống thuốc huyết áp nhưng thấy tác dụng phụ.",
    "Bạn là người hay ăn mặn, uống rượu bia, muốn tìm hiểu về tăng huyết áp.",
    "Bạn là con cái đang lo cho bố mẹ bị tăng huyết áp.",
    "Bạn là bệnh nhân tiểu đường kèm tăng huyết áp.",
]

async def generate_question(
    client: httpx.AsyncClient,
    vllm_url: str,
    model: str,
    previous_question: str | None = None,
    chatbot_response: str | None = None,
) -> str:
    """Call vLLM to generate a patient question about hypertension."""

    persona = random.choice(PERSONAS)
    system = f"{SYSTEM_PROMPT}\n{persona}"

    if previous_question and chatbot_response:
        truncated = chatbot_response[:2000]
        user_msg = FOLLOWUP_PROMPT_TEMPLATE.format(
            previous_question=previous_question,
            chatbot_response=truncated,
        )
    else:
        user_msg = FIRST_QUESTION_PROMPT

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 256,
        "temperature": 0.9,
        "top_p": 0.95,
    }

    resp = await client.post(
        f"{vllm_url}/v1/chat/completions",
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    question = data["choices"][0]["message"]["content"].strip()
    question = question.strip('"').strip("'").strip()
    return question


async def send_to_chatbot(
    client: httpx.AsyncClient,
    chatbot_url: str,
    conversation_id: str,
    question: str,
) -> str:
    """Send a question to the chatbot API and return its response."""

    url = f"{chatbot_url}/api/v1/conversations/{conversation_id}/messages"
    payload = {"content": question}

    resp = await client.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict):
        if "content" in data:
            return data["content"]
        if "message" in data:
            msg = data["message"]
            if isinstance(msg, dict) and "content" in msg:
                return msg["content"]
            return str(msg)
        if "data" in data:
            inner = data["data"]
            if isinstance(inner, dict) and "content" in inner:
                return inner["content"]
            return str(inner)
        if "response" in data:
            return str(data["response"])

    return json.dumps(data, ensure_ascii=False)


async def run_loop(
    chatbot_url: str,
    vllm_url: str,
    model: str,
    conversation_id: str,
    delay: float,
    log_file: str | None,
    api_key: str = "dummy",
) -> None:
    """Main loop: generate question → send → get response → repeat."""

    stop_event = asyncio.Event()

    def _handle_signal():
        logger.info("Nhận tín hiệu dừng — kết thúc sau câu hỏi hiện tại...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    log_fh = None
    if log_file:
        log_fh = open(log_file, "a", encoding="utf-8")
        logger.info("Ghi log conversation vào %s", log_file)

    previous_question = None
    chatbot_response = None
    turn = 0

    headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async with httpx.AsyncClient(headers=headers) as client:
        logger.info("Bắt đầu auto-test. Ctrl+C để dừng.")
        logger.info("  Chatbot : %s", chatbot_url)
        logger.info("  vLLM    : %s (model: %s)", vllm_url, model)
        logger.info("  Conv ID : %s", conversation_id)
        logger.info("  Delay   : %.1fs giữa các lượt", delay)
        print("-" * 70)

        while not stop_event.is_set():
            turn += 1

            try:
                question = await generate_question(
                    client, vllm_url, model, previous_question, chatbot_response,
                )
            except Exception as exc:
                logger.error("[Turn %d] Lỗi sinh câu hỏi: %s", turn, exc)
                await asyncio.sleep(5)
                continue

            print(f"\n🤒 [Turn {turn}] Bệnh nhân hỏi:")
            print(f"   {question}")

            try:
                response = await send_to_chatbot(
                    client, chatbot_url, conversation_id, question,
                )
            except Exception as exc:
                logger.error("[Turn %d] Lỗi gọi chatbot: %s", turn, exc)
                await asyncio.sleep(5)
                continue

            print(f"\n💊 [Turn {turn}] Chatbot trả lời:")
            display = response[:1000] + ("..." if len(response) > 1000 else "")
            print(f"   {display}")
            print("-" * 70)

            if log_fh:
                entry = {
                    "turn": turn,
                    "timestamp": datetime.now().isoformat(),
                    "question": question,
                    "response": response,
                }
                log_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
                log_fh.flush()

            previous_question = question
            chatbot_response = response
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    if log_fh:
        log_fh.close()

    print(f"\nDừng sau {turn} lượt hỏi-đáp.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-test chatbot y tế bằng câu hỏi sinh từ LLM",
    )
    parser.add_argument(
        "--chatbot-url",
        type=str,
        default=os.getenv("CHATBOT_URL", "http://localhost:8111"),
        help="Chatbot API base URL (default: $CHATBOT_URL or http://localhost:8111)",
    )
    parser.add_argument(
        "--vllm-url",
        type=str,
        default=os.getenv("VLLM_URL", "http://localhost:8380"),
        help="vLLM server URL (default: $VLLM_URL or http://localhost:8380)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="cyankiwi/Qwen3-30B-A3B-Instruct-2507-AWQ-4bit",
        help="Model name trên vLLM (default: %(default)s)",
    )
    parser.add_argument(
        "--conversation-id",
        type=str,
        default="a7fcbb0e-ec81-486c-807d-e5315b26a9cc",
        help="Conversation ID để gửi messages (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("API_KEY", "dummy"),
        help="API key cho vLLM server (default: $API_KEY or 'dummy')",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Delay (giây) giữa các lượt hỏi (default: 3.0)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="File ghi log conversation (JSONL format). Ví dụ: test_log.jsonl",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await run_loop(
        chatbot_url=args.chatbot_url,
        vllm_url=args.vllm_url,
        model=args.model,
        conversation_id=args.conversation_id,
        delay=args.delay,
        log_file=args.log_file,
        api_key=args.api_key,
    )


if __name__ == "__main__":
    asyncio.run(main())
