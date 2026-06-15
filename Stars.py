import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import random
import time
import threading
from datetime import datetime, timedelta

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = '8513337227:AAFinAnTEFxsVXa0E8BOV1Rm-8VU8LHywIM'
BOT_USERNAME = "ТВОЙ_БОТ"
OWNER_ID = 7430802882
CASE_PRICE = 10
CASE_NAME = '📦 Обычный кейс'

REWARDS = {
    1: {'type': 'coin', 'chance': 45, 'name': '1 StarsCoin', 'emoji': '🪙'},
    2: {'type': 'coin', 'chance': 30, 'name': '2 StarsCoin', 'emoji': '🪙'},
    5: {'type': 'coin', 'chance': 15, 'name': '5 StarsCoin', 'emoji': '🪙'},
    10: {'type': 'coin', 'chance': 10, 'name': '10 StarsCoin', 'emoji': '🪙'},
    15: {'type': 'gift', 'chance': 5, 'name': 'Подарок 15⭐', 'emoji': '🎁'}
}

PROMO_CODES = {
    "RONALDO": {"amount": 100, "uses_left": -1},
    "XGEN": {"amount": 50, "uses_left": 100},
    "TRAGG": {"amount": 25, "uses_left": 50},
    "STARS": {"amount": 10, "uses_left": 200}
}

ANIMATION_FRAMES = [
    "🎲 Открываю кейс...",
    "🎲 Вращаю барабан... ███▒▒▒▒▒▒▒ 20%",
    "🎲 Вращаю барабан... ██████▒▒▒▒ 50%",
    "🎲 Вращаю барабан... █████████▒ 80%",
    "🎲 Вращаю барабан... ██████████ 100%",
    "✨ Почти готово...",
    "🎁 Открываю!"
]

