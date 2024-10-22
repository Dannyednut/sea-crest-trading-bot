
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes,ConversationHandler
import asyncio

# config.py
import json
from typing import Dict, Any

class Config:
    def __init__(self, config: Dict[str, Any]):
        self.api_key = config['api_key']
        self.api_secret = config['api_secret']
        self.coins = config['coins']
        self.max_amount = config['max_amount']
        self.min_spread = config['min_spread']
        self.stop_loss = config['stop_loss']
        self.duration = config['duration']

# api_client.py
from typing import Dict, Any
import pybit.unified_trading
import requests

class APIClient:
    def __init__(self, api_key: str, api_secret: str):
        self.session = pybit.unified_trading.HTTP(
            demo=True,
            api_key=api_key,
            api_secret=api_secret
        )
        self.session.url = 'https://demo-api.bybit.com'

    def get_wallet_balance(self, coin: str) -> float:
        try:
            response = self.session.get_wallet_balance(accountType='UNIFIED')
            coins = response['result']['list'][0]['coin']
            balance = next((float(i['equity']) for i in coins if i['coin'] == coin), None)
            if balance is None:
                raise ValueError(f"Balance not found for {coin}")
            return balance
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            raise APIError(f"Failed to get wallet balance: {str(e)}")

    def get_ticker_price(self, symbol: str) -> float:
        try:
            response = self.session.get_tickers(category='spot')
            ticker = next((i for i in response['result']['list'] if i['symbol'] == symbol), None)
            if ticker is None:
                raise ValueError(f"Ticker not found for {symbol}")
            return float(ticker['lastPrice'])
        except (requests.exceptions.RequestException, KeyError, IndexError) as e:
            raise APIError(f"Failed to get ticker price: {str(e)}")

    def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: float = None) -> Dict[str, Any]:
        try:
            params = {
                'category': 'spot',
                'symbol': symbol,
                'side': side,
                'orderType': order_type,
                'qty': str(qty),
            }
            if price:
                params['price'] = str(price)
            response = self.session.place_order(**params)
            if response['retMsg'] != 'OK':
                raise ValueError(f"Order placement failed: {response['retMsg']}")
            return response['result']
        except (requests.exceptions.RequestException, KeyError) as e:
            raise APIError(f"Failed to place order: {str(e)}")

    def get_open_order(self,pair: str):
        res = self.session.get_open_orders(category = 'spot',symbol = pair)
        res = res['result']['list']
        if res:
            print(res[0]['orderStatus'])
            print(res[0]['orderId'])
            return res[0]
        else:
            return 0

    def cancel_order(self,symbol, id):
        self.session.cancel_order(
            category="spot",
            symbol=symbol,
            orderId= id,
        )
    def get_lot_size(self,pair: str) -> float:
        all=(self.session.get_instruments_info(category='spot'))['result']['list']
        for i in all:
            if i['symbol'] == pair:
                return float(i['lotSizeFilter']['basePrecision'])

# arbitrage.py
import time
from datetime import datetime, timedelta
from typing import Tuple
import math

