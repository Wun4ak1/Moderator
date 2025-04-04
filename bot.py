from dotenv import load_dotenv
import importlib
import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, JobQueue, ChatMemberHandler, CallbackQueryHandler, ConversationHandler, ContextTypes
import asyncio
from telegram.constants import ParseMode
from collections import defaultdict
import html
import datetime
print(datetime.__file__)

# ✅ Фойдаланувчи хабарларини ҳисоблаш учун dict
user_messages = defaultdict(list)

# 🚫 Анти-флуд функцияси
async def anti_flood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ✅ Хабар `update.message` бўлмаса, ҳеч нарса қилмаймиз
    if update.message is None:
        return

    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    current_time = datetime.datetime.now()

    # Фойдаланувчи хабар вақтини сақлаймиз
    user_messages[user_id].append(current_time)

    # Фақат охирги 5 сония ичидаги хабарларни ҳисоблаймиз
    user_messages[user_id] = [
        msg_time for msg_time in user_messages[user_id]
        if (current_time - msg_time).total_seconds() <= 5
    ]

    if len(user_messages[user_id]) >= 3:
        await update.message.delete()  # ✅ 3-та хабардан ошса, ўчирилади
        warning_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚨 {update.message.from_user.first_name}, илтимос, спам қилманг!",
        )
        await asyncio.sleep(3)  # ✅ 3 сониядан кейин хабарни ўчириш
        await warning_msg.delete()

# ✅ Регуляр ифодаларни импорт қилиш
re = importlib.import_module("re")

# ✅ Бот учун TOKEN
load_dotenv()
TOKEN = os.getenv("TOKEN")
CREATOR_ID = int(os.getenv("CREATOR_ID"))  # Ботнинг яратувчиси ID'си
# print(f"CREATOR_ID = {CREATOR_ID} (Type: {type(CREATOR_ID)})") # CREATOR_ID = 200555555 (Type: <class 'int'>)

if not TOKEN:
    print("Xato: .env faylida TOKEN sozlanmagan.")

broadcast_waiting = {}  # 📌 CREATOR'нинг жавобини кутиш учун

# 📂 Файл жойлашуви
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Жорий файл директорияси
DB_PATH = os.path.join(BASE_DIR, "users.db")  # Локал базани шу ерга қўямиз

# 🛠 Базага уланиш функцияси
def get_db_connection():
    return sqlite3.connect(DB_PATH) # Базани инициализация қиламиз /app/users.db

# ✅ "users" жадвалини яратиш
def create_users_table():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

           # Янгиланган код: Жадвал мавжуд бўлса, ўчирмасдан фақат яратиш
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER,  -- Фойдаланувчи ID
                    chat_id INTEGER,  -- Guruh ID
                    refer_count INTEGER DEFAULT 0,  -- Takliflar soni
                    write_access INTEGER DEFAULT 0,  -- Yozish huquqi
                    invited_by INTEGER,  -- Taklif qilgan foydalanuvchi ID
                    is_active INTEGER DEFAULT 1,  -- Guruhda qolgan yoki chiqib ketganligini saqlash
                    PRIMARY KEY (user_id, chat_id)  -- Foydalanuvchi + guruh bo‘yicha unikallik
                )
            """)
            conn.commit()
        print("✅ 'users' жадвали муваффақиятли яратилди!")
    except sqlite3.Error as e:
        print(f"❌ 'users' жадвалини яратишда хатолик: {e}")

# 🛠 "settings" жадвалини яратиш
def create_settings_table():
    """`settings` жадвали мавжуд бўлмаса, яратади."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE,  -- Гуруҳ ID
                    admin_id INTEGER,  -- Гуруҳ админи ID
                    restrictions TEXT,  -- Гуруҳ чекловлари (JSON кўринишида)
                    min_refer INTEGER DEFAULT 5  -- Минимал таклифлар сони
                )
            """)
            conn.commit()
            print("✅ 'settings' жадвали муваффақиятли яратилди!")
    except sqlite3.Error as e:
        print(f"❌ settings жадвалини яратишда хатолик: {e}")

# 🔄 Барча жадвалларни яратиш
def init_db():
    create_users_table()
    create_settings_table()
    add_groups_if_not_exists()

# Ботни ишга тушириш буйруғи
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("✅ /start буйруғи қабул қилинди!")  # DEBUG
    await update.message.reply_text("Ассалому алайкум! Сизни @kosonsoytoshkentaksi груҳига таклиф қиламиз!")

print("Бот ишга тушмоқда...")

async def get_chat_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"👥 Гуруҳ ID: `{chat.id}`\n📛 Гуруҳ номи: {chat.title}", parse_mode="Markdown")

async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📢 CREATOR'дан хабар олиш."""
    
    user_id = update.message.from_user.id

    commd = update.message  # Фойдаланувчи буйруғини олиш

    # ✅ Фақат ADMIN_USER_ID'га рухсат берилади
    if user_id != CREATOR_ID:
        msg = await update.message.reply_text("❌ Бу буйруқ фақат бот яратувчиси учун!")
        await asyncio.sleep(4)  # 4 сония кутиш
        try:
            await commd.delete()  # Буйруқни ўчириш
            await msg.delete()  # Хабарни ўчириш
        except Exception:
            pass  # Агар хабар йўқ бўлса, бот ишдан чиқмасин
        return  # Агар админ бўлмаса, чиқиб кетамиз
    
    broadcast_waiting[user_id] = True  # ✅ CREATOR'нинг жавобини кутиш
    await update.message.reply_text("✍️ Хабарни киритинг!\n\n📌 Намуна:\n<b>Title:</b> Янги эълон!\nsubtitle: Бугунги йиғилиш ҳақида\n<i>description:</i> Йиғилиш 18:00 да бўлади.", parse_mode="HTML")

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📢 CREATOR хабар юборганда, барча гуруҳларга юбориш."""
    
    user_id = update.message.from_user.id
    if user_id not in broadcast_waiting or not broadcast_waiting[user_id]:
        return  # Агар CREATOR хабар юбормаётган бўлса, чиқамиз

    del broadcast_waiting[user_id]  # ✅ Фойдаланувчини рўйхатдан олиб ташлаш

    message_text = update.message.text.strip()
    if not message_text:
        await update.message.reply_text("❌ Хабар бўш бўлиши мумкин эмас!")
        return

    # 📌 Хабарни форматлаш
    lines = message_text.split("\n")
    title, subtitle, description = "", "", ""

    for line in lines:
        if line.lower().startswith("title:"):
            title = line[6:].strip()
        elif line.lower().startswith("subtitle:"):
            subtitle = line[9:].strip()
        elif line.lower().startswith("description:"):
            description = line[12:].strip()
    
    if not title:
        await update.message.reply_text("❌ Хабарда <b>Title:</b> бўлиши шарт!", parse_mode="HTML")
        return

    formatted_message = f"📢 <b>{title}</b>\n"
    if subtitle:
        formatted_message += f"{subtitle}\n"
    if description:
        formatted_message += f"<i>{description}</i>"

    # 📌 Уникал гуруҳлар рўйхатини олиш
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT chat_id FROM users")
        chat_ids = cursor.fetchall()
    
    sent_count = 0
    
    for chat_id in chat_ids:
        chat_id = chat_id[0]
        try:
            await context.bot.send_message(chat_id, formatted_message, parse_mode="HTML")
            sent_count += 1
        except Exception as e:
            print(f"❌ {chat_id} гуруҳига хабар юбориб бўлмади: {e}")

    # ✅ CREATOR'га натижани юбориш
    await update.message.reply_text(f"✅ Хабар {sent_count} та гуруҳга юборилди!", parse_mode="HTML")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📢 CREATOR барча гуруҳларга хабар юбориши мумкин!"""
    
    user_id = update.message.from_user.id
    
    commd = update.message  # Фойдаланувчи буйруғини олиш

    # ✅ Фақат ADMIN_USER_ID'га рухсат берилади
    if user_id != CREATOR_ID:
        msg = await update.message.reply_text("❌ Бу буйруқ фақат бот яратувчиси учун!")
        await asyncio.sleep(4)  # 4 сония кутиш
        try:
            await commd.delete()  # Буйруқни ўчириш
            await msg.delete()  # Хабарни ўчириш
        except Exception:
            pass  # Агар хабар йўқ бўлса, бот ишдан чиқмасин
        return  # Агар админ бўлмаса, чиқиб кетамиз

    # 📌 Хабар матнини текшириш
    if not context.args:
        await update.message.reply_text("❌ Илтимос, хабар матнини ҳам юборинг!\n\nМасалан:\n<code>/broadcast Янги эълон!</code>", parse_mode="HTML")
        return

    message_text = " ".join(context.args)  # 📩 Хабар матнини олиш

    # 📌 Уникал гуруҳлар рўйхатини олиш
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT chat_id FROM users")
        chat_ids = cursor.fetchall()
    
    sent_count = 0  # ✅ Қанча гуруҳга юборилганлигини ҳисоблаш
    
    # 📢 Ҳар бир гуруҳга хабар юбориш
    for chat_id in chat_ids:
        chat_id = chat_id[0]
        try:
            await context.bot.send_message(chat_id, f"📢 <b>Эълон:</b>\n{message_text}", parse_mode="HTML")
            sent_count += 1
        except Exception as e:
            print(f"❌ {chat_id} гуруҳига хабар юбориб бўлмади: {e}")

    # ✅ CREATOR'га натижани юбориш
    await update.message.reply_text(f"✅ Хабар {sent_count} та гуруҳга юборилди!", parse_mode="HTML")