conn = sqlite3.connect('stars_bot.db', check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            total_opened INTEGER DEFAULT 0,
            total_gifts INTEGER DEFAULT 0,
            total_coins_won INTEGER DEFAULT 0,
            last_daily TEXT,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, item_name TEXT, item_type TEXT,
            item_value INTEGER, emoji TEXT DEFAULT '🪙',
            claimed INTEGER DEFAULT 0, opened_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, reward_name TEXT, reward_type TEXT,
            reward_value INTEGER, emoji TEXT DEFAULT '🪙',
            opened_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks (
            user_id INTEGER, task_id TEXT,
            progress INTEGER DEFAULT 0, done INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS referrals (
            inviter_id INTEGER, invited_id INTEGER PRIMARY KEY,
            rewarded INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS promos_used (
            user_id INTEGER, promo_code TEXT,
            used_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, promo_code)
        );
        CREATE TABLE IF NOT EXISTS bans (
            user_id INTEGER PRIMARY KEY,
            reason TEXT DEFAULT 'Нарушение',
            banned_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()

init_db()

def is_banned(uid):
    cursor.execute('SELECT 1 FROM bans WHERE user_id = ?', (uid,))
    return cursor.fetchone() is not None

def get_user(uid):
    cursor.execute('SELECT user_id, balance, total_opened, total_gifts, total_coins_won, last_daily FROM users WHERE user_id = ?', (uid,))
    row = cursor.fetchone()
    if row:
        return {'user_id': row[0], 'balance': row[1], 'total_opened': row[2], 'total_gifts': row[3], 'total_coins_won': row[4], 'last_daily': row[5]}
    cursor.execute('INSERT OR IGNORE INTO users (user_id, balance, total_opened, total_gifts, total_coins_won) VALUES (?, 0, 0, 0, 0)', (uid,))
    conn.commit()
    return {'user_id': uid, 'balance': 0, 'total_opened': 0, 'total_gifts': 0, 'total_coins_won': 0, 'last_daily': None}

def get_balance(uid):
    return get_user(uid)['balance']

def update_balance(uid, amount):
    new_bal = get_balance(uid) + amount
    cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_bal, uid))
    conn.commit()
    return new_bal

def add_item(uid, name, itype, value, emoji):
    cursor.execute('INSERT INTO inventory (user_id, item_name, item_type, item_value, emoji) VALUES (?, ?, ?, ?, ?)',
                   (uid, name, itype, value, emoji))
    conn.commit()

def get_items(uid, claimed=0):
    cursor.execute('SELECT * FROM inventory WHERE user_id = ? AND claimed = ? ORDER BY opened_at DESC', (uid, claimed))
    return cursor.fetchall()

def claim_item(uid, item_id):
    cursor.execute('SELECT * FROM inventory WHERE id = ? AND user_id = ? AND claimed = 0', (item_id, uid))
    item = cursor.fetchone()
    if not item:
        return False, None
    cursor.execute('UPDATE inventory SET claimed = 1 WHERE id = ?', (item_id,))
    update_balance(uid, item[4])
    conn.commit()
    return True, item

def add_history(uid, name, itype, value, emoji):
    cursor.execute('INSERT INTO history (user_id, reward_name, reward_type, reward_value, emoji) VALUES (?, ?, ?, ?, ?)',
                   (uid, name, itype, value, emoji))
    conn.commit()

def update_stats(uid, gift=False, coins=0):
    updates = ['total_opened = total_opened + 1']
    if gift:
        updates.append('total_gifts = total_gifts + 1')
    if coins > 0:
        updates.append(f'total_coins_won = total_coins_won + {coins}')
    cursor.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", (uid,))
    conn.commit()

def get_top(limit=10):
    cursor.execute('SELECT user_id, balance, total_opened FROM users ORDER BY balance DESC LIMIT ?', (limit,))
    return cursor.fetchall()

def can_use_promo(uid, code):
    cursor.execute('SELECT 1 FROM promos_used WHERE user_id = ? AND promo_code = ?', (uid, code))
    if cursor.fetchone():
        return False
    promo = PROMO_CODES.get(code.upper())
    if not promo:
        return False
    if promo['uses_left'] == 0:
        return False
    return True

def use_promo(uid, code):
    promo = PROMO_CODES[code.upper()]
    if promo['uses_left'] > 0:
        promo['uses_left'] -= 1
    cursor.execute('INSERT INTO promos_used (user_id, promo_code) VALUES (?, ?)', (uid, code.upper()))
    update_balance(uid, promo['amount'])
    conn.commit()
    return promo['amount']

def add_referral(inviter, invited):
    try:
        cursor.execute('INSERT INTO referrals (inviter_id, invited_id) VALUES (?, ?)', (inviter, invited))
        conn.commit()
        update_balance(inviter, 20)
        return True
    except:
        return False

def count_referrals(uid):
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE inviter_id = ?', (uid,))
    return cursor.fetchone()[0]

def get_task(uid, tid):
    cursor.execute('SELECT * FROM tasks WHERE user_id = ? AND task_id = ?', (uid, tid))
    row = cursor.fetchone()
    if row:
        return {'user_id': row[0], 'task_id': row[1], 'progress': row[2], 'done': row[3]}
    cursor.execute('INSERT INTO tasks (user_id, task_id) VALUES (?, ?)', (uid, tid))
    conn.commit()
    return {'user_id': uid, 'task_id': tid, 'progress': 0, 'done': 0}

def set_task(uid, tid, progress=None, done=None):
    t = get_task(uid, tid)
    np = progress if progress is not None else t['progress']
    nd = done if done is not None else t['done']
    cursor.execute('UPDATE tasks SET progress = ?, done = ? WHERE user_id = ? AND task_id = ?', (np, nd, uid, tid))
    conn.commit()

def claim_daily(uid):
    user = get_user(uid)
    now = datetime.now()
    if user['last_daily']:
        last = datetime.fromisoformat(user['last_daily'])
        if (now - last) < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last)
            h = int(remaining.total_seconds() // 3600)
            m = int((remaining.total_seconds() % 3600) // 60)
            return False, f"Жди {h} ч {m} мин"
    cursor.execute('UPDATE users SET last_daily = ? WHERE user_id = ?', (now.isoformat(), uid))
    update_balance(uid, 5)
    conn.commit()
    return True, "Ежедневный бонус: +5 🪙"

def open_case():
    roll = random.randint(1, 100)
    cum = 0
    for val, data in REWARDS.items():
        cum += data['chance']
        if roll <= cum:
            return val, data['type'], data['name'], data['emoji']
    return 0, 'coin', 'ничего', '❌'

def main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton('💰 Баланс', callback_data='bal'),
        InlineKeyboardButton('📦 Кейс', callback_data='open'),
        InlineKeyboardButton('🎒 Инвентарь', callback_data='inv'),
        InlineKeyboardButton('🏆 Топ', callback_data='top'),
        InlineKeyboardButton('👤 Профиль', callback_data='prof'),
        InlineKeyboardButton('🎁 Промокод', callback_data='promo_menu'),
        InlineKeyboardButton('📋 Задания', callback_data='tasks_menu'),
        InlineKeyboardButton('👥 Рефералы', callback_data='ref_menu'),
        InlineKeyboardButton('🎯 Бонус', callback_data='daily'),
        InlineKeyboardButton('ℹ️ Помощь', callback_data='help')
    )
    return kb

def back_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton('🔙 Назад', callback_data='main'))
    return kb

