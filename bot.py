from telegram.ext import Updater, MessageHandler, Filters
from telegram.ext import CommandHandler

import numpy as np
import matplotlib.pyplot as plt

import json
import time
import asyncio
import aiohttp
import io
import os

telegram_bot_token = os.getenv('token')

updater = Updater(token=telegram_bot_token, use_context=True)
dispatcher = updater.dispatcher

def load_users():
    with open("users.json", "r") as f:
        users = json.load(f)
    return users

def load_rates():
    with open("rates.json", "r") as f:
       rates = list(map(float, json.load(f)))
    return rates

def update_users(users):
    with open("users.json", "w") as f:
        json.dump(users, f)

def update_rates(rates):
    with open("rates.json", "w") as f:
        json.dump(rates, f)

def check_user(users, chat_id):
    if not (chat_id in users):
        users[chat_id] = {"state": "default", "limits": []}
    return users

def start(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=chat_id,
                             text="Привет, я могу отправить текущий курс DOGE, "
                                  "а также предупреждать о резких скачках(можно настроить). Давай начнём")

    users = load_users()
    users[chat_id] = {"state": "default", "limits": []}
    update_users(users)


def help(update, context):
    chat_id = update.effective_chat.id

    text = '''Доступные команды:
    
/rate - текущий курс
/new - добавить новое отслеживание
/trackings - посмотреть текущие отслеживания
/delete N - удалить отслеживание номер N'''

    context.bot.send_message(chat_id=chat_id,
                             text=text)


def rates_msg(rate_new, rate_old, time):
    change = 0
    smile = ''
    if (rate_old > rate_new and rate_old != 0):
        change = 100 * (1 - rate_new / rate_old)
        smile = "📉"
    elif (rate_old != 0):
        smile = "📈"
        change = 100 * (rate_new / rate_old - 1)
    msg = f"{smile} {change:.2f}% за последние {time} секунд"
    return msg


def trackings(update, context):
    chat_id = str(update.effective_chat.id)
    users = load_users()

    users = check_user(users, chat_id)

    index = 0
    msg = 'Твои отслеживания:\n\n'
    for limit in users[chat_id]['limits']:
        index += 1
        msg += "{index}. На {percent}% за {sec} секунд\n".format(
            index=index, percent=limit['diff'], sec=limit['time'])

    context.bot.send_message(chat_id=chat_id, text=msg)


def delete(update, context):

    chat_id = str(update.effective_chat.id)
    users = load_users()
    user_msg = update.message.text
    index = int(user_msg[8:]) - 1
    del users[chat_id]['limits'][index]
    msg = "Как скажешь"
    context.bot.send_message(chat_id=chat_id, text=msg)

    update_users(users)

    trackings(update, context)


def new_tracking(update, context):
    users = load_users()
    chat_id = str(update.effective_chat.id)
    user_msg = update.message.text

    users = check_user(users, chat_id)

    msg = ''
    if (users[chat_id]['state'] == "default" and user_msg == "/new"):
        users[chat_id]['state'] = "enter diff"
        msg = "Ок. Введи на сколько % должен измениться курс, чтобы я тебе написал"
    elif (users[chat_id]['state'] == "enter diff"):
        users[chat_id]['state'] = "enter time"
        users[chat_id]['limits'].append({'time': 1, 'last_check': 0})
        users[chat_id]['limits'][-1]['diff'] = float(user_msg)
        msg = "Ок. Введи за какое время(в секундах) курс должен измениться"
    elif (users[chat_id]['state'] == "enter time"):
        users[chat_id]['state'] = "default"
        users[chat_id]['limits'][-1]['time'] = int(user_msg)
        msg = "Запомнил. Слежу внимательнее"

    context.bot.send_message(chat_id=chat_id, text=msg)
    update_users(users)


def rate(update, context):
    rates_history = load_rates()
    chat_id = update.effective_chat.id

    msg = f"1 DOGE = {rates_history[-1]} USDT\n\n"
    basic_time = 3600

    if (rates_history[-basic_time] != 0):
        msg += rates_msg(rates_history[-1], rates_history[-basic_time], basic_time)

    context.bot.send_message(chat_id=chat_id,
                             text=msg)

    y = np.array(rates_history[-basic_time:])
    x = np.array(range(len(rates_history[-basic_time:])))
    fig = plt.figure()
    plt.title("DOGE/USD")
    plt.xlabel("Seconds")
    plt.ylabel("Price")
    plt.plot(x, y)

    buffer = io.BytesIO()
    fig.savefig(buffer, format='png')

    plt.close()

    buffer.seek(0)
    context.bot.send_photo(chat_id, buffer.read())


async def notifier():
    delay = 1
    while True:
        users = load_users()
        rates_history = load_rates()

        for chat_id in users.keys():
            user = users[chat_id]
            msg = ''
            index = -1
            for limit in user['limits']:
                index += 1
                time_diff, diff = int(limit['time']) + 1, float(limit['diff']) / 100
                new_rate, old_rate = rates_history[-1], rates_history[-time_diff]
                if old_rate == 0 or new_rate == 0:
                    continue

                if ((new_rate > old_rate and (new_rate / old_rate - 1) >= diff) \
                    or (new_rate < old_rate and (1 - new_rate / old_rate) >= diff)) \
                        and (int(time.time()) - int(limit['last_check']) > time_diff / 2):
                    msg += rates_msg(new_rate, old_rate, time_diff - 1) + '\n'

                    users[chat_id]['limits'][index]['last_check'] = int(time.time())

            if len(msg) > 0:
                msg = f"1 DOGE = {rates_history[-1]} USDT\n\n" + msg
                updater.bot.send_message(chat_id=chat_id,
                                         text=msg)
        update_users(users)

        await asyncio.sleep(delay)


async def checker():
    delay = 1
    rates_history = load_rates()

    key = "https://api.binance.com/api/v3/ticker/price?symbol="
    currencies = ["DOGEUSDT"]

    async with aiohttp.ClientSession() as session:
        while True:
            for i in currencies:
                url = key + i
                async with session.get(url) as resp:
                    data = await resp.text()

                data = json.loads(data)
                rates_history = rates_history[1:]
                rates_history.append(data['price'])
                update_rates(rates_history)

            await asyncio.sleep(delay)


def bot():
    updater.start_polling()

async def main():
    bot()
    task2 = asyncio.create_task(notifier())
    task3 = asyncio.create_task(checker())

    await task2
    await task3

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("rate", rate))
dispatcher.add_handler(CommandHandler("new", new_tracking))
dispatcher.add_handler(CommandHandler("help", help))
dispatcher.add_handler(CommandHandler("trackings", trackings))
dispatcher.add_handler(CommandHandler("delete", delete))
dispatcher.add_handler(MessageHandler(Filters.text, new_tracking))

asyncio.run(main())