
from quart import Quart, request
from telegram import Update
from telegram.ext import Application
import os
from dotenv import load_dotenv
from gram import TelegramInterface  # Assuming your script is named telegram_app.py

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
    telegram_interface = TelegramInterface(telegram_token)
    application = telegram_interface.run()
    await application.initialize()
    await telegram_interface.setup_webhook(webhook_url)

@app.route(f'/{telegram_token}', methods=['POST'])
async def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_interface.application.bot)
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
    # Set up webhook
    telegram_interface.setup_webhook(webhook_url)

    # Run the Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