# 🔹 Гуруҳ базага қўшилиши учун
def add_group_to_db(chat_id: int):
    """Гуруҳни settings жадвалига қўшади, агар у йўқ бўлса."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Гуруҳ базада бор-йўқлигини текшириш
            cursor.execute("SELECT chat_id FROM settings WHERE chat_id=?", (chat_id,))
            exists = cursor.fetchone()

            if not exists:
                cursor.execute("""
                    INSERT INTO settings (chat_id, min_refer) 
                    VALUES (?, ?)
                """, (chat_id, 1))  # Default referral limit = 1
                conn.commit()
                # print(f"✅ Гуруҳ базага қўшилди: {chat_id}")
            # else:
                # print(f"🔹 Гуруҳ олдиндан мавжуд: {chat_id}")

    except sqlite3.Error as e:
        print(f"❌ add_group_to_db(): Хатолик: {e}")

# 🔹 Барча гуруҳларни базага қўшиш учун махсус код
def fix_missing_groups():
    """Барча мавжуд гуруҳларни settings жадвалига қўшиш."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Бот уланган гуруҳларни топамиз
            cursor.execute("SELECT DISTINCT chat_id FROM users;")
            all_groups = cursor.fetchall()

            for group in all_groups:
                chat_id = group[0]
                add_group_to_db(chat_id)  # Гуруҳни базага қўшамиз
            
                # 🔹 settings жадвалида бор-йўқлигини текширамиз
                cursor.execute("SELECT 1 FROM settings WHERE chat_id=?", (chat_id,))
                exists = cursor.fetchone()

                if not exists:
                    # 🔹 Агар settings жадвалида йўқ бўлса, қўшамиз
                    cursor.execute("INSERT INTO settings (chat_id, min_refer) VALUES (?, ?)", (chat_id, 1))
                    conn.commit()
                    print(f"✅ Янги гуруҳ базага қўшилди: {chat_id}")

            # print("✅ Барча гуруҳлар settings жадвалига мослаштирилди!")

    except sqlite3.Error as e:
        print(f"❌ fix_missing_groups(): Хатолик: {e}")

# Бошлаш учун қўнғироқ қилинг:
fix_missing_groups()

def add_groups_if_not_exists():
    """Барча гуруҳлар учун, агар улар `users` жадвалда йўқ бўлса, қўшиш."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # Гуруҳларни `settings` жадвалидан олиш
            cursor.execute("SELECT chat_id FROM settings")
            chat_ids = cursor.fetchall()

            for chat_id_tuple in chat_ids:
                chat_id = chat_id_tuple[0]

                # Гуруҳ `users` базасида бор-йўқлигини текшириш
                cursor.execute("SELECT 1 FROM users WHERE chat_id=?", (chat_id,))
                exists = cursor.fetchone()

                if not exists:
                    # Агар гуруҳ `users` базасида йўқ бўлса, қўшиш
                    cursor.execute("""
                        INSERT INTO users (user_id, chat_id, refer_count, write_access, invited_by, is_active) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (99999999, chat_id, 0, 0, None, 1))
                    conn.commit()
                    print(f"✅ Янги гуруҳ `users` базасига қўшилди: {chat_id}")
                # else:
                    # print(f"⚡ Гуруҳ `users` базасида аллақачон мавжуд: {chat_id}")
    except sqlite3.Error as e:
        print(f"❌ add_groups_if_not_exists(): Хатолик юз берди: {e}")

import sqlite3

def check_user_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, chat_id, refer_count, invited_by, is_active FROM users")
    users = cursor.fetchall()
    
#    for user in users:
#        print(f"User ID: {user[0]}, Chat ID: {user[1]}, Referral Count: {user[2]}, Invited By: {user[3]}, Active: {user[4]}")

    conn.close()

check_user_data()

