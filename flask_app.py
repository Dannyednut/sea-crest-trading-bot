
from quart import Quart, request
from telegram import Update
import os
from dotenv import load_dotenv
from gram import TelegramInterface  # Assuming your script is named telegram_app.py
import asyncio

app = Quart(__name__)

load_dotenv(dotenv_path='./config.env')
telegram_token = os.getenv('TELEGRAM_TOKEN')
webhook_url = os.getenv('WEBHOOK_URL')

# Create the TelegramInterface instance
telegram_interface = TelegramInterface(telegram_token)

# Set up the application
@app.before_serving
async def startup():
    global telegram_interface
    application = telegram_interface.run()
    await application.initialize()
    await application.bot.set_webhook(url=f"{webhook_url}/{telegram_token}")

@app.route(f'/{telegram_token}', methods=['POST'])
async def webhook():
    update = Update.de_json(await request.get_json(force=True), telegram_interface.application.bot)
    await telegram_interface.application.process_update(update)
    return 'OK'

@app.route('/health')
async def health_check():
    return 'OK', 200

@app.route('/keep_alive')
def keep_alive():
    return 'Bot is active!'

@app.route('/')
def index():
    return 'Telegram Bot is running!'

if __name__ == '__main__':
    # Run the Quart app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
