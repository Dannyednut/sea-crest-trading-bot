
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
            api_key=api_key,
            api_secret=api_secret
        )
        self.session.url = 'https://api.bybit.com'

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
        try:
            if usdt_price < usdc_price:
                return self._trade_usdt_lower(coin, usdt_pair, usdc_pair, usdt_price, usdc_price, initial_usdcusdt)
            elif usdc_price < usdt_price:
                return self._trade_usdc_lower(coin, usdt_pair, usdc_pair, usdt_price, usdc_price, initial_usdcusdt)
            else:
                return 0
        except Exception as e:
            error_message = f"Arbitrage: Error executing trade for {coin}: {str(e)}"
            print(error_message)
            raise APIError()

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
        diff = usdc_price - usdt_price
        spread = (diff/usdt_price)*100
        if spread < self.config.min_spread:
            return 0

        usdt_balance = self.api_client.get_wallet_balance('USDT')
        trade_amount = min(self.config.max_amount, usdt_balance / usdt_price)
        qty = self.truncate(trade_amount)

        try:
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
        except Exception as e:
            error_message = f"Arbitrage: Error in USDT lower trade for {coin}: {str(e)}"
            print(error_message)
            raise  APIError()


    def _trade_usdc_lower(self, coin: str, usdt_pair: str, usdc_pair: str, usdt_price: float, usdc_price: float, initial_usdcusdt: float) -> float:
        diff = usdt_price - usdc_price
        spread = (diff/usdc_price)*100
        if spread < self.config.min_spread:
            return 0

        usdt_balance = self.api_client.get_wallet_balance('USDT')
        trade_amount = min(self.config.max_amount, usdt_balance / usdt_price)
        qty = self.truncate(trade_amount)

        try:
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
        except Exception as e:
            error_message = f"Arbitrage: Error in USDC lower trade for {coin}: {str(e)}"
            print(error_message)
            raise  APIError()



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

        verify = self.api_client.get_open_order(pair)
        if not verify:
            return position
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
        profit = current_balance - self.initial_balance
        return profit

    def run(self, status_callback=None):
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
                    err = (f"Error occurred: {e}")
                    err+= ("\nCheck your trading account for active trade and complete manually")
                    self.active = False
                    return err

            if self.active:
                print('Sleeping for 2 seconds')
                for _ in range(2):
                    if not self.active:
                        break
                    time.sleep(1)

        total_time = datetime.now() - start_time
        total_profit = self._calculate_profit('USDT')
        minutes, seconds = divmod(total_time.seconds, 60)
        print(f'Traded for {minutes} minutes and {seconds} seconds')
        print(f'Total profit: ${total_profit}')

        final_message = "Arbitrage: Traded for " +str(minutes) +" minutes and " + str(seconds) + " seconds. Total profit: " + str(round(total_profit,2))
        print(final_message)
        if status_callback:
            status_callback(final_message)
        msg = "BOT: Trade completed in " +str(minutes) +" minute(s) and " + str(seconds) + " second(s).\nTotal profit: 💲" + str(round(total_profit,2))
        return msg
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

    def start(self, status_callback=None):
        try:
            if status_callback:
                status_callback("Starting trading process...")
            profit = self.arbitrage.run(status_callback)
            return profit
        except Exception as e:
            error_message = f"ArbitrageWrapper: An unexpected error occurred: {e}"
            if status_callback:
                status_callback(error_message)
            if "ErrCode: 401" in str(e):
                return "Error: Invalid Api Key or Secret Key!\nUse /start to restart the bot, then /set_config to set the correct keys."
            return f"Error: {str(e)}", None

    def stop(self):
        if hasattr(self, 'arbitrage'):
            self.arbitrage.active = False
            self.arbitrage.stop()
            return "Stop command received"
        return "Bot not running"

    def get_profit(self):
        if hasattr(self, 'arbitrage'):
            return self.arbitrage._calculate_profit('USDT')
        return 0.0
    