async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Гуруҳга кирган ёки чиққан аъзоларни кузатиб боради."""
    chat_id = update.effective_chat.id
    user_id = update.chat_member.user.id
    status = update.chat_member.new_chat_member.status

    conn = get_db_connection()
    cursor = conn.cursor()

    if status in ["left", "kicked"]:  # Фойдаланувчи чиқиб кетган ёки блокланган
        cursor.execute("UPDATE users SET is_active=0 WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        conn.commit()
        print(f"❌ {user_id} ID'ли фойдаланувчи {chat_id} гуруҳидан чиқиб кетди!")
    
    elif status in ["member", "administrator", "creator"]:  # Фойдаланувчи гуруҳга қайта кирган
        cursor.execute("UPDATE users SET is_active=1 WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        conn.commit()
        print(f"✅ {user_id} ID'ли фойдаланувчи {chat_id} гуруҳига қайта қўшилди!")

    conn.close()

# 📊 Бот Статистикасини кўриш
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бот статистикасини кўриш."""
    user_id = update.message.from_user.id # Фойдаланувчи ID'си олинади
    user_name = update.message.from_user.first_name  # Фойдаланувчи исми олинади
    commd = update.message  # Фойдаланувчи буйруғини олиш

    # ✅ Фақат ADMIN_USER_ID'га рухсат берилади
    if user_id != CREATOR_ID:
        msg = await update.message.reply_text("❌ Бу буйруқ фақат бот яратувчиси учун!")
        await asyncio.sleep(4)  # 4 сония кутиш
        try:
            await commd.delete()  # Буйруқни ўчириш
            await msg.delete()  # Хабарни ўчириш
        except Exception:
            pass  # Агар хабар йўқ бўлса, бот ишдан чиқмасин
        return  # Агар админ бўлмаса, чиқиб кетамиз
    
    # 📌 Гуруҳлар ва аъзолар ҳақида маълумот олиш
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 📌 Уникал гуруҳларни ҳисоблаш
        cursor.execute("SELECT DISTINCT chat_id FROM users")  # Гуруҳ ID'сини оламиз
        chat_ids = cursor.fetchall()  # Гуруҳ ID'лари рўйхати
        total_groups = len(chat_ids)  # Гуруҳлар сони

        # 📌 Ҳар бир гуруҳдаги аъзолар сонини ҳисоблаш
        chat_info = ""  # Гуруҳлар ҳақидаги маълумотни сақлаш
        total_users = 0  # Барча гуруҳлардаги умумий аъзолар сони

        mention = f'<a href="tg://user?id={user_id}">{user_name}</a>' # Фойдаланувчи исмини форматлаш

        for chat_id in chat_ids:  # Гуруҳ ID'сини оламиз
            chat_id = chat_id[0]  # Гуруҳ ID'си

            # 🔥 Фақат гуруҳлар ва каналларни ҳисоблаш (шахсий чатларни чиқариб ташлаш)
            if chat_id > 0:
                continue  # Агар шахсий чат бўлса, давом этамиз

            try:
                real_user_count = await context.bot.get_chat_member_count(chat_id)  # 📌 Telegram API орқали аъзолар сони
                total_users += real_user_count  # ✅ Ҳақиқий аъзоларни қўшиш
            except Exception:
                continue  # Агар хатолик бўлса, шунчаки ўтиб кетамиз

            # ✅ Фақат гуруҳда қолган (фаол) аъзоларни ҳисоблаш
            cursor.execute("""
                SELECT COUNT(*)  -- Аъзолар сони
                FROM users  -- Фойдаланувчилар жадвали
                WHERE chat_id=?  -- Гуруҳ IDси
                    AND is_active=1  -- Гуруҳда қолган аъзолар
                """, (chat_id,))
            active_users = cursor.fetchone()[0] or 0  # Агар None чиқса, 0 қайтарамиз

            # total_users += active_users  # Барча гуруҳлардаги аъзолар сонини ҳисоблаш

            # ✅ Ёзиш ҳуқуқига эга фойдаланувчилар сонини ҳисоблаш
            cursor.execute("""
                SELECT COUNT(*)  -- Ёзиш мумкин бўлган аъзолар
                FROM users  -- Фойдаланувчилар жадвали
                WHERE chat_id=?  -- Гуруҳ IDси
                    AND is_active=1  -- Фақат фаол аъзолар
                    AND write_access=1  -- Ёзишга рухсат берилганлар
            """, (chat_id,))
            can_write_users = cursor.fetchone()[0] or 0  # Агар None чиқса, 0 қайтарамиз

            # 📌 Гуруҳ ҳақида Telegram API орқали маълумот олиш
            try:
                chat = await context.bot.get_chat(chat_id)  # 🆕 Гуруҳ маълумотлари
                chat_title = chat.title  # Гуруҳ номи

                # chat_link = f"https://t.me/{chat.username}" if chat.username else f"tg://openmessage?chat_id={chat_id}"

                if chat.username:
                    chat_link = f"https://t.me/{chat.username}"  # ✅ Агар username бўлса
                else:
                    #chat_link = f"tg://resolve?domain={chat_id}"  # ✅ Агар username йўқ бўлса
                    chat_invite_link = await chat.export_invite_link()  # ✅ Invite link олиш (Админ бўлса)
                    chat_link = chat_invite_link if chat_invite_link else f"tg://openmessage?chat_id={chat_id}"

                # 📌 **Гуруҳдаги ҳақиқий аъзолар сонини олиш (Telegram API орқали)**
                real_user_count = await context.bot.get_chat_member_count(chat_id)

            except Exception:
                chat_title = "Номаълум гуруҳ"
                chat_link = f"tg://openmessage?chat_id={chat_id}"
                real_user_count = "❓"  # Агар хатолик бўлса, номаълум қилиб қўямиз

            chat_info += (
                f"📌 <a href='{chat_link}'>{chat_title}</a> — "
                f"👤 {real_user_count} реал аъзо | ✅ {active_users} фаол | ✍️ {can_write_users} ёзиш мумкин\n"
            )

    # 📊 Бот статистикасини жўнатиш
    stats_message = (  # Статистика хабарини форматлаш
        f"📊 <b>Бот статистикаси</b>\n\n"
        f"📍 Уланган гуруҳлар сони: <b>{total_groups}</b>\n"
        f"👥 Барча гуруҳлардаги умумий аъзолар: <b>{total_users}</b>\n\n"
        f"{chat_info}" # Гуруҳлар ҳақидаги маълумот
    )

    await update.message.reply_text(stats_message, parse_mode="HTML") # Статистика хабарини юбориш