def animate_single_case(chat_id, message_id, user_id):
    for frame in ANIMATION_FRAMES:
        try:
            bot.edit_message_text(f"{CASE_NAME}\n\n{frame}", chat_id, message_id)
            time.sleep(0.5)
        except:
            time.sleep(0.3)
    
    val, typ, name, emoji = open_case()
    add_item(user_id, name, typ, val, emoji)
    add_history(user_id, name, typ, val, emoji)
    is_gift = (typ == 'gift')
    coins = val if typ == 'coin' else 0
    update_stats(user_id, gift=is_gift, coins=coins)
    
    if is_gift:
        t = get_task(user_id, 'win_gift')
        if not t['done']:
            set_task(user_id, 'win_gift', done=1)
            update_balance(user_id, 30)
    
    t2 = get_task(user_id, 'open_5')
    if not t2['done']:
        np = t2['progress'] + 1
        if np >= 5:
            set_task(user_id, 'open_5', progress=0, done=1)
            update_balance(user_id, 15)
        else:
            set_task(user_id, 'open_5', progress=np)
    
    t3 = get_task(user_id, 'collect_100')
    if not t3['done'] and get_balance(user_id) >= 100:
        set_task(user_id, 'collect_100', done=1)
        update_balance(user_id, 25)
    
    try:
        bot.edit_message_text(
            f"{CASE_NAME}\n\n✨ Выпало: {emoji} {name}\n📦 В инвентаре!\n💰 Баланс: {get_balance(user_id)} 🪙",
            chat_id, message_id, reply_markup=back_kb()
        )
    except:
        pass