class TelegramInterface:
    def __init__(self, token: str):
        self.application = Application.builder().token(token).build()
        self.arbitrage_wrapper = None
        self.token = token
        self._lock = asyncio.Lock()  # Use asyncio.Lock instead of threading.Lock
        self.background_tasks = set()
        # Define conversation states
        self.APIKEY, self.APISECRET, self.COINS, self.AMOUNT, self.STOPLOSS, self.SPREAD, self.DURATION = range(7)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Welcome to the Sea Crest Bot! Please use the command /set_config to configure your settings.')

    async def set_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Please enter your API key:')
        return self.APIKEY

    async def set_coins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('Please enter the new coins to trade (comma-separated):')
        return self.COINS

    async def get_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['api_key'] = update.message.text
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await update.message.reply_text('Your API key has been saved. Please enter your API secret now:')
        return self.APISECRET

    async def get_api_secret(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['api_secret'] = update.message.text
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await update.message.reply_text('API secret saved. Now enter the coins to trade (comma-separated: BTC,BNB):')
        return self.COINS

    async def get_coins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['coins'] = update.message.text.split(',')
        await update.message.reply_text('Your selected coins have been saved. Configuration is complete. Please use the command /start_bot to begin trading.')
        return ConversationHandler.END

    async def request_trade_params(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('How much would you like to trade? Please ensure that your spot USDT balance is sufficient for this amount:')
        return self.AMOUNT

    async def get_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['max_amount'] = float(update.message.text)
        await update.message.reply_text('What is the maximum amount you are willing to risk for this trade? This will be set as your stop-loss threshold:')
        return self.STOPLOSS

    async def get_stoploss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['stop_loss'] = float(update.message.text)
        await update.message.reply_text('Please enter the minimum spread (recommended: 0.15):')
        return self.SPREAD

    async def get_spread(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['min_spread'] = float(update.message.text)
        await update.message.reply_text('Please specify the trading duration in minutes ⏱️:')
        return self.DURATION

    async def get_duration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['duration'] = int(update.message.text)
        await self.start_bot(update, context)
        return ConversationHandler.END

    async def start_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        async with self._lock:
            if self.arbitrage_wrapper and hasattr(self.arbitrage_wrapper, 'active') and self.arbitrage_wrapper.arbitrage.active:
                await update.message.reply_text('The bot is currently running!')
                return

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
                # Create and store the background task
                task = asyncio.create_task(self.run_arbitrage(context, update.effective_chat.id))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)
                await update.message.reply_text('Trading Instructions noted✍️ ')
            else:
                await update.message.reply_text('Some configuration data are missing. Please use /set_config to set up your configuration.')

    async def run_arbitrage(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        if self.arbitrage_wrapper:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Trading process started. You will be notified when trading completes."
            )
            try:
                # Create a message queue for communication between threads
                message_queue = asyncio.Queue()
                
                # Create a status callback that puts messages in the queue
                async def async_callback(message):
                    await message_queue.put(message)

                def status_callback(message):
                    # Create a new event loop for this thread if necessary
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    loop.create_task(async_callback(message))

                # Start a task to process messages from the queue
                async def process_messages():
                    while True:
                        try:
                            message = await message_queue.get()
                            if message == "DONE":
                                break
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message
                            )
                        except Exception as e:
                            print(f"Error processing message: {e}")

                # Start the message processing task
                message_processor = asyncio.create_task(process_messages())

                # Run the trading process in a thread pool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self.arbitrage_wrapper.start(status_callback)
                )
                if isinstance(result, tuple):
                    status, profit = result
                else:
                    status, profit = "Success!", result
                
                # Signal the message processor to stop
                await message_queue.put("DONE")
                await message_processor

                # Send final status
                await context.bot.send_message(
                    chat_id=chat_id,
                    text= profit if profit is not None else status
                )

            except Exception as e:
                print(f"Error in run_arbitrage: {str(e)}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Error during trading: {str(e)}"
                )
                if 'message_processor' in locals():
                    await message_queue.put("DONE")
                    await message_processor

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        async with self._lock:
            if self.arbitrage_wrapper:
                try:
                    # Stop the arbitrage process
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, self.arbitrage_wrapper.stop)
                    
                    # Cancel any running background tasks
                    for task in self.background_tasks:
                        try:
                            task.cancel()
                            await task
                        except asyncio.CancelledError:
                            pass
                    
                    self.background_tasks.clear()
                    await update.message.reply_text(f'The trading bot has been halted. 🛑 {result}')
                except Exception as e:
                    await update.message.reply_text(f'An error occurred while attempting to stop the bot: {str(e)}')
            else:
                await update.message.reply_text('Bot is not running.')

    async def get_profit(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.arbitrage_wrapper:
            try:
                loop = asyncio.get_event_loop()
                profit = await loop.run_in_executor(None, self.arbitrage_wrapper.get_profit)
                await update.message.reply_text(f'Your current profit is: ${profit:.2f}')
            except Exception as e:
                await update.message.reply_text(f'Error getting profit: {str(e)}')
        else:
            await update.message.reply_text('Bot is not configured or running.')

    def run(self):
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("set_config", self.set_config),
                CommandHandler("start_bot", self.request_trade_params),
                CommandHandler("set_coins", self.set_coins),
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
    def setup_webhook(self, url):
        self.application.run_webhook(
            listen="0.0.0.0",
            port=8443,
            url_path=self.token,
            webhook_url=f"{url}/{self.token}"
        )

    async def __cleanup(self):
        """Cleanup method to ensure all tasks are properly cancelled"""
        for task in self.background_tasks:
            try:
                task.cancel()
                await task
            except asyncio.CancelledError:
                pass
        self.background_tasks.clear()

    def __del__(self):
        """Destructor to ensure cleanup"""
        if self.background_tasks:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.__cleanup())
            else:
                try:
                    loop.run_until_complete(self.__cleanup())
                except RuntimeError:
                    # If the event loop is closed, create a new one
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    new_loop.run_until_complete(self.__cleanup())
                    new_loop.close()
    

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