# 📊 Гуруҳ статистикасини кўриш
async def group_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat  # ✅ Chat ID olish uchun
    user_id = update.message.from_user.id

    # 📌 Агар шахсий чат бўлса, буйруқни бекор қиламиз
    if chat.type == "private":
        await update.message.reply_text("❌ Бу буйруқ фақат гуруҳда ишлайди.")
        return

    chat_id = chat.id
    commd = update.message

    chat_member = await context.bot.get_chat_member(chat_id, user_id)
    if chat_member.status not in ["administrator", "creator"]:
        try:
            await commd.delete()
        except Exception:
            pass
        return 

    conn = get_db_connection()
    cursor = conn.cursor()

    total_users = await context.bot.get_chat_member_count(chat_id)  # 📌 Гуруҳдаги реал юзерлар сони

    # 📌 Ўртача таклифлар сонини ҳисоблаш
    cursor.execute("""
        SELECT AVG(refer_count)  -- Ўртача таклифлар сони
        FROM users  -- Фойдаланувчилар жадвали
        WHERE chat_id=?  -- Гуруҳ IDси
    """, (chat_id,))
    avg_refer = cursor.fetchone()[0] or 0

    # ✅ Гуруҳда қолган аъзоларни олиш (фаол фойдаланувчилар)
    cursor.execute("""
        SELECT user_id  -- Фойдаланувчи ID
        FROM users  -- Фойдаланувчилар жадвали
        WHERE chat_id=? AND is_active=1  -- Гуруҳда қолган аъзолар
    """, (chat_id,))
    active_members = {row[0] for row in cursor.fetchall()}  # Гуруҳда қолганлар set() кўринишида

    # ✅ Гуруҳда қолган ва таклиф қилинган фойдаланувчиларни ҳисоблаш
    cursor.execute("""
        SELECT invited_by, COUNT(user_id)  -- Таклиф қилинган фойдаланувчилар
        FROM users  -- Фойдаланувчилар жадвали
        WHERE chat_id=?  -- Гуруҳ IDси
            AND is_active=1  -- Фаол аъзолар
            AND invited_by IS NOT NULL  -- Таклиф қилган фойдаланувчилар
        GROUP BY invited_by  -- Таклиф қилган фойдаланувчиларни гуруҳлаш
        ORDER BY COUNT(user_id) DESC  -- Таклифлар сони бўйича тартиблаш
    """, (chat_id,))
    
    all_top_users = cursor.fetchall()
    top_users = [(uid, count) for uid, count in all_top_users if uid in active_members]

    top_users_text = ""
    for i, (uid, count) in enumerate(top_users[:5], start=1):
        try:
            user = await context.bot.get_chat(uid)
            user_name = user.first_name if user.first_name else "Номаълум"
        except Exception:
            user_name = "Номаълум"

        top_users_text += f"{i}. <a href='tg://user?id={uid}'>{user_name}</a> - {count} та таклиф\n"

    # ✍️ Хабар ёзиш ҳуқуқига эга фойдаланувчилар сони
    cursor.execute("""
        SELECT COUNT(*)  -- Хабар ёзиш ҳуқуқига эга фойдаланувчилар
        FROM users  -- Фойдаланувчилар жадвали
        WHERE chat_id=?  -- Гуруҳ IDси
            AND write_access = 1  -- Хабар ёзиш ҳуқуқига эга
    """, (chat_id,))
    can_write_users = cursor.fetchone()[0]

    conn.close()

    stats_text = (f"📊 <b>Гуруҳ статистикаси:</b>\n\n"
                  f"👥 Жами фойдаланувчилар: <b>{total_users}</b>\n"
                  f"📈 Ўртача таклифлар: <b>{avg_refer:.1f}</b>\n"
                  f"✍️ Хабар ёзиш ҳуқуқига эга: <b>{can_write_users}</b>\n\n"
                  f"{'🏆 <b>Энг фаол иштирокчилар:</b>\n' + top_users_text if top_users_text else ''}") 

    statistik = await update.message.reply_text(stats_text, parse_mode="HTML")

    await asyncio.sleep(5)
    try:
        await commd.delete()
        await statistik.delete()
    except Exception:
        pass