def animate_multiple_cases(chat_id, message_id, user_id, count):
    results = []
    for i in range(count):
        val, typ, name, emoji = open_case()
        add_item(user_id, name, typ, val, emoji)
        add_history(user_id, name, typ, val, emoji)
        is_gift = (typ == 'gift')
        coins = val if typ == 'coin' else 0
        update_stats(user_id, gift=is_gift, coins=coins)
        results.append({'emoji': emoji, 'name': name, 'gift': is_gift})
        
        try:
            progress_text = ""
            for j in range(count):
                if j < i:
                    progress_text += "✅ "
                elif j == i:
                    progress_text += "🎲 "
                else:
                    progress_text += "⬜ "
            bot.edit_message_text(
                f"📦 Открываю кейсы...\n\n{progress_text}\n\nГотово: {i+1}/{count}",
                chat_id, message_id
            )
            time.sleep(1.0)
        except:
            time.sleep(0.5)
    
    if any(r['gift'] for r in results):
        t = get_task(user_id, 'win_gift')
        if not t['done']:
            set_task(user_id, 'win_gift', done=1)
            update_balance(user_id, 30)
    
    t2 = get_task(user_id, 'open_5')
    if not t2['done']:
        np = t2['progress'] + count
        if np >= 5:
            set_task(user_id, 'open_5', progress=0, done=1)
            update_balance(user_id, 15)
        else:
            set_task(user_id, 'open_5', progress=np)
    
    t3 = get_task(user_id, 'collect_100')
    if not t3['done'] and get_balance(user_id) >= 100:
        set_task(user_id, 'collect_100', done=1)
        update_balance(user_id, 25)
    
    result_text = "\n".join([f"{r['emoji']} {r['name']}" for r in results])
    try:
        bot.edit_message_text(
            f"📦 Открыто {count} кейсов:\n\n{result_text}\n\n📦 В инвентаре!\n💰 Баланс: {get_balance(user_id)} 🪙",
            chat_id, message_id, reply_markup=back_kb()
        )
    except:
        pass

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.chat.id
    if is_banned(uid):
        bot.send_message(uid, "🚫 Заблокирован.")
        return
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('ref'):
        try:
            inviter = int(args[1][3:])
            if inviter != uid:
                if add_referral(inviter, uid):
                    try:
                        bot.send_message(inviter, "👥 Новый друг! +20 🪙")
                    except:
                        pass
        except:
            pass
    get_user(uid)
    bot.send_message(uid, f"🎲 Привет, {message.from_user.first_name}!\n\nКейс за {CASE_PRICE} 🪙. Выбивай подарки и звёзды!", reply_markup=main_kb())

