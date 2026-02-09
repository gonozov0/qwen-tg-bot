include .env
export

REMOTE_HOST = 84.201.187.84
REMOTE_USER = gonozov0
SSH_KEY = ~/.ssh/vpn
REMOTE_DIR = ~/qwen-tg-bot
SSH_CMD = ssh -l $(REMOTE_USER) $(REMOTE_HOST) -i $(SSH_KEY)

run:
	uv run python main.py

deploy:
	rsync -avz --exclude '.venv/' --exclude '__pycache__/' --exclude '.idea/' --exclude '.git/' \
		-e "ssh -i $(SSH_KEY)" \
		. $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_DIR)/
	$(SSH_CMD) 'echo "TG_BOT_TOKEN=$(TG_BOT_TOKEN)" > $(REMOTE_DIR)/.env'
	$(SSH_CMD) 'cd $(REMOTE_DIR) && /home/$(REMOTE_USER)/.local/bin/uv sync'

setup-service:
	$(SSH_CMD) 'sudo cp $(REMOTE_DIR)/qwen-tg-bot.service /etc/systemd/system/qwen-tg-bot.service && sudo systemctl daemon-reload && sudo systemctl enable qwen-tg-bot'

restart:
	$(SSH_CMD) 'sudo systemctl restart qwen-tg-bot'

stop:
	$(SSH_CMD) 'sudo systemctl stop qwen-tg-bot'

logs:
	$(SSH_CMD) 'sudo journalctl -u qwen-tg-bot -f'

status:
	$(SSH_CMD) 'sudo systemctl status qwen-tg-bot'