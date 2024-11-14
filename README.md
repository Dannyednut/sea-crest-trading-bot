# Sea Crest Trading Bot

## Overview
The Sea Crest Trading Bot is a Telegram-based arbitrage trading bot that allows users to automatically trade cryptocurrency pairs. It leverages price discrepancies between different trading pairs to execute profitable trades.

## Features
- **Automated Trading**: The bot can automatically execute trades based on user-defined parameters.
- **Configurable Settings**: Users can set their API keys, trading pairs, maximum trade amounts, stop-loss thresholds, minimum spreads, and trading durations.
- **Real-Time Notifications**: The bot sends updates to users about trading activities and profits.
- **Error Handling**: Built-in error handling to manage API-related issues and trading errors.

## Requirements
- Python 3.8 or higher
- Telegram Bot API Token
- Bybit API Key and Secret
- Required Python packages:
  - `python-telegram-bot`
  - `pybit`
  - `requests`
  - `dotenv`
  
## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/Dannyednut/sea-crest-trading-bot.git
   cd sea-crest-trading-bot

2. Install the required packages:
    ```bash
    pip install -r requirements.txt

3. Create a .env file in the root directory and add your Telegram token and webhook URL:
    TELEGRAM_TOKEN=your_telegram_token
    WEBHOOK_URL=your_webhook_url

4. Ensure that you have the Bybit API Key and Secret ready.

## Usage
1. Start the bot by running the main script:
    ```bash
    python main.py

2. Open your Telegram app and search for your bot. Start a chat with it

3. Use the command `/set_config` to configure your trading settings:
    • Enter your API key.
    • Enter your API secret.
    • Enter the coins you want to trade (comma-separated).
    • Enter the maximum amount for trades.
    • Set your stop-loss threshold.
    • Set the minimum spread for trades.
    • Set the trading duration in minutes.

4. After configuration, use the command `/start_bot` to begin trading.

5. You can check your current profit using the command `/get_profit` or stop the bot with `/stop_bot`.

## Lincense
This project is licensed under the MIT License. See the LICENSE file for details.

## Disclaimer
Trading cryptocurrencies involves risk. This bot is intended for educational purposes only. Use at your own risk.