async def remove_left_members(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Гуруҳдан чиқиб кетганларни текшириш ва уларни referral рўйхатидан чиқариш."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # БАЗАДАН ҲАММА РЕФЕРАЛЛАРНИ ОЛАМАН
            cursor.execute("SELECT user_id FROM users")
            all_users = cursor.fetchall()

            for user in all_users:
                user_id = user[0]

                try:
                    member = await context.bot.get_chat_member(chat_id, user_id)  # ✅ TUZATILDI
                    if member.status in ["left", "kicked"]:  
                        # Agar foydalanuvchi chiqib ketgan bo‘lsa
                        cursor.execute("UPDATE users SET refer_count = refer_count - 1 WHERE user_id=?", (user_id,))
                        conn.commit()
                        print(f"❌ {user_id} chiqib ketgan! refer_count kamaytirildi!")
                except Exception:
                    pass  # Agar xato bo‘lsa, bot ishdan chiqmasin

    except sqlite3.Error as e:
        print(f"❌ remove_left_members({chat_id}): Xatolik yuz berdi: {e}")

async def get_real_refer_count(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Фойдаланувчи таклиф қилганлардан фақат гуруҳда қолганлар сонини ҳисоблайди."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # ✅ Foydalanuvchi taklif qilgan barcha user_id larni olish
            cursor.execute("SELECT user_id FROM users WHERE invited_by=?", (user_id,))
            invited_users = cursor.fetchall()

            if not invited_users:
                return 0  # Taklif qilingan foydalanuvchilar yo‘q

            real_count = 0

            # ✅ Har bir taklif qilingan foydalanuvchini tekshirish
            for (invited_id,) in invited_users:
                try:
                    member = await context.bot.get_chat_member(chat_id, invited_id)
                    if member.status in ["member", "administrator"]:  # ✅ Faqat guruhda qolganlarni hisoblash
                        real_count += 1
                except Exception:
                    pass  # Agar foydalanuvchini topa olmasa, davom etamiz

            return real_count

    except sqlite3.Error as e:
        print(f"❌ get_real_refer_count({chat_id}, {user_id}): Xатолик: {e}")
        return 0

# ✅ Менинг таклифларимни кўриш
async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user  # ✅ `.from_user` o‘rniga universal ishlaydi
    chat = update.effective_chat  # ✅ Chat ID olish uchun
    message = update.message or update.callback_query.message  # ✅ Xatolikni oldini olish

    user_id = user.id
    chat_id = chat.id
    first_name = user.first_name

    conn = get_db_connection()
    cursor = conn.cursor()

    # ✅ Фақат гуруҳда қолган таклиф этилганларни ҳисоблаш
    cursor.execute("""
        SELECT COUNT(*) 
        FROM users 
        WHERE invited_by=? AND chat_id=? AND is_active=1
    """, (user_id, chat_id))
    refer_count = cursor.fetchone()[0] or 0  # None бўлса 0

    # ✅ Ёзиш ҳуқуқи берилган фойдаланувчиларни ҳисоблаш
    cursor.execute("""
        SELECT COUNT(*) 
        FROM users 
        WHERE invited_by=? AND chat_id=? AND is_active=1 AND write_access=1
    """, (user_id, chat_id))
    write_access = cursor.fetchone()[0] or 0  # None бўлса 0

    conn.close()

    if write_access == 0:
        access_message = "❌ Сизга ёзиш ҳуқуқи берилмаган!"
    else:
        access_message = "✅ Сизга ёзиш ҳуқуқи берилган!"

    mssg = await update.message.reply_text(f"👤 {first_name}, Сиз таклиф қилганлар сони: <b>{refer_count} та!</b> 📊\n{access_message}", parse_mode="HTML")

#    mssg = await update.message.reply_text(
#        f"👤 {first_name}, Сиз таклиф қилганлар сони: <b>{refer_count} та!</b> 📊\n"
#        f"{'❌ Сизга ёзиш ҳуқуқи берилмаган!\n' if write_access == 0 else '✅ Сизга ёзиш ҳуқуқи берилган!\n'}", 
#        parse_mode="HTML"
#    )
    try:
        await message.delete()
    except Exception:
        pass

    await asyncio.sleep(5)
    try:
        await mssg.delete()
    except Exception:
        pass

    return

# ✅ Ботни инициализация қилиш
app = Application.builder().token(TOKEN).build() # Ботни инициализация қиламиз
job_queue = app.job_queue  # JobQueue'ни инициализация қиламиз

# 🛠 Админ панелини ўчириш функцияси
# Лимитни ўзгартириш тугмасини ўчириш
async def delete_set_limit(context: ContextTypes.DEFAULT_TYPE):  # JobQueue'дан фойдаланиш
    job_data = context.job.data  # JobQueue'дан маълумот оламиз
    chat_id = job_data["chat_id"]  # Гуруҳ ID'си
    message_id = job_data.get("message_id")  # Хабар ID'си

    if not message_id:  # Агар `message_id` йўқ бўлса,
        return  # функцияни тугатамиз
    
    try: # Хабарни ўчириш
        await context.bot.delete_message(chat_id, message_id) # Гуруҳ ID'си ва хабар ID'си орқали ўчириш
    except Exception as e: # Агар хатолик бўлса,
        print(f"❌ Лимитни ўзгартириш тугмасини ўчиришда хатолик: {e}")

MIN_REFER = 5  # Стандарт минимал реферал лимити

# Лимитни ўзгартириш тугмасини юбориш
async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
    commd = update.message  # Фойдаланувчи буйруғини олиш

    print(f"👤 {user_id} админ панел очишга уринаяпти...")  # DEBUG

    chat_member = await context.bot.get_chat_member(chat_id, user_id) # if user_id not in admin_ids:

    if chat_member.status not in ["administrator", "creator"]:
        msg = await update.message.reply_text("❌ Сиз админ эмассиз!")
        await asyncio.sleep(5)  # 5 сония кутиш
        try:
            await commd.delete()  # Буйруқни ўчириш
            await msg.delete()  # Хабарни ўчириш
        except Exception:
            pass  # Агар хабар йўқ бўлса, бот ишдан чиқмасин
        return  # Агар админ бўлмаса, чиқиб кетамиз

     # Лимитни ўзгартириш тугмаси
    print("✅ Лимит панел юборилмоқда...")  # DEBUG
    keyboard = [
        [InlineKeyboardButton("🔄 Лимитни ўзгартириш", callback_data="change_limit")],
        [InlineKeyboardButton("🚫 Панелни ёпиш", callback_data="close_panel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    admin_msg = await update.message.reply_text("⚙️ Лимит панел:", reply_markup=reply_markup)

    # 15 сониядан кейин хабарни ўчириш учун JobQueue'дан фойдаланиш
    context.job_queue.run_once(delete_set_limit, 15, data={"chat_id": chat_id, "message_id": admin_msg.message_id})

CUSTOM_LIMIT = range(1)  # 🔹 Фойдаланувчи рақам киритишини кутиш ҳолати

def generate_limit_keyboard(current_limit):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📌 Жорий лимит: {current_limit} одам", callback_data="none")],
        [InlineKeyboardButton("➖ Озайтириш", callback_data="decrease_limit"),
         InlineKeyboardButton("➕ Кўпайтириш", callback_data="increase_limit")],
        [InlineKeyboardButton("✅ Тасдиқлаш", callback_data="confirm_limit")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_limit")]
    ])

# ✅ Лимитни озайтириш ва кўпайтириш
async def adjust_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id  # 🔹 Чат ID
    data = query.data  # Фойдаланувчи босган тугма маълумотини оламиз

    # Фойдаланувчининг жорий лимитини context.user_data'да сақлаш
    if "temp_limit" not in context.user_data: # Агар "temp_limit" мавжуд бўлмаса, базадан оламиз
        context.user_data["temp_limit"] = get_refer_limit(chat_id)  # 📌 Базадан жорий лимитни олиш

    current_limit = context.user_data["temp_limit"] # Фойдаланувчининг жорий лимити

    if data == "increase_limit":
        context.user_data["temp_limit"] = current_limit + 1
    elif data == "decrease_limit":
        context.user_data["temp_limit"] = max(1, current_limit - 1)  # 🔹 Лимит 1 дан камаймаслиги керак
    elif data == "confirm_limit":
        set_refer_limit(chat_id, context.user_data["temp_limit"])  # ✅ Базага сақлаймиз
        await query.message.edit_text(f"✅ Янги лимит белгиланди: {context.user_data['temp_limit']} одам")
        del context.user_data["temp_limit"]  # ✅ Кечиктирилган маълумотни ўчириш
        return  # ✅ Функцияни тугатамиз
    elif data == "cancel_limit": # ❌ Бекор қилиш босилганда
        await query.message.edit_text(f"Лимит ўзгартирилмади. Жорий чеклов: {current_limit} одам")
        return # ❌ Функцияни тугатамиз

    new_limit = context.user_data["temp_limit"]
    reply_markup = generate_limit_keyboard(new_limit)

    await query.answer(f"Таклиф чеклови {new_limit} га ўзгартирилди!")  # ✅ Фойдаланувчига хабар юбориш
    await query.message.edit_reply_markup(reply_markup=reply_markup) # ✅ Клавиатурани янгилаш

# ✅ Фойдаланувчи юборган рақамни қабул қилиш
async def set_custom_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        limit = int(update.message.text)  # 🔹 Фойдаланувчининг рақам юборганини текшириш
        if limit <= 0:
            await update.message.reply_text("❌ Лимит мусбат сон бўлиши керак! Қайта уриниб кўринг:")
            return CUSTOM_LIMIT  # 🔹 Яна рақам киритишни кутиш

        set_refer_limit(limit)  # ✅ Лимитни сақлаш
        await update.message.reply_text(f"✅ Гуруҳ учун минимал таклиф чеклови {limit} қилиб ўрнатилди!")
        return ConversationHandler.END  # 🔹 Мулоқотни якунлаш

    except ValueError:
        await update.message.reply_text("❌ Нотўғри формат! Илтимос, рақам киритинг:")
        return CUSTOM_LIMIT  # 🔹 Яна рақам киритишни кутиш

# ✅ Мулоқотни бекор қилиш (Фойдаланувчи рақам киритмаса)
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Лимитни ўзгартириш бекор қилинди.")
    return ConversationHandler.END

async def ask_write_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.message.edit_text("🔢 Илтимос, янги минимал таклиф чекловини рақам сифатида юборинг:")
    return CUSTOM_LIMIT  # ✅ Фойдаланувчининг жавобини кутиш

# ✅ Бошқарув тугмачаларини созлаш
conv_handler = ConversationHandler( 
    entry_points=[CallbackQueryHandler(ask_write_limit, pattern="^write_limit$")],
    states={
        CUSTOM_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_custom_limit)],
    },
    fallbacks=[CommandHandler("cancel", cancel)]
)

# гуруҳдаги ҳақиқий админларни аниқлайди
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Фойдаланувчи гуруҳ админи эканлигини текшириш."""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    admins = await context.bot.get_chat_administrators(chat_id)

    return any(admin.user.id == user_id for admin in admins)

# Танланган чекловни сақлаш
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id  # 📌 Гуруҳ ID'сини оламиз
    data = query.data
    print(f"🔹 Callback келди: {data} | Chat ID: {chat_id}")  # DEBUG учун

    if not query.message:
        await query.answer("⚠ Хатолик: Ҳабар топилмади!", show_alert=True)
        return  # Агар хабар мавжуд бўлмаса, функцияни тўхтатамиз
    
    # Лимитни танлаш тугмаларини чиқариш
    if data == "change_limit":

        # Рақамли танлов тугмалари ва "Бошқа рақам танлаш"
        keyboard = [
            [InlineKeyboardButton("5", callback_data="limit_5"),
            InlineKeyboardButton("10", callback_data="limit_10")],
            [InlineKeyboardButton("15", callback_data="limit_15"),
            InlineKeyboardButton("20", callback_data="limit_20")],
            [InlineKeyboardButton("🔢 Бошқа рақам танлаш", callback_data="custom_limit")],
            [InlineKeyboardButton("Қўлда рақам киритиш", callback_data="write_limit")],
            [InlineKeyboardButton("🚫 Панелни ёпиш", callback_data="close_panel")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await query.message.edit_text("Гуруҳ учун минимал таклиф чекловини танланг:", reply_markup=reply_markup)
        except Exception as e:
            print(f"❌ Хабарни таҳрир қилишда хатолик: {e}")
            await query.answer("⚠ Хабар таҳрир қилиб бўлмайди!", show_alert=True)

    # ✅ "write_limit" танланганда ask_write_limit'ни ишга тушурамиз
    if data == "write_limit":
        await ask_write_limit(update, context)  # Фойдаланувчидан рақам киритишни сўраймиз
        return  # Функцияни тугатамиз

    # Панелни ўчириш
    if data == "close_panel":
        try:
            await query.message.delete()
            await query.answer("Панел ёпилди! ✅", show_alert=False)
        except Exception as e:
            print(f"❌ Панелни ёпишда хатолик: {e}")
        return
    
    # ✅ 5, 10, 15, 20 танловлари ишламаса, ушбу қисми текширилади
    if data.startswith("limit_"):
        try:
            #limit = int(data.split("_")[1])
            _, limit_value = data.split("_")
            limit = int(limit_value)
            print(f"✅ Танланган лимит: {limit}")  # DEBUG
            context.user_data["temp_limit"] = limit  # 📌 Фойдаланувчи танлаган лимитни сақлаймиз
            set_refer_limit(chat_id, limit)  # 📌 Гуруҳ ID бўйича чекловни сақлаймиз
            await query.answer(f"Таклиф чеклови {limit} қилиб ўрнатилди!")
            await query.message.edit_text(f"Гуруҳ учун минимал таклиф чеклови: {limit} одам")
        except Exception as e:
            print(f"❌ Лимитни сақлашда хатолик: {e}")
        return

    # "Бошқа рақам танлаш" логикаси
    if data == "custom_limit":
        limit = get_refer_limit(chat_id)  # 📌 Гуруҳ ID бўйича чекловни оламиз

        if "temp_limit" not in context.user_data:  # Агар мавжуд бўлмаса, базадан оламиз
            context.user_data["temp_limit"] = get_refer_limit(chat_id)  

        keyboard = [
            [InlineKeyboardButton(f"📌 Жорий лимит: {context.user_data['temp_limit']} одам", callback_data="none")],
            [InlineKeyboardButton("➖ Озайтириш", callback_data="decrease_limit"),
             InlineKeyboardButton("➕ Кўпайтириш", callback_data="increase_limit")],
            [InlineKeyboardButton("✅ Тасдиқлаш", callback_data="confirm_limit")],
            [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_limit")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # **📌 Фақат клавиатурани янгилаймиз, матн ўзгармайди!**
        await query.message.edit_reply_markup(reply_markup=reply_markup)

# Лимитни базада сақлаш
def set_refer_limit(chat_id: int, limit: int):
    """Settings жадвалида `min_refer` қийматини янгилайди. Агар мавжуд бўлмаса, қўшади."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # `settings` жадвалида chat_id мавжудлигини текшириш
            cursor.execute("SELECT COUNT(*) FROM settings WHERE chat_id=?", (chat_id,))
            exists = cursor.fetchone()[0] > 0  

            if exists:
                cursor.execute("UPDATE settings SET min_refer=? WHERE chat_id=?", (limit, chat_id))
            else:
                cursor.execute("INSERT INTO settings (chat_id, min_refer) VALUES (?, ?)", (chat_id, limit))  

            conn.commit()
            print(f"✅ {chat_id} учун чеклов {limit} га ўрнатилди!")  

    except sqlite3.Error as e:
        print(f"❌ set_refer_limit(): Xatolik yuz berdi: {e}") 

# Базадан минимал таклиф чекловини олиш
def get_refer_limit(chat_id: int) -> int:
    """Settings жадвалидан `min_refer` қийматини олади. Агар мавжуд бўлмаса, `MIN_REFER` қайтаради."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT min_refer FROM settings WHERE chat_id=?", (chat_id,))  
            result = cursor.fetchone()
            
            return int(result[0]) if result and result[0] is not None else MIN_REFER  

    except sqlite3.Error as e:
        print(f"❌ get_refer_limit({chat_id}): Xатолик юз берди: {e}")  
        return MIN_REFER

# Базага одамни қўшиш ёки янгилаш
def add_referral(user_id, chat_id, invited_by):
    """Янги таклифни базага қўшиш."""
    print(f"🔍 add_referral() ishladi: user_id={user_id}, chat_id={chat_id}, invited_by={invited_by}")  # ✅ LOG

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # ⚡ Гуруҳни базага қўшамиз, агар у йўқ бўлса
            add_group_to_db(chat_id)

            

           # 📌 Фойдаланувчи базада бор ёки йўқлигини текшириш
            cursor.execute("""
                    SELECT user_id 
                    FROM users 
                    WHERE user_id=? 
                        AND chat_id=?
                """,  (user_id, chat_id))
            exists = cursor.fetchone()

            if not exists: # 📌 Агар фойдаланувчи базада йўқ бўлса, қўшамиз
                cursor.execute("""
                    INSERT INTO users (user_id, chat_id, refer_count, write_access, invited_by) 
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, chat_id, 0, 0, invited_by))
                conn.commit()  # Маълумотлар тўғри сақланганини текширинг

            # 📌 Таклиф қилинганлар сонини фақат гуруҳда қолганлар орқали ҳисоблаш
            cursor.execute("""
                SELECT COUNT(*) 
                FROM users 
                WHERE invited_by=? 
                    AND chat_id=?
                    AND write_access=1
            """, (invited_by, chat_id))
            refer_count = cursor.fetchone()[0]

            print(f"🔹 REFER COUNT: {refer_count}")  # Лог: Refer count

            required_refs = get_refer_limit(chat_id)  # ✅ Гуруҳ ID бўйича minimal referral олиш
            write_access = int(refer_count >= required_refs)  # ✅ 1 ёки 0

            # 📌 Таклиф қилган фойдаланувчининг маълумотларини янгилаш
            cursor.execute("""
                UPDATE users 
                SET refer_count=?, write_access=? 
                WHERE user_id=? 
                    AND chat_id=?
            """, (refer_count, write_access, invited_by, chat_id))
            conn.commit()  # Маълумотлар тўғри сақланганини текширинг

            print(f"✅ {invited_by} учун таклифлар сони: {refer_count} (лимит: {required_refs})")

    except sqlite3.Error as e:
        print(f"❌ add_referral({user_id}): Xатолик yuz berdi: {e}")  # ✅ Хатоларни логга чиқарамиз

