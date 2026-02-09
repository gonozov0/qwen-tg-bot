# Qwen Telegram Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Telegram-бот, проксирующий сообщения в qwen CLI (headless mode) с сохранением сессий per user.

**Architecture:** aiogram 3.x бот принимает сообщения, запускает `qwen -p "prompt" --yolo` через subprocess. Каждый TG user привязан к qwen session ID. Новые сессии детектятся по появлению новых .jsonl файлов в `~/.qwen/projects/.../chats/`. Однопоточная обработка через asyncio.Lock.

**Tech Stack:** Python 3.9+, aiogram 3.x, asyncio subprocess

---

### Task 1: Настройка проекта

**Files:**
- Modify: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`

**Step 1: Обновить pyproject.toml**

```toml
[project]
name = "qwen-tg-bot"
version = "0.1.0"
description = "Telegram bot proxying messages to qwen CLI"
requires-python = ">=3.9"
dependencies = [
    "aiogram>=3.0,<4.0",
    "python-dotenv>=1.0",
]
```

**Step 2: Создать .env.example**

```
TG_BOT_TOKEN=your-telegram-bot-token
QWEN_WORK_DIR=/home/user/qwen-workspace
```

**Step 3: Создать .gitignore**

```
.venv/
.env
__pycache__/
.idea/
```

**Step 4: Установить зависимости**

Run: `cd /Users/gonozov0/PycharmProjects/qwen-tg-bot && uv sync`

**Step 5: Commit**

```
git init && git add pyproject.toml .env.example .gitignore && git commit -m "init: project setup with aiogram"
```

---

### Task 2: Реализовать бота

**Files:**
- Rewrite: `main.py`

**Step 1: Написать main.py**

Единый файл со всей логикой:

```python
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
QWEN_WORK_DIR = Path(os.environ.get("QWEN_WORK_DIR", Path.home() / "qwen-workspace"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# tg_user_id -> qwen session_id
sessions: dict[int, str] = {}

# Однопоточность: только один qwen-процесс одновременно
qwen_lock = asyncio.Lock()


def get_chats_dir() -> Path:
    """Вычисляет путь к директории чатов qwen на основе QWEN_WORK_DIR.

    qwen хранит чаты в ~/.qwen/projects/{encoded-cwd}/chats/
    где encoded-cwd — это CWD с заменой / на -
    Пример: /home/user/workspace -> -home-user-workspace
    """
    encoded = str(QWEN_WORK_DIR).replace("/", "-")
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
    cmd.extend(["-p", prompt, "--yolo"])

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
            # Новая сессия: запоминаем файлы до запуска
            before = list_session_ids()
            response = await run_qwen(message.text)
            after = list_session_ids()
            new_ids = after - before
            if new_ids:
                session_id = new_ids.pop()
                sessions[user_id] = session_id
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
    logger.info(f"Qwen work dir: {QWEN_WORK_DIR}")
    logger.info(f"Qwen chats dir: {get_chats_dir()}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Протестировать локально**

1. Создать бота через @BotFather, получить токен
2. Создать `.env` из `.env.example`, заполнить `TG_BOT_TOKEN`
3. Run: `cd /Users/gonozov0/PycharmProjects/qwen-tg-bot && uv run python main.py`
4. Написать боту в Telegram, убедиться что ответ приходит
5. Написать второе сообщение — убедиться что сессия продолжается (qwen помнит контекст)

**Step 3: Commit**

```
git add main.py && git commit -m "feat: telegram bot proxying to qwen CLI"
```

---

### Task 3: Деплой на Yandex Cloud VM

**Step 1: Создать VM в Yandex Cloud**

- Консоль: https://console.yandex.cloud/
- Compute Cloud → Создать VM
- Ubuntu 22.04, минимум 2 vCPU / 4 GB RAM
- SSH-ключ для доступа

**Step 2: Настроить VM**

```bash
# На VM:
sudo apt update && sudo apt install -y curl git python3 python3-pip python3-venv

# Node.js 20+
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# qwen
npm install -g @qwen-code/qwen-code@latest

# Авторизация qwen (через API key)
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://..."  # если нужен кастомный endpoint

# Проект
git clone <repo-url> ~/qwen-tg-bot
cd ~/qwen-tg-bot
python3 -m venv .venv
source .venv/bin/activate
pip install aiogram python-dotenv

# .env
cp .env.example .env
nano .env  # заполнить TG_BOT_TOKEN, QWEN_WORK_DIR=/home/user/qwen-workspace
```

**Step 3: Создать systemd-сервис**

```bash
sudo tee /etc/systemd/system/qwen-tg-bot.service << 'EOF'
[Unit]
Description=Qwen Telegram Bot
After=network.target

[Service]
User=user
WorkingDirectory=/home/user/qwen-tg-bot
EnvironmentFile=/home/user/qwen-tg-bot/.env
ExecStart=/home/user/qwen-tg-bot/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable qwen-tg-bot
sudo systemctl start qwen-tg-bot
sudo systemctl status qwen-tg-bot
```

**Step 4: Проверить**

1. Написать боту в Telegram
2. Убедиться что ответ пришёл
3. `sudo journalctl -u qwen-tg-bot -f` — смотреть логи
