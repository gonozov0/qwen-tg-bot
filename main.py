from __future__ import annotations

import asyncio
import os
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
PWD = Path.cwd()
QWEN_WORK_DIR = Path("tmp/qwen")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# tg_user_id -> qwen session_id
sessions: dict[int, str] = {}

# Все известные session_id (существовавшие при старте + созданные ботом)
known_session_ids: set[str] = set()

# Однопоточность: только один qwen-процесс одновременно
qwen_lock = asyncio.Lock()


def get_chats_dir() -> Path:
    """Вычисляет путь к директории чатов qwen на основе QWEN_WORK_DIR.

    qwen хранит чаты в ~/.qwen/projects/{encoded-cwd}/chats/
    где encoded-cwd — это CWD с заменой / на -
    Пример: /home/user/workspace -> -home-user-workspace
    """
    full_path = PWD / QWEN_WORK_DIR
    encoded = str(full_path).replace("/", "-")
    return Path.home() / ".qwen" / "projects" / encoded / "chats"


def list_session_ids() -> set[str]:
    """Возвращает множество ID всех существующих сессий."""
    chats_dir = get_chats_dir()
    if not chats_dir.exists():
        return set()
    return {f.stem for f in chats_dir.glob("*.jsonl")}


async def run_qwen(prompt: str, session_id: str | None = None) -> str:
    """Запускает qwen в headless-режиме и возвращает stdout."""
    cmd = ["qwen"]
    if session_id:
        cmd.append(f"--resume={session_id}")
    cmd.extend(["-p", f"\"{prompt}\""])

    logger.info(f"Running: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(QWEN_WORK_DIR),
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"qwen stderr: {stderr.decode()}")
        return f"Error (exit code {proc.returncode}):\n{stderr.decode()[:1000]}"

    return stdout.decode().strip()


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
        if user_id in sessions:
            # Продолжаем существующую сессию
            response = await run_qwen(message.text, sessions[user_id])
        else:
            # Новая сессия: ищем разницу с известными сессиями
            response = await run_qwen(message.text)
            new_ids = list_session_ids() - known_session_ids
            logger.info(f"new ids: {new_ids}")
            if new_ids:
                session_id = new_ids.pop()
                sessions[user_id] = session_id
                known_session_ids.update(new_ids | {session_id})
                logger.info(f"New session for user {user_id}: {session_id}")
            else:
                logger.warning(f"Could not detect new session for user {user_id}")

    # Telegram ограничивает сообщения 4096 символами
    if len(response) <= 4096:
        await wait_msg.edit_text(response or "(пустой ответ)")
    else:
        await wait_msg.edit_text(response[:4096])
        # Отправляем остаток частями
        for i in range(4096, len(response), 4096):
            await message.reply(response[i:i + 4096])


async def main():
    QWEN_WORK_DIR.mkdir(parents=True, exist_ok=True)
    known_session_ids.update(list_session_ids())
    logger.info(f"Qwen work dir: {QWEN_WORK_DIR}")
    logger.info(f"Qwen chats dir: {get_chats_dir()}")
    logger.info(f"Known sessions at startup: {known_session_ids}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