@bot.message_handler(commands=['promo'])
def cmd_promo(message):
    uid = message.chat.id
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(uid, "Используй: /promo КОД")
        return
    code = parts[1].upper()
    if not can_use_promo(uid, code):
        bot.send_message(uid, "❌ Промокод недействителен.")
        return
    amount = use_promo(uid, code)
    bot.send_message(uid, f"✅ +{amount} 🪙!", reply_markup=main_kb())

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    uid = message.chat.id
    if uid != OWNER_ID:
        return
    parts = message.text.split()
    if len(parts) == 1:
        total_users = cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        total_opens = cursor.execute('SELECT SUM(total_opened) FROM users').fetchone()[0] or 0
        total_balance = cursor.execute('SELECT SUM(balance) FROM users').fetchone()[0] or 0
        banned = cursor.execute('SELECT COUNT(*) FROM bans').fetchone()[0]
        bot.send_message(uid, f"📊 Админ-панель\n\n👥 Пользователей: {total_users}\n📦 Открытий: {total_opens}\n💰 Балансов: {total_balance} 🪙\n🚫 Забанено: {banned}\n\n/admin give ID СУММА\n/admin send ID СУММА\n/admin ban ID ПРИЧИНА\n/admin unban ID\n/admin promo КОД СУММА USES\n/admin info ID\n/admin broadcast ТЕКСТ")
    elif len(parts) >= 2:
        cmd = parts[1].lower()
        if cmd == 'give' and len(parts) >= 4:
            target = int(parts[2])
            amount = int(parts[3])
            update_balance(target, amount)
            bot.send_message(uid, f"✅ Выдано {amount} 🪙 пользователю {target}")
            try:
                bot.send_message(target, f"💰 Админ выдал {amount} 🪙!")
            except:
                pass
        elif cmd == 'send' and len(parts) >= 4:
            target = int(parts[2])
            amount = int(parts[3])
            if get_balance(uid) < amount:
                bot.send_message(uid, "❌ Недостаточно монет!")
                return
            update_balance(uid, -amount)
            update_balance(target, amount)
            bot.send_message(uid, f"✅ Отправлено {amount} 🪙 пользователю {target}")
            try:
                bot.send_message(target, f"💰 Пользователь {uid} отправил вам {amount} 🪙!")
            except:
                pass
        elif cmd == 'ban' and len(parts) >= 3:
            target = int(parts[2])
            reason = ' '.join(parts[3:]) if len(parts) > 3 else 'Нарушение'
            cursor.execute('INSERT OR IGNORE INTO bans (user_id, reason) VALUES (?, ?)', (target, reason))
            conn.commit()
            bot.send_message(uid, f"🚫 Пользователь {target} забанен: {reason}")
        elif cmd == 'unban' and len(parts) >= 3:
            target = int(parts[2])
            cursor.execute('DELETE FROM bans WHERE user_id = ?', (target,))
            conn.commit()
            bot.send_message(uid, f"✅ Пользователь {target} разбанен")
        elif cmd == 'promo' and len(parts) >= 5:
            code = parts[2].upper()
            amount = int(parts[3])
            uses = int(parts[4])
            PROMO_CODES[code] = {"amount": amount, "uses_left": uses}
            bot.send_message(uid, f"✅ Промокод {code}: +{amount} 🪙, {uses} использований")
        elif cmd == 'info' and len(parts) >= 3:
            target = int(parts[2])
            u = get_user(target)
            items = len(get_items(target))
            refs = count_referrals(target)
            banned = is_banned(target)
            bot.send_message(uid, f"👤 ID{target}\n💰 Баланс: {u['balance']} 🪙\n📦 Кейсов: {u['total_opened']}\n🎁 Подарков: {u['total_gifts']}\n🎒 Предметов: {items}\n👥 Рефералов: {refs}\n🚫 Забанен: {'Да' if banned else 'Нет'}")
        elif cmd == 'broadcast' and len(parts) >= 3:
            text = ' '.join(parts[2:])
            users = cursor.execute('SELECT user_id FROM users').fetchall()
            count = 0
            for u in users:
                try:
                    bot.send_message(u[0], f"📢 Рассылка:\n\n{text}")
                    count += 1
                except:
                    pass
            bot.send_message(uid, f"✅ Отправлено {count} пользователям")

