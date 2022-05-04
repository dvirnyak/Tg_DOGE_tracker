from telegram.ext import Updater, MessageHandler, Filters
from telegram.ext import CommandHandler

import time

from multiprocessing import Process, Lock

import requests
import json

telegram_bot_token = "5325608136:AAFrbmsGXxbsYKO3oO1SvD12ZK7_Y_2oCBc"

updater = Updater(token=telegram_bot_token, use_context=True)
dispatcher = updater.dispatcher
lock = Lock()

def start(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=chat_id,
                             text="Привет, я могу отправить текущий курс DOGE, "
                                  "а также предупреждать о резких скачках(можно настроить). Давай начнём")
    lock.acquire()

    with open("users.json", "r") as f:
        users = json.load(f)

    users[chat_id] = {"state": "default", "limits": []}

    with open("users.json", "w") as f:
        json.dump(users, f)

    lock.release()


def rates_msg(rate_new, rate_old, time1):
    change = 0
    smile = ''
    if (rate_old > rate_new and rate_old != 0):
        change = 100 * (1 - rate_new / rate_old)
        smile = "📉"
    elif (rate_old != 0):
        smile = "📈"
        change = 100 * (rate_new / rate_old - 1)
    msg = "{smile} {change:.2f}% за последние {sec} секунд".format(smile=smile, change=change, sec=time1)
    return msg


def new_tracking(update, context):
    lock.acquire()
    users = {}

    with open("users.json", "r") as f:
        users = json.load(f)

    chat_id = str(update.effective_chat.id)
    user_msg = update.message.text

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
    with open('users.json', 'w') as f:
        json.dump(users, f)
    lock.release()


def rate(update, context):
    lock.acquire()
    with open("rates.json", "r") as f:
        rates_history = list(map(float, json.load(f)))
    lock.release()

    chat_id = update.effective_chat.id
    msg = "1 DOGE = {} USDT\n\n".format(rates_history[-1])

    basic_time = 3600
    if (rates_history[-basic_time] != 0):
        msg += rates_msg(rates_history[-1], rates_history[-basic_time], basic_time)

    context.bot.send_message(chat_id=chat_id,
                             text=msg)


def notifier():
    delay = 1
    while True:
        lock.acquire()
        with open("users.json", "r") as f:
            users = json.load(f)

        with open("rates.json", "r") as f:
            rates_history = list(map(float, json.load(f)))

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

                if (new_rate > old_rate and (new_rate / old_rate - 1) >= diff) \
                        or (new_rate < old_rate and (1 - new_rate / old_rate) >= diff)\
                        and limit['last_check'] - time.time() > time_diff:
                    msg += rates_msg(new_rate, old_rate, time_diff-1) + '\n'
                    users[chat_id]['limits'][index]['last_check'] = int(time.time())

            if len(msg) > 0:
                msg = "1 DOGE = {} USDT\n\n".format(rates_history[-1]) + msg
                updater.bot.send_message(chat_id=chat_id,
                                         text=msg)
        with open('users.json', 'w') as f:
            json.dump(users, f)
        lock.release()
        time.sleep(delay)


def checker():
    delay = 1
    with open("rates.json", "r") as f:
        rates_history = list(map(float, json.load(f)))

    key = "https://api.binance.com/api/v3/ticker/price?symbol="
    currencies = ["DOGEUSDT"]

    while True:
        for i in currencies:
            url = key + i
            data = requests.get(url)
            data = data.json()
            rates_history = rates_history[1:]
            rates_history.append(data['price'])

        lock.acquire()
        with open('rates.json', 'w') as f:
            json.dump(rates_history, f)
        lock.release()

        time.sleep(delay)


def bot():
    updater.start_polling()


dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("rate", rate))
dispatcher.add_handler(CommandHandler("new", new_tracking))
dispatcher.add_handler(MessageHandler(Filters.text, new_tracking))

Process(target=checker).start()
Process(target=bot).start()
Process(target=notifier()).start()