class Arbitrage:
    def __init__(self, config: Config, api_client: APIClient):
        self.config = config
        self.api_client = api_client
        self.active = True

    def execute_trade(self, coin: str) -> float:
        usdt_pair = f'{coin}USDT'
        usdc_pair = f'{coin}USDC'
        usdt_price = self.api_client.get_ticker_price(usdt_pair)
        usdc_price = self.api_client.get_ticker_price(usdc_pair)
        initial_usdcusdt = self.api_client.get_ticker_price('USDCUSDT')

        if usdt_price < usdc_price:
            return self._trade_usdt_lower(coin, usdt_pair, usdc_pair, usdt_price, usdc_price, initial_usdcusdt)
        elif usdc_price < usdt_price:
            return self._trade_usdc_lower(coin, usdt_pair, usdc_pair, usdt_price, usdc_price, initial_usdcusdt)
        else:
            return 0

    @staticmethod
    def reverse(inverse: float):
        """
        Takes in a decimal inverse (e.g. 0.001) and returns its whole number inverse equivalent (e.g. 1000)
        """
        inverse_str = str(inverse).replace('.', '')  # convert the decimal inverse to a string and remove the decimal point
        whole_num = int(inverse_str[::-1])  # reverse the digits and convert to an integer
        return whole_num


    def truncate(self,maxval: float, lot: float =0.01):
        decimal = self.reverse(lot)
        max_val = float(maxval)
        return math.trunc(max_val * decimal) / decimal

    def _trade_usdt_lower(self, coin: str, usdt_pair: str, usdc_pair: str, usdt_price: float, usdc_price: float, initial_usdcusdt: float) -> float:
        spread = usdc_price - usdt_price
        if spread <= self.config.min_spread:
            return 0

        usdt_balance = self.api_client.get_wallet_balance('USDT')
        trade_amount = min(self.config.max_amount, usdt_balance / usdt_price)
        qty = self.truncate(trade_amount)

        # Buy the coin with USDT
        self.api_client.place_order(usdt_pair, 'Buy', 'Market', qty)

        # Get the bought amount
        coin_balance = self.api_client.get_wallet_balance(coin)
        coin_lot = self.api_client.get_lot_size(usdc_pair)
        coin_balance = self.truncate(coin_balance,coin_lot)

        # Sell the bought coin to USDC
        sell_order = self._place_sell_order(usdc_pair, coin_balance, usdc_price)

        # Convert USDC back to USDT
        usdc_balance = self.truncate(self.api_client.get_wallet_balance('USDC'))
        self._convert_usdc_to_usdt(usdc_balance, initial_usdcusdt)

        return self._calculate_profit('USDT')

    def _trade_usdc_lower(self, coin: str, usdt_pair: str, usdc_pair: str, usdt_price: float, usdc_price: float, initial_usdcusdt: float) -> float:
        spread = usdt_price - usdc_price
        if spread <= self.config.min_spread:
            return 0

        usdt_balance = self.api_client.get_wallet_balance('USDT')
        trade_amount = min(self.config.max_amount, usdt_balance / usdt_price)
        qty = self.truncate(trade_amount)

        # Buy USDC with USDT
        self.api_client.place_order('USDCUSDT', 'Buy', 'Market', qty)

        usdc_balance = self.truncate(self.api_client.get_wallet_balance('USDC'))

        # Buy the coin with USDC
        self.api_client.place_order(usdc_pair, 'Buy', 'Market', usdc_balance)

        # Get the bought amount
        coin_balance = self.truncate(self.api_client.get_wallet_balance(coin))

        # Sell the bought coin to USDT
        sell_order = self._place_sell_order(usdt_pair, coin_balance, usdt_price)

        return self._calculate_profit('USDT')


    def _place_sell_order(self, pair: str, amount: float, price: float) -> dict:
        position = self.api_client.place_order(pair, 'Sell', 'Limit', amount, price)

        for _ in range(20):  # Wait for up to 20 seconds
            order = self.api_client.get_open_order(pair)
            if not order:
                return position

            current_price = self.api_client.get_ticker_price(pair)
            if current_price < price:
                self.api_client.cancel_order(pair, order['orderId'])
                return self.api_client.place_order(pair, 'Sell', 'Market', amount)

            time.sleep(1)

        # If the order hasn't filled after 20 seconds, cancel and market sell
        self.api_client.cancel_order(pair, order['orderId'])
        return self.api_client.place_order(pair, 'Sell', 'Market', amount)

    def _convert_usdc_to_usdt(self, usdc_amount: float, initial_usdcusdt: float):
        for _ in range(30):  # Try for up to 30 seconds
            usdc_price = self.api_client.get_ticker_price('USDCUSDT')
            if usdc_price >= initial_usdcusdt or usdc_price == (initial_usdcusdt - 0.0001):
                convert_order = self.api_client.place_order('USDCUSDT', 'Sell', 'Limit', usdc_amount, '1.00')

                for _ in range(5):  # Wait for up to 5 seconds
                    if not self.api_client.get_open_order('USDCUSDT'):
                        return
                    time.sleep(1)

                # If the order hasn't filled after 5 seconds, cancel and market sell
                self.api_client.cancel_order('USDCUSDT', convert_order['orderId'])
                self.api_client.place_order('USDCUSDT', 'Sell', 'Market', usdc_amount)
                return

            time.sleep(1)

        # If we couldn't convert at a good price after 30 seconds, market sell
        self.api_client.place_order('USDCUSDT', 'Sell', 'Market', usdc_amount)

    def _calculate_profit(self, base_currency: str) -> float:
        current_balance = self.api_client.get_wallet_balance(base_currency)
        profit = current_balance - self.api_client.get_wallet_balance('USDT')
        return profit

    def run(self):
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=self.config.duration)
        self.initial_balance = self.api_client.get_wallet_balance('USDT')

        while self.active and datetime.now() < end_time:
            if not self.active:
                break
            for coin in self.config.coins:
                if not self.active:
                    break
                try:
                    profit = self.execute_trade(coin)
                    print(f'{coin} profit = {profit}')

                    total_profit = self._calculate_profit('USDT')
                    if total_profit < 0 and abs(total_profit) >= self.config.stop_loss:
                        print("Stop loss reached")
                        self.active = False
                        break

                except Exception as e:
                    print(f"Error occurred: {str(e)}")
                    print("Check your trading account for active trade and complete manually")
                    self.active = False
                    break

            if self.active:
                print('Sleeping for 5 seconds')
                for _ in range(5):
                    if not self.active:
                        break
                    time.sleep(1)

        total_time = datetime.now() - start_time
        total_profit = self._calculate_profit('USDT')
        minutes, seconds = divmod(total_time.seconds, 60)
        print(f'Traded for {minutes} minutes and {seconds} seconds')
        print(f'Total profit: ${total_profit}')

    def stop(self):
        self.active = False
        return "Stopped"

# exceptions.py
class APIError(Exception):
    """Custom exception for API-related errors."""
    pass


import threading
# main.py
class ArbitrageWrapper:
    def __init__(self, config: Config):
        self.config = config
        self.api_client = APIClient(config.api_key, config.api_secret)
        self.arbitrage = Arbitrage(config, self.api_client)

    def start(self):
        try:
            thread = threading.Thread(target=self.arbitrage.run)
            thread.start()

            if self.arbitrage.active == False:
                self.arbitrage.stop()

            thread.join()
            return "Trading completed", self.get_profit()
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            print("Arbitrage bot stopped.")


    def stop(self):
        return self.arbitrage.stop()

    def get_profit(self):
        return self.arbitrage._calculate_profit('USDT')

class TelegramInterface:
    def __init__(self, token: str):
        self.application = Application.builder().token(token).build()
        self.arbitrage_wrapper = None
        self.token = token
        # Define conversation states
        self.APIKEY, self.APISECRET, self.COINS, self.AMOUNT, self.STOPLOSS, self.SPREAD, self.DURATION = range(7)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Welcome to the Arbitrage Bot! Use /set_config to set your configuration.')

    async def set_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Please enter your API key:')
        return self.APIKEY

    async def get_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['api_key'] = update.message.text
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await update.message.reply_text('API key saved. Now enter your API secret:')
        return self.APISECRET

    async def get_api_secret(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['api_secret'] = update.message.text
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await update.message.reply_text('API secret saved. Now enter the coins to trade (comma-separated):')
        return self.COINS

    async def get_coins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['coins'] = update.message.text.split(',')
        await update.message.reply_text('Coins saved. Configuration complete. Use /start_bot to begin trading.')
        return ConversationHandler.END

    async def request_trade_params(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Enter the maximum trade amount:')
        return self.AMOUNT

    async def get_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['max_amount'] = float(update.message.text)
        await update.message.reply_text('Enter the stop loss amount:')
        return self.STOPLOSS

    async def get_stoploss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['stop_loss'] = float(update.message.text)
        await update.message.reply_text('Enter the minimum spread:')
        return self.SPREAD

    async def get_spread(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['min_spread'] = float(update.message.text)
        await update.message.reply_text('Enter the trading duration in minutes:')
        return self.DURATION

    async def get_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['duration'] = int(update.message.text)
        await self.start_bot(update, context)
        return ConversationHandler.END

    async def start_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        config_data = {
            'api_key': context.user_data.get('api_key'),
            'api_secret': context.user_data.get('api_secret'),
            'coins': context.user_data.get('coins'),
            'max_amount': context.user_data.get('max_amount'),
            'stop_loss': context.user_data.get('stop_loss'),
            'min_spread': context.user_data.get('min_spread'),
            'duration': context.user_data.get('duration')
        }

        if all(config_data.values()):
            config = Config(config_data)
            self.arbitrage_wrapper = ArbitrageWrapper(config)
            context.job_queue.run_once(self.run_arbitrage, 0, chat_id=update.effective_chat.id)
            await update.message.reply_text('Arbitrage bot started. You will be notified when trading completes.')
        else:
            await update.message.reply_text('Some configuration data is missing. Please use /set_config to set up your configuration.')

    async def run_arbitrage(self, context: ContextTypes.DEFAULT_TYPE):
        if self.arbitrage_wrapper:
            status, profit = await asyncio.to_thread(self.arbitrage_wrapper.start)
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=f"{status}\nFinal profit: ${profit:.2f}" if profit is not None else status
            )
        else:
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text="Bot is not configured. Please use /set_config first."
            )

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.arbitrage_wrapper:
            try:
                result = await asyncio.to_thread(self.arbitrage_wrapper.stop)
                await update.message.reply_text(f'Arbitrage bot stopped. {result}')
            except Exception as e:

                await update.message.reply_text(f'Error stopping bot: {str(e)}')
            return
        else:
            await update.message.reply_text('Bot is not running.')
            return

    async def get_profit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.arbitrage_wrapper:
            profit = self.arbitrage_wrapper.get_profit()
            await update.message.reply_text(f'Current profit: ${profit:.2f}')
        else:
            await update.message.reply_text('Bot is not configured or running.')

    def run(self):
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("set_config", self.set_config),
                          CommandHandler("start_bot", self.request_trade_params)
            ],
            states={
                self.APIKEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_api_key)],
                self.APISECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_api_secret)],
                self.COINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_coins)],
                self.AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_amount)],
                self.STOPLOSS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_stoploss)],
                self.SPREAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_spread)],
                self.DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_duration)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(conv_handler)

        self.application.add_handler(CommandHandler("stop_bot", self.stop_bot))
        self.application.add_handler(CommandHandler("get_profit", self.get_profit))
        return self.application
    

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Configuration cancelled.')
        return ConversationHandler.END

import os
from dotenv import load_dotenv
def main():
    load_dotenv(dotenv_path='./config.env')
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    webhook_url = os.getenv('WEBHOOK_URL')
    telegram_interface = TelegramInterface(telegram_token)
    telegram_interface.run()
    telegram_interface.setup_webhook(webhook_url)

if __name__ == "__main__":
    main()