# Гуруҳга янги одам қўшилганда
async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):  
    print("🔹 `new_member` ФУНКЦИЯСИ ЧАҚИРИЛДИ!")  
    #print(f"🔹 new_member чақирилди: {update}") # ТЕГИШЛИ ХАБАРЛАРНИ ЛОГГА ЧИҚАРАМИЗ

    if update.message and update.message.new_chat_members:
        new_user = update.message.new_chat_members[0]  # ✅ Янги қўшилган фойдаланувчи
        new_user_id = new_user.id  # 📌 Фойдаланувчи ID
        chat_id = update.message.chat_id  # 📌 Гуруҳ ID
        inviter_id = update.message.from_user.id  # ✅ Таклиф қилган шахснинг ID

        print(f"👤 Янги аъзо ID: {new_user_id}, Таклиф қилган ID: {inviter_id}, Гуруҳ ID: {chat_id}")

        # ✅ add_referral() функциясини тўғри чақириш
        add_referral(user_id=new_user_id, invited_by=inviter_id, chat_id=chat_id)

        await delete_join_message(update, context)  # ✅ Хабарни ўчириш

# Гуруҳга қўшилиш ва чиқиш хабарларини ўчириш
async def delete_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🔹 `delete_join_message` ФУНКЦИЯСИ ЧАҚИРИЛДИ!")  # ✅ DEBUG учун 
    await asyncio.sleep(1)  # 1 сония кутиш, Ошиб кетишга қарши кечикиш қўшамиз
    # print(f"🔹 delete_join_message чақирилди: {update}")

    if update.message: # Агар хабар мавжуд бўлса,
        print("🗑 Хабар ўчирилмоқда...")  # ✅ DEBUG учун  
        try:
            await update.message.delete()  # ✅ Хабарни ўчириш
        except Exception as e:
            print(f"❌ Хабар ўчиришда хатолик: {e}")  # ✅ Агар ўчмаётган бўлса, сабабини билиш учун логга чиқарамиз