@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    uid = call.from_user.id
    mid = call.message.message_id
    cid = call.message.chat.id
    data = call.data

    if is_banned(uid):
        bot.answer_callback_query(call.id, "🚫 Заблокирован.", show_alert=True)
        return

    try:
        if data == 'main':
            bot.edit_message_text("Главное меню:", cid, mid, reply_markup=main_kb())
        elif data == 'bal':
            bot.edit_message_text(f"💰 Баланс: {get_balance(uid)} 🪙", cid, mid, reply_markup=back_kb())
        elif data == 'open':
            kb = InlineKeyboardMarkup(row_width=3)
            kb.add(
                InlineKeyboardButton('📦 x1 (10 🪙)', callback_data='open_1'),
                InlineKeyboardButton('📦 x2 (20 🪙)', callback_data='open_2'),
                InlineKeyboardButton('📦 x3 (30 🪙)', callback_data='open_3'),
                InlineKeyboardButton('📦 x4 (40 🪙)', callback_data='open_4'),
                InlineKeyboardButton('📦 x5 (50 🪙)', callback_data='open_5'),
                InlineKeyboardButton('🔙 Назад', callback_data='main')
            )
            bot.edit_message_text("📦 Сколько кейсов открыть?", cid, mid, reply_markup=kb)
        elif data.startswith('open_'):
            count = int(data.split('_')[1])
            price = CASE_PRICE * count
            if get_balance(uid) < price:
                bot.answer_callback_query(call.id, f"❌ Нужно {price} 🪙!", show_alert=True)
                return
            update_balance(uid, -price)
            bot.edit_message_text(f"📦 Открываю {count} кейсов...", cid, mid)
            if count == 1:
                thread = threading.Thread(target=animate_single_case, args=(cid, mid, uid))
            else:
                thread = threading.Thread(target=animate_multiple_cases, args=(cid, mid, uid, count))
            thread.start()
        elif data == 'inv':
            items = get_items(uid)
            if not items:
                bot.edit_message_text("🎒 Пусто.", cid, mid, reply_markup=back_kb())
                return
            kb = InlineKeyboardMarkup(row_width=2)
            for it in items:
                kb.add(InlineKeyboardButton(f"{it[5]} {it[2]} (x{it[4]})", callback_data=f"claim_{it[0]}"))
            kb.add(InlineKeyboardButton('🔙 Назад', callback_data='main'))
            bot.edit_message_text("🎒 Нажми чтобы забрать:", cid, mid, reply_markup=kb)
        elif data.startswith('claim_'):
            item_id = int(data.split('_')[1])
            ok, item = claim_item(uid, item_id)
            if ok:
                bot.answer_callback_query(call.id, f"✅ +{item[4]} 🪙!")
                bot.edit_message_text(f"✅ Готово! Баланс: {get_balance(uid)} 🪙", cid, mid, reply_markup=back_kb())
            else:
                bot.answer_callback_query(call.id, "❌ Ошибка.", show_alert=True)
        elif data == 'top':
            top = get_top(10)
            text = "🏆 Топ-10:\n\n"
            for i, u in enumerate(top, 1):
                text += f"{i}. ID{u[0]}: {u[1]} 🪙\n"
            bot.edit_message_text(text, cid, mid, reply_markup=back_kb())
        elif data == 'prof':
            u = get_user(uid)
            refs = count_referrals(uid)
            bot.edit_message_text(
                f"👤 Профиль\n\n"
                f"🆔 ID: {uid}\n"
                f"💰 Баланс: {u['balance']} 🪙\n"
                f"📦 Кейсов: {u['total_opened']}\n"
                f"🎁 Подарков: {u['total_gifts']}\n"
                f"👥 Рефералов: {refs}",
                cid, mid, reply_markup=back_kb()
            )
        elif data == 'promo_menu':
            bot.edit_message_text("Введи: /promo КОД\nДоступные: RONALDO, XGEN, TRAGG, STARS", cid, mid, reply_markup=back_kb())
        elif data == 'tasks_menu':
            t1 = get_task(uid, 'open_5')
            t2 = get_task(uid, 'win_gift')
            t3 = get_task(uid, 'collect_100')
            bot.edit_message_text(f"📋 Задания:\n\n1. Кейсов: {t1['progress']}/5 {'✅' if t1['done'] else ''}\n2. Подарок: {'✅' if t2['done'] else '❌'}\n3. 100 монет: {'✅' if t3['done'] else '❌'}", cid, mid, reply_markup=back_kb())
        elif data == 'ref_menu':
            refs = count_referrals(uid)
            link = f"https://t.me/{bot.get_me().username}?start=ref{uid}"
            bot.edit_message_text(f"👥 Ссылка:\n{link}\n\nПриглашено: {refs}", cid, mid, reply_markup=back_kb())
        elif data == 'daily':
            ok, msg = claim_daily(uid)
            bot.answer_callback_query(call.id, msg, show_alert=True)
            if ok:
                bot.edit_message_text(f"💰 Баланс: {get_balance(uid)} 🪙", cid, mid, reply_markup=back_kb())
        elif data == 'help':
            bot.edit_message_text("По вопросам: @Youtubeshortsfonk", cid, mid, reply_markup=back_kb())
    except Exception as e:
        print(f"Ошибка: {e}")
        try:
            bot.edit_message_text("❌ Ошибка.", cid, mid, reply_markup=main_kb())
        except:
            pass

print("🚀 Бот запущен!")
bot.infinity_polling()
