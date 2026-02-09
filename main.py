from __future__ import annotations

import asyncio
import json
import os
import logging
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TG_BOT_TOKEN"]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# tg_user_id -> qwen session_id
sessions: dict[int, str] = {}

# Однопоточность: только один qwen-процесс одновременно
qwen_lock = asyncio.Lock()


@dataclass
class QwenResult:
    text: str
    session_id: str | None


def parse_qwen_json(raw: str) -> QwenResult:
    """Парсит JSON-вывод qwen (флаг -o=json) и извлекает текст ответа и session_id."""
    events = json.loads(raw)
    session_id = None
    result_text = ""
    for event in events:
        if event.get("session_id"):
            session_id = event["session_id"]
        if event.get("type") == "result":
            result_text = event.get("result", "")
    return QwenResult(text=result_text, session_id=session_id)


async def run_qwen(prompt: str, session_id: str | None = None) -> QwenResult:
    """Запускает qwen с -o=json и возвращает результат с session_id."""
    cmd = ["qwen", "-o=json"]
    if session_id:
        cmd.append(f"--resume={session_id}")
    cmd.extend(["-p", f"\"{prompt}\""])

    logger.info(f"Running: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"qwen stderr: {stderr.decode()}")
        return QwenResult(
            text=f"Error (exit code {proc.returncode}):\n{stderr.decode()[:1000]}",
            session_id=session_id,
        )

    try:
        return parse_qwen_json(stdout.decode())
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse qwen JSON output: {e}")
        return QwenResult(text=stdout.decode().strip(), session_id=session_id)


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if user_id in sessions:
        del sessions[user_id]
        logger.info(f"Session cleared for user {user_id}")
        await message.reply("Сессия сброшена. Следующее сообщение начнёт новый диалог.")
    else:
        await message.reply(
            "Привет! Я прокси к qwen code. Просто напиши сообщение и я передам его в qwen."
        )


@dp.message()
async def handle_message(message: types.Message):
    if not message.text:
        await message.reply("Поддерживаются только текстовые сообщения.")
        return

    user_id = message.from_user.id
    wait_msg = await message.reply("Думаю...")

    async with qwen_lock:
        result = await run_qwen(message.text, sessions.get(user_id))
        if result.session_id and user_id not in sessions:
            sessions[user_id] = result.session_id
            logger.info(f"New session for user {user_id}: {result.session_id}")

    response = result.text

    # Telegram ограничивает сообщения 4096 символами
    if len(response) <= 4096:
        await wait_msg.edit_text(response or "(пустой ответ)")
    else:
        await wait_msg.edit_text(response[:4096])
        for i in range(4096, len(response), 4096):
            await message.reply(response[i:i + 4096])


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