#    await update.message.delete() # Гуруҳга қўшилганда хабарни ўчириш
    else:
        print("❌ Хабар мавжуд эмас!")  # Агар хабар мавжуд бўлмаса, логга чиқарамиз

# Фойдаланувчининг ёзиш ҳуқуқини текшириш
def check_write_access(user_id, chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Гуруҳ учун минимал таклифлар сонини оламиз
    cursor.execute("""
        SELECT min_refer 
        FROM settings 
        WHERE chat_id = ?
    """, (chat_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        return False  # Агар гуруҳ базада бўлмаса, ёзишни чеклаймиз
    
    min_refer = row[0]  # Минимал таклифлар сони

    # Фойдаланувчи таклифларини текшириш
    cursor.execute("""
        SELECT refer_count, write_access 
        FROM users 
        WHERE user_id = ?
    """, (user_id,))
    user_row = cursor.fetchone()
    
    conn.close()

    if user_row is None:
        return False  # Агар фойдаланувчи базада бўлмаса, ёзишни чеклаймиз

    refer_count = user_row[0]
    write_access = user_row[1]  # Фойдаланувчининг ёзиш ҳуқуқи

    # Агар таклифлар етарли бўлса ва ёзиш ҳуқуқи берилмаган бўлса
    if refer_count >= min_refer and write_access == 0:
        update_write_access(user_id, chat_id, True)  # Ёзиш ҳуқуқини бериш
        return True

    return write_access == 1  # Агар ёзиш ҳуқуқи берилган бўлса, true қайтарамиз

# ✅ Фойдаланувчининг таклифларини текшириш    
def get_refer_count(user_id: int, chat_id: int):
    """Фойдаланувчи таклифлари сонини олиш."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT refer_count 
                FROM users 
                WHERE user_id=? 
                    AND chat_id=?
            """, (user_id, chat_id))
            refer_count = cursor.fetchone()
            if refer_count is None:
                print(f"❌ {user_id} учун таклифлар сони мавжуд эмас.")
                return 0  # Агар маълумот бўлмаса, 0 қайтариш
            return refer_count[0]

    except sqlite3.Error as e:
        print(f"❌ get_refer_count({user_id}): Хатолик yuz berdi: {e}")
        return 0  # Хатолик бўлса ҳам 0 қайтариш

# ✅ Ҳар бир хабар келганда анти-флудни текшириш
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ✅ Фақатгина оддий хабарлар учун ишлайди
    if update.message is not None:
        await anti_flood(update, context)  # ✅ Анти-флуд тизими

    if update.message.from_user.id == context.bot.id: # Ботнинг ўз хабарини текшириш
        return  

    user_id = update.message.from_user.id  
    chat_id = update.effective_chat.id  
    user_name = update.message.from_user.first_name  

    chat_member = await context.bot.get_chat_member(chat_id, user_id)

    # ⚡ Гуруҳни базага қўшамиз, агар у йўқ бўлса
    add_group_to_db(chat_id)
    print(f"❌ def handle_message: {user_id} | Chat ID: {chat_id}")  # DEBUG

    if chat_member.status in ["administrator", "creator"]:
        return # Агар админ бўлса, функцияни тугатамиз

    if user_id == CREATOR_ID:
        return  # Хусусан, ботни ишлатувчи ижодкорни текширмаслик

    # Фойдаланувчининг таклифлар сони
    refer_count = get_refer_count(user_id, chat_id)

    # Гуруҳ учун минимал чеклов
    required_refs = get_refer_limit(chat_id)

    # ✅ Фойдаланувчи ёзиш ҳуқуқига эгалигини текширамиз
    if refer_count < required_refs:
        remaining = required_refs - refer_count  

        mention = f'<a href="tg://user?id={user_id}">{user_name}</a>'  

        try:
            await update.message.delete()  
            warning_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"Ҳурматли {mention},\n"
                    f"Гуруҳда хабар ёзиш учун \n"
                    f"таклифлар сони {refer_count}, лимит {required_refs}!\n"
                    f"яна {remaining} та одам қўшинг.",  
                parse_mode=ParseMode.HTML  
            )
            await asyncio.sleep(5) 
            await warning_msg.delete()  
            return
        except Exception as e:
            print(f"❌ Хабарни ўчиришда хатолик: {e}")

# ✅ Ёзиш ҳуқуқини қўлда ўзгартириш учун буйруқ қўшиш
async def update_write_access(user_id: int, chat_id: int, access: bool):
    """Фойдаланувчига ёзиш рухсатини бериш ёки олиб ташлаш."""
    try:
        async with get_db_connection() as conn:
            cursor = conn.cursor()

            # 🛠 Фойдаланувчи базада бор-йўқлигини текшириш
            await cursor.execute("SELECT 1 FROM users WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            #cursor.execute("""
            #        UPDATE users 
            #        SET write_access = ? 
            #        WHERE user_id = ? 
            #            AND chat_id = ?
            #    """, (int(access), user_id, chat_id))
            exists = cursor.fetchone()

            if exists:  # ✅ Агар фойдаланувчи базада бўлса, `write_access` янгиланади
                await cursor.execute("""
                        UPDATE users 
                        SET write_access=? 
                        WHERE user_id=? 
                            AND chat_id=?
                    """, (int(access), user_id, chat_id))
            else:  # ✅ Агар йўқ бўлса, янги ёзув қўшилади
                await cursor.execute("""
                        INSERT INTO users (user_id, chat_id, write_access) 
                        VALUES (?, ?, ?)
                    """, (user_id, chat_id, int(access)))

            await conn.commit()  # ✅ Базани сақлаш
    except sqlite3.Error as e:
        print(f"❌ update_write_access(): Xатолик юз берди: {e}")  # ✅ Хатоларни чоп этиш

# 📌 Фойдаланувчига ёзиш ҳуқуқини бериш
async def grant_write(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📌 Админ фойдаланувчига ёзиш ҳуқуқи беради."""
    chat_id = update.effective_chat.id
    user_id = None

    # 🔹 Агар фойдаланувчига жавоб берилган бўлса, уни ID'сини оламиз
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    # 🔹 Агар буйруқ билан ID берилган бўлса, уни текширамиз
    elif context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Нотўғри ID формати! Илтимос, рақам киритинг.")
            return
    # 🔹 Агар ID ҳам, жавоб ҳам берилмаган бўлса
    else:
        await update.message.reply_text("❌ Илтимос, фойдаланувчини жавоб орқали ёки ID билан юборинг!")
        return

    # 📌 Фойдаланувчига ёзиш ҳуқуқини бериш
    update_write_access(user_id, chat_id, True)

    # ✅ Жавоб хабарини юбориш
    user_mention = f"<a href='tg://user?id={user_id}'>{html.escape(str(user_id))}</a>"
    await update.message.reply_text(
        f"✅ {user_mention} га ёзиш ҳуқуқи берилди!", 
        parse_mode="HTML"
    )

# 📌 Фойдаланувчига ёзиш ҳуқуқини бекор қилиш
async def revoke_write(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ фойдаланувчидан ёзиш ҳуқуқини олиб ташлайди"""
    chat_id = update.effective_chat.id
    user_id = None

    # 🔹 Агар фойдаланувчига жавоб берилган бўлса, уни ID'сини оламиз
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    # 🔹 Агар буйруқ билан ID берилган бўлса, уни текширамиз
    elif context.args:
        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Нотўғри ID формати! Илтимос, рақам киритинг.")
            return
    # 🔹 Агар ID ҳам, жавоб ҳам берилмаган бўлса
    else:
        await update.message.reply_text("❌ Илтимос, фойдаланувчини жавоб орқали ёки ID билан юборинг!")
        return

    # 📌 Фойдаланувчига ёзиш ҳуқуқини бекор қилиш
    update_write_access(user_id, chat_id, False)

    # ✅ Жавоб хабарини юбориш
    user_mention = f"<a href='tg://user?id={user_id}'>{html.escape(str(user_id))}</a>"
    await update.message.reply_text(
        f"🚫 {user_mention} дан ёзиш ҳуқуқи олиб ташланди!", 
        parse_mode="HTML"
    )

# 🛠 3️⃣ Гуруҳга юборилган Ҳаволаларни автоматик ўчириш
async def delete_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ҳавола бор-йўқлигини REGEX билан текшириш
    if re.search(r"(https?:\/\/[^\s]+|t\.me\/[a-zA-Z0-9_]+)", update.message.text, re.IGNORECASE):
        try:
            await update.message.delete()
        except Exception as e:
            print(f"❌ Хабарни ўчиришда хатолик: {e}")

        await update.message.reply_text("🚫 Гуруҳда ҳаволаларни юбориш мумкин эмас!")

# Буйруқларга жавоб қайтаргандан сўнг уларни ва жавоб хабарни ўчириш
async def command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text

    # Жавоб хабарини юбориш
    response_message = await update.message.reply_text(f"Ҳозирда {command} буйруғини мавжуд эмас!")

    await update.message.delete()  # Буйруқ хабарини ўчириш

    await asyncio.sleep(5)  # 5 сонияда ўчириш
    try:
        await response_message.delete()  # Жавоб хабарини ўчириш
    except Exception as e:
        print(f"❌ Хабарни ўчиришда хатолик: {e}")

# Ботни ишга тушириш
def main():
    init_db()  # ✅ SQL жадвалини яратиш **ФАҚАТ БИР МАРТА**

    # 📌 Ботни инициализация қилиш
    app = Application.builder().token(TOKEN).build()

    # 🔹 Бошланғич команда
    app.add_handler(CommandHandler("start", start))

    app.add_handler(CommandHandler("chatid", get_chat_info))

    # 📌 Буйруқни қўшиш
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.add_handler(CommandHandler("startbroadcast", start_broadcast))

    # 🔹 Статистика буйруғини қўшиш
    app.add_handler(CommandHandler("stats", stats))
    
    # 🔹 /stats буйруғини қўшиш
    app.add_handler(CommandHandler("groupstats", group_stats, filters=filters.ChatType.GROUPS))

    #app.add_handler(CommandHandler("stats", user_stats, filters=filters.ChatType.PRIVATE))

    # 🔹 Менинг таклифларим буйруғи
    app.add_handler(CommandHandler("myreferrals", my_referrals))
    
    # 🔹 Лимит панел
    app.add_handler(CommandHandler("set_limit", set_limit, filters=filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)) # Бу ботни фақат гуруҳда ишлашига чеклов қўяди.

    # ✅ Ёзиш ҳуқуқини қўлда ўзгартириш учун буйруқ қўшиш
    app.add_handler(CommandHandler("grantwrite", grant_write))
    app.add_handler(CommandHandler("revoke", revoke_write))

    # 🔹 Янги аъзо хабарларини текшириш
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))

    # 🔹 Чиқиш хабарини ўчириш
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, delete_join_message))  

    # app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, delete_join_message))  # Янги аъзо хабарини ўчириш
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message))

    # Барча буйруқларни ушлаб оладиган хэндлер
    app.add_handler(MessageHandler(filters.COMMAND, command_handler))

    app.add_handler(ChatMemberHandler(handle_chat_member_update))

    # 🔹 Бошқарув тугмалари
    #app.add_handler(CallbackQueryHandler(button_handler))  

    app.add_handler(conv_handler)

    # "Бошқа рақам танлаш" тугмаси учун хэндлер
    app.add_handler(CallbackQueryHandler(button_handler, pattern=r"^(limit_\d+|change_limit|custom_limit|write_limit|close_panel)$"))

    # "Кўпайтириш", "Озайтириш" ва "Бекор қилиш" тугмалари учун хэндлер
    app.add_handler(CallbackQueryHandler(adjust_limit, pattern="^(increase_limit|decrease_limit|confirm_limit|cancel_limit)$"))

    # 🔹 Ҳаволаларни ўчириш фильтрлари
    link_filter = filters.TEXT & filters.Regex(r"(https?://[^\s]+|t\.me/[^\s]+)")
    app.add_handler(MessageHandler(link_filter, delete_invite_link))
    app.add_handler(MessageHandler(filters.Entity("url"), delete_invite_link))

    # 🔹 Охирида барча матнли хабарларни ишловчи ҳандлер
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Бот ишга тушди!")
    app.run_polling()

if __name__ == "__main__":
    main()
