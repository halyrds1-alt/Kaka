import logging
import httpx
import sqlite3
import asyncio
import os
import json
from datetime import datetime
from typing import Dict, Any, Tuple
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8979668811:AAHVemkoyYaTXnQpy2kOnzyKvi8dlb3efLw"
DEEPSCAN_TOKEN = "deepscan_6747528307:EbOVbwAg"
CHANNEL_URL = "https://t.me/Insightix"
SUPPORT_LINK = "https://t.me/bothkm"
ADMIN_ID = 6747528307

# Премиум эмодзи ID для кнопок
BTN_SEARCH = "5893382531037794941"      # 🔎 Искать
BTN_PROFILE = "5893161718179173515"     # ⚙️ Профиль
BTN_NEWS = "5258023599419171861"        # 🔧 Новости
BTN_SUPPORT = "5364052602357044385"     # 🐶 Поддержка
BTN_BACK = "5258328383183396223"        # ◀️ Назад

# Премиум эмодзи ID для текстовых сообщений
EMOJI_WELCOME = "5895713431264170680"
EMOJI_POINT = "5886676966102274844"
EMOJI_SEARCHING = "5429411030960711866"
EMOJI_WAIT = "5210838989921106328"
EMOJI_SUCCESS = "5843918217323484232"
EMOJI_INFO = "5258503720928288433"
EMOJI_STAR = "5895770017458294953"

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BOT_DIR, 'insightx.db')
PHOTO_PATH = os.path.join(BOT_DIR, 'menu.jpg')

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            reg_date TEXT,
            requests_today INTEGER DEFAULT 0,
            last_reset TEXT,
            total_requests INTEGER DEFAULT 0,
            subscribed_to_channel INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (ADMIN_ID,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, reg_date, last_reset, is_admin, subscribed_to_channel) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ADMIN_ID, "admin", "Admin", datetime.now().isoformat(), datetime.now().isoformat(), 1, 1)
        )
    
    conn.commit()
    conn.close()
    print(f"✅ База данных: {DB_PATH}")


def add_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, reg_date, last_reset) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, datetime.now().isoformat(), datetime.now().isoformat())
        )
    conn.commit()
    conn.close()


def get_user_info(user_id: int) -> Dict:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, username, requests_today, total_requests, is_admin, subscribed_to_channel FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "username": row[1],
            "requests_today": row[2],
            "total_requests": row[3],
            "is_admin": row[4] or 0,
            "subscribed_to_channel": row[5] or 0
        }
    return {"user_id": user_id, "requests_today": 0, "total_requests": 0, "is_admin": 0, "subscribed_to_channel": 0}


def check_subscribed_to_channel(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT subscribed_to_channel FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1


def mark_channel_subscribed(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET subscribed_to_channel = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def increment_request(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT requests_today, last_reset FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        requests_today, last_reset = row
        last_reset_date = datetime.fromisoformat(last_reset)
        
        if datetime.now().date() > last_reset_date.date():
            requests_today = 0
            last_reset = datetime.now().isoformat()
        
        if requests_today >= 50:
            conn.close()
            return False
        
        cursor.execute(
            "UPDATE users SET requests_today = ?, last_reset = ?, total_requests = total_requests + 1 WHERE user_id = ?",
            (requests_today + 1, last_reset, user_id)
        )
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, total_requests FROM users WHERE user_id != ?", (ADMIN_ID,))
    users = cursor.fetchall()
    conn.close()
    return users


def get_users_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE user_id != ?", (ADMIN_ID,))
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_total_requests():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(total_requests) FROM users WHERE user_id != ?", (ADMIN_ID,))
    result = cursor.fetchone()[0]
    conn.close()
    return result or 0


# ========== DEEPSCAN API ==========
async def deepscan_search(query: str) -> Tuple[bool, Dict[str, Any]]:
    clean_query = query.strip()
    url = "https://deepscan.cc/api/v1/search"
    payload = {"token": DEEPSCAN_TOKEN, "search": clean_query}
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return True, data
                return False, {"error": f'<tg-emoji emoji-id="{EMOJI_INFO}">❌</tg-emoji> Ничего не найдено'}
            return False, {"error": f'<tg-emoji emoji-id="{EMOJI_INFO}">❌</tg-emoji> Ошибка API: {response.status_code}'}
    except Exception as e:
        logger.error(f"DeepScan error: {e}")
        return False, {"error": f'<tg-emoji emoji-id="{EMOJI_INFO}">❌</tg-emoji> Ошибка: {str(e)}'}


# ========== HTML ОТЧЁТ ==========
def generate_html_report(data: Dict[str, Any], query: str) -> str:
    search_type = data.get('type', 'unknown')
    uuid = data.get('uuid', '—')
    links = data.get('links', [])
    possible_names = data.get('possible-names', [])
    full_result = data.get('full-result', [])
    banks_result = data.get('banks-result', [])
    additional = data.get('additional-result', {})
    registers = data.get('registers', [])
    telegram_data = data.get('telegram', {})
    fast_result = data.get('fast-result', {})
    
    phone_info = additional.get('phone_info', {})
    sources_count = len(full_result) + len(registers)
    
    all_names = []
    for name in possible_names:
        if name not in all_names:
            all_names.append(name)
    for item in full_result:
        if item.get('fio') and item['fio'] not in all_names:
            all_names.append(item['fio'])
        if item.get('full_name') and item['full_name'] not in all_names:
            all_names.append(item['full_name'])
    
    all_emails = []
    if fast_result.get('email'):
        emails = fast_result['email']
        if isinstance(emails, list):
            for e in emails:
                if '@' in str(e) and e not in all_emails:
                    all_emails.append(e)
    for item in full_result:
        if item.get('email') and item['email'] not in all_emails:
            all_emails.append(item['email'])
    
    all_phones = []
    if fast_result.get('phone'):
        phones = fast_result['phone']
        if isinstance(phones, list):
            for p in phones:
                if p not in all_phones:
                    all_phones.append(p)
    for item in full_result:
        if item.get('phone') and item['phone'] not in all_phones:
            all_phones.append(item['phone'])
    
    banks = []
    for bank in banks_result:
        if isinstance(bank, dict):
            banks.append(bank)
    
    tg_link = None
    tg_username = None
    if telegram_data:
        tg_username = telegram_data.get('username')
        if tg_username:
            tg_link = f"https://t.me/{tg_username}"
    
    birthday = fast_result.get('birthday', ['—'])[0] if fast_result.get('birthday') else '—'
    if isinstance(birthday, list):
        birthday = birthday[0] if birthday else '—'
    
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>InsightX | {query}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: linear-gradient(135deg, #0a0a0a 0%, #0d0d0d 100%);
            font-family: 'Segoe UI', -apple-system, sans-serif;
            padding: 20px;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 30px;
            background: linear-gradient(135deg, rgba(255,0,0,0.1), rgba(0,0,0,0.3));
            border-radius: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,0,0,0.3);
        }}
        .header h1 {{
            font-size: 2em;
            background: linear-gradient(135deg, #ff3333, #ff0000);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header i {{ color: #ff0000; margin: 0 10px; }}
        .query-card {{
            background: rgba(255,0,0,0.05);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,0,0,0.2);
        }}
        .query-card .value {{ font-size: 1.2em; color: #fff; word-break: break-all; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: rgba(255,0,0,0.05);
            border-radius: 16px;
            padding: 15px;
            text-align: center;
            border: 1px solid rgba(255,0,0,0.15);
        }}
        .stat-card i {{ font-size: 1.8em; color: #ff0000; margin-bottom: 8px; }}
        .stat-card .number {{ font-size: 1.5em; font-weight: 700; color: #ff3333; }}
        .section {{
            background: rgba(0,0,0,0.4);
            border-radius: 16px;
            margin-bottom: 12px;
            border: 1px solid rgba(255,0,0,0.1);
        }}
        .section-header {{
            padding: 12px 18px;
            background: rgba(255,0,0,0.08);
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            color: #ff3333;
            font-weight: 600;
            border-left: 3px solid #ff0000;
        }}
        .section-header i {{ margin-right: 8px; }}
        .section-content {{ padding: 15px 18px; border-top: 1px solid rgba(255,0,0,0.1); }}
        .section-content.collapsed {{ display: none; }}
        .item {{
            padding: 10px 0;
            border-bottom: 1px solid rgba(255,0,0,0.08);
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .item-key {{ width: 120px; color: rgba(255,255,255,0.5); }}
        .item-key i {{ width: 20px; margin-right: 8px; color: #ff0000; }}
        .item-value {{ flex: 1; color: #fff; word-break: break-word; }}
        .item-value a {{ color: #ff4444; text-decoration: none; }}
        .tag {{
            display: inline-block;
            background: rgba(255,0,0,0.1);
            padding: 5px 12px;
            border-radius: 20px;
            margin: 4px;
            font-size: 0.85em;
            color: #ff6666;
            border: 1px solid rgba(255,0,0,0.2);
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: rgba(255,255,255,0.3);
            font-size: 0.7em;
            border-top: 1px solid rgba(255,0,0,0.1);
            margin-top: 20px;
        }}
        @media (max-width: 600px) {{
            .stats {{ grid-template-columns: repeat(2, 1fr); }}
            .item {{ flex-direction: column; }}
            .item-key {{ width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><i class="fas fa-bolt"></i><h1>INSIGHT X</h1><i class="fas fa-brain"></i></div>
        <div class="query-card"><div class="value"><i class="fas fa-search"></i> ЗАПРОС: {query}</div><div style="margin-top: 8px; color: #666;">Тип: {search_type} | UUID: {uuid[:8]}...</div></div>
        <div class="stats">
            <div class="stat-card"><i class="fas fa-database"></i><div class="number">{sources_count}</div><div>Источников</div></div>
            <div class="stat-card"><i class="fas fa-link"></i><div class="number">{len(links)}</div><div>Связей</div></div>
            <div class="stat-card"><i class="fas fa-users"></i><div class="number">{len(all_names)}</div><div>Имён</div></div>
            <div class="stat-card"><i class="fas fa-building-columns"></i><div class="number">{len(banks)}</div><div>Банков</div></div>
        </div>
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fas fa-signal"></i> ИНФОРМАЦИЯ О НОМЕРЕ <i class="fas fa-chevron-down"></i></div>
        <div class="section-content">
            <div class="item"><div class="item-key"><i class="fas fa-flag"></i> Страна:</div><div class="item-value">{phone_info.get('country', '—')}</div></div>
            <div class="item"><div class="item-key"><i class="fas fa-tower-cell"></i> Оператор:</div><div class="item-value">{phone_info.get('operator', '—')}</div></div>
            <div class="item"><div class="item-key"><i class="fas fa-location-dot"></i> Регион:</div><div class="item-value">{phone_info.get('region', '—')}</div></div>
        </div></div>
        ''' if phone_info else ''}
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fas fa-users"></i> ВОЗМОЖНЫЕ ИМЕНА <i class="fas fa-chevron-down"></i></div>
        <div class="section-content">{''.join([f'<span class="tag"><i class="fas fa-tag"></i> {name}</span>' for name in all_names[:20]])}</div></div>
        ''' if all_names else ''}
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fas fa-envelope"></i> EMAIL АДРЕСА <i class="fas fa-chevron-down"></i></div>
        <div class="section-content">{''.join([f'<div class="item"><div class="item-key"><i class="fas fa-at"></i> Email:</div><div class="item-value"><a href="mailto:{email}">{email}</a></div></div>' for email in all_emails[:10]])}</div></div>
        ''' if all_emails else ''}
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fas fa-phone"></i> ТЕЛЕФОНЫ <i class="fas fa-chevron-down"></i></div>
        <div class="section-content">{''.join([f'<div class="item"><div class="item-key"><i class="fas fa-mobile-alt"></i> Номер:</div><div class="item-value">{phone}</div></div>' for phone in all_phones[:10]])}</div></div>
        ''' if all_phones else ''}
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fas fa-building-columns"></i> БАНКОВСКИЕ СЕРВИСЫ <i class="fas fa-chevron-down"></i></div>
        <div class="section-content">{''.join([f'<div class="item"><div class="item-key"><i class="fas fa-university"></i> {bank.get("bank", "Банк")}:</div><div class="item-value">{bank.get("name", "—")}</div></div>' for bank in banks[:15]])}</div></div>
        ''' if banks else ''}
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fab fa-telegram"></i> TELEGRAM <i class="fas fa-chevron-down"></i></div>
        <div class="section-content"><div class="item"><div class="item-key"><i class="fab fa-telegram"></i> Профиль:</div><div class="item-value"><a href="{tg_link}" target="_blank">@{tg_username}</a></div></div></div></div>
        ''' if tg_link else ''}
        {f'''
        <div class="section"><div class="section-header" onclick="toggleSection(this)"><i class="fas fa-link"></i> НАЙДЕННЫЕ СВЯЗИ <i class="fas fa-chevron-down"></i></div>
        <div class="section-content">{''.join([f'<div class="item"><div class="item-key"><i class="fas fa-external-link-alt"></i> Связь:</div><div class="item-value"><a href="{link}" target="_blank">{link}</a></div></div>' for link in links[:15]])}</div></div>
        ''' if links else ''}
        <div class="footer"><p><i class="fas fa-bolt"></i> INSIGHTX — профессиональный поиск информации <i class="fas fa-brain"></i></p><p><a href="{CHANNEL_URL}" target="_blank"><i class="fab fa-telegram"></i> @Insightix</a></p></div>
    </div>
    <script>function toggleSection(header){{const content=header.nextElementSibling;header.classList.toggle('collapsed');content.classList.toggle('collapsed');}}</script>
</body>
</html>'''
    return html


# ========== КЛАВИАТУРЫ С ПРЕМИУМ ЭМОДЗИ НА КНОПКАХ ==========
def get_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text="Искать",
            callback_data="main_start",
            icon_custom_emoji_id=BTN_SEARCH
        )],
        [
            InlineKeyboardButton(
                text="Профиль",
                callback_data="menu_profile",
                icon_custom_emoji_id=BTN_PROFILE
            ),
            InlineKeyboardButton(
                text="Новости",
                callback_data="menu_news",
                icon_custom_emoji_id=BTN_NEWS
            ),
            InlineKeyboardButton(
                text="Поддержка",
                callback_data="menu_support",
                icon_custom_emoji_id=BTN_SUPPORT
            ),
        ],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("⚙️ Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)


def get_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text="Назад",
            callback_data="main_menu",
            icon_custom_emoji_id=BTN_BACK
        )
    ]])


def get_channel_check_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Я подписался", callback_data="check_subscribe")],
        [InlineKeyboardButton("📢 Перейти на канал", url=CHANNEL_URL)],
    ])


def get_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")],
    ])


# ========== ОБРАБОТЧИКИ ==========
async def send_main_menu(chat_id: int, text: str, reply_markup, context):
    if os.path.exists(PHOTO_PATH):
        try:
            with open(PHOTO_PATH, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            return
        except:
            pass
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    
    add_user(user.id, user.username or "", user.first_name or "")
    
    if not check_subscribed_to_channel(user.id):
        text = f'''<tg-emoji emoji-id="{EMOJI_WELCOME}">✅</tg-emoji> <b>Добро пожаловать в InsightX, {user.first_name}!</b>

<blockquote>Получите полное представление: узнайте всё о людях, их контактах, связях, местоположении, имуществе и криминальном прошлом.</blockquote>

⚠️ <b>Для доступа подпишись на канал:</b>
{CHANNEL_URL}

<tg-emoji emoji-id="{EMOJI_POINT}">👆</tg-emoji> <b>После подписки нажми кнопку:</b>'''
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=get_channel_check_menu(), disable_web_page_preview=True)
        return
    
    user_info = get_user_info(user.id)
    is_admin = user_info.get("is_admin", False)
    
    text = f'''<tg-emoji emoji-id="{EMOJI_WELCOME}">✅</tg-emoji> <b>Добро пожаловать в InsightX, {user.first_name}!</b>

<blockquote>Получите полное представление: узнайте всё о людях, их контактах, связях, местоположении, имуществе и криминальном прошлом.</blockquote>

<tg-emoji emoji-id="{EMOJI_POINT}">👆</tg-emoji> <b>Используй кнопки:</b>'''
    if is_admin:
        text += "\n\n👑 <b>Вы вошли как АДМИНИСТРАТОР</b>"
    
    await send_main_menu(update.effective_chat.id, text, get_main_menu(is_admin), context)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_info = get_user_info(user_id)
    is_admin = user_info.get("is_admin", False)
    
    if query.data == "check_subscribe":
        mark_channel_subscribed(user_id)
        text = f'''<tg-emoji emoji-id="{EMOJI_SUCCESS}">✅</tg-emoji> <b>Доступ открыт!</b>

<tg-emoji emoji-id="{EMOJI_STAR}">💫</tg-emoji> Теперь ты можешь пользоваться InsightX.

<blockquote>Получите полное представление: узнайте всё о людях, их контактах, связях, местоположении, имуществе и криминальном прошлом.</blockquote>'''
        if is_admin:
            text += "\n\n👑 <b>Вы вошли как АДМИНИСТРАТОР</b>"
        await send_main_menu(query.message.chat.id, text, get_main_menu(is_admin), context)
        await query.message.delete()
        return
    
    if query.data == "main_menu":
        text = f'''<tg-emoji emoji-id="{EMOJI_WELCOME}">✅</tg-emoji> <b>Добро пожаловать в InsightX!</b>

<blockquote>Получите полное представление: узнайте всё о людях, их контактах, связях, местоположении, имуществе и криминальном прошлом.</blockquote>

<tg-emoji emoji-id="{EMOJI_POINT}">👆</tg-emoji> <b>Используй кнопки:</b>'''
        if is_admin:
            text += "\n\n👑 <b>Вы вошли как АДМИНИСТРАТОР</b>"
        await send_main_menu(query.message.chat.id, text, get_main_menu(is_admin), context)
        await query.message.delete()
        context.user_data.pop("awaiting_search", None)
        return
    
    if query.data == "main_start":
        text = f'''<tg-emoji emoji-id="{BTN_SEARCH}">🔎</tg-emoji> <b>Введите данные для поиска:</b>

<blockquote>
• Номер телефона
• ФИО
• Email
• Telegram username
</blockquote>

<i>Система автоматически определит тип запроса</i>'''
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_back_menu())
        context.user_data["awaiting_search"] = True
        return
    
    if query.data == "menu_profile":
        requests_today = user_info.get("requests_today", 0)
        total_requests = user_info.get("total_requests", 0)
        
        text = f'''<tg-emoji emoji-id="{BTN_PROFILE}">⚙️</tg-emoji> <b>ПРОФИЛЬ</b>

<blockquote>
├ 🆔 ID: <code>{user_id}</code>
├ 📊 Запросов сегодня: {requests_today}/50
├ 📈 Всего запросов: {total_requests}
</blockquote>'''
        
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_back_menu(), disable_web_page_preview=True)
        return
    
    if query.data == "menu_support":
        await query.edit_message_text(
            f'''<tg-emoji emoji-id="{BTN_SUPPORT}">🐶</tg-emoji> <b>ПОДДЕРЖКА</b>

<blockquote>
📢 Канал: {CHANNEL_URL}
👨‍💻 Техподдержка: {SUPPORT_LINK}
</blockquote>

<i>По всем вопросам обращайтесь</i>''',
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👨‍💻 Написать", url=SUPPORT_LINK),
                InlineKeyboardButton("◀️ Назад", callback_data="main_menu")
            ]]),
            disable_web_page_preview=True
        )
        return
    
    if query.data == "menu_news":
        await query.edit_message_text(
            f'''<tg-emoji emoji-id="{BTN_NEWS}">🔧</tg-emoji> <b>НОВОСТИ</b>

<blockquote>
Все актуальные новости в нашем канале:
{CHANNEL_URL}
</blockquote>

👇 <b>Переходи по ссылке:</b>''',
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Перейти на канал", url=CHANNEL_URL),
                InlineKeyboardButton("◀️ Назад", callback_data="main_menu")
            ]]),
            disable_web_page_preview=True
        )
        return
    
    # Админ панель
    if query.data == "admin_panel" and is_admin:
        await query.edit_message_text("⚙️ <b>АДМИН ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=get_admin_menu())
        return
    
    if query.data == "admin_stats" and is_admin:
        users_count = get_users_count()
        total_requests = get_total_requests()
        await query.edit_message_text(f"📊 <b>СТАТИСТИКА</b>\n\n<blockquote>├ 👥 Пользователей: {users_count}\n├ 📝 Всего запросов: {total_requests}\n└ 📅 {datetime.now().strftime('%d.%m.%Y')}</blockquote>", parse_mode="HTML", reply_markup=get_back_menu())
        return
    
    if query.data == "admin_users" and is_admin:
        users = get_all_users()
        text = "👥 <b>СПИСОК ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
        for u in users[:15]:
            name = u[1] or u[2] or f"id{u[0]}"
            text += f"├ {name} — {u[3]} запросов\n"
        if len(users) > 15:
            text += f"\n└ и ещё {len(users)-15}..."
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=get_back_menu())
        return
    
    if query.data == "admin_broadcast" and is_admin:
        context.user_data["awaiting_broadcast"] = True
        await query.edit_message_text("📢 <b>РАССЫЛКА</b>\n\nОтправь сообщение для всех пользователей:", parse_mode="HTML", reply_markup=get_back_menu())
        return


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    
    if context.user_data.get("is_searching"):
        await update.message.reply_text(
            f'<tg-emoji emoji-id="{EMOJI_INFO}">⚠️</tg-emoji> <b>Поиск уже выполняется!</b>\n\nПодождите завершения текущего запроса.',
            parse_mode="HTML"
        )
        return
    
    if not context.user_data.get("awaiting_search"):
        await update.message.reply_text(f'<tg-emoji emoji-id="{BTN_SEARCH}">🔎</tg-emoji> Нажми "Искать" в меню', parse_mode="HTML")
        return
    
    if not check_subscribed_to_channel(user_id):
        await update.message.reply_text(f'⚠️ Подпишись на канал:\n{CHANNEL_URL}\n\nПосле подписки нажми /start', parse_mode="HTML")
        context.user_data.pop("awaiting_search", None)
        return
    
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text('Введите данные для поиска!')
        return
    
    if not increment_request(user_id):
        await update.message.reply_text(f'<tg-emoji emoji-id="{EMOJI_INFO}">❌</tg-emoji> <b>Лимит исчерпан!</b>\n\n50 запросов в день', parse_mode="HTML")
        return
    
    context.user_data["is_searching"] = True
    
    msg = await update.message.reply_text(
        f'<tg-emoji emoji-id="{EMOJI_SEARCHING}">💬</tg-emoji> <b>Ищем данные, подождите...</b>\n\n<code>{query}</code>\n\n<tg-emoji emoji-id="{EMOJI_WAIT}">⏳</tg-emoji> <i>Это может занять до 2 минут</i>',
        parse_mode="HTML"
    )
    
    success, result = await deepscan_search(query)
    context.user_data["is_searching"] = False
    
    if success:
        html_content = generate_html_report(result, query)
        html_bytes = BytesIO(html_content.encode('utf-8'))
        html_bytes.name = f"insightx_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        
        links_count = len(result.get('links', []))
        sources_count = len(result.get('full-result', []))
        
        await msg.delete()
        await update.message.reply_document(
            document=html_bytes,
            caption=f'<tg-emoji emoji-id="{EMOJI_SUCCESS}">✅</tg-emoji> <b>Результат найден!</b>\n\n📋 Запрос: <code>{query}</code>\n📊 Найдено источников: {links_count + sources_count}',
            parse_mode="HTML"
        )
    else:
        await msg.edit_text(
            f'<tg-emoji emoji-id="{EMOJI_INFO}">❌</tg-emoji> <b>НИЧЕГО НЕ НАЙДЕНО</b>\n\n<blockquote>\n{result.get("error", "Попробуйте другой запрос")}\n🔎 Запрос: <code>{query}</code>\n</blockquote>\n\n<tg-emoji emoji-id="{BTN_SUPPORT}">🐶</tg-emoji> <i>Обратитесь в поддержку</i>',
            parse_mode="HTML",
            reply_markup=get_back_menu()
        )


async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    user_info = get_user_info(user_id)
    
    if not user_info or not user_info.get("is_admin"):
        return
    
    if not context.user_data.get("awaiting_broadcast"):
        return
    
    text = update.message.text
    users = get_all_users()
    success = 0
    
    for u in users:
        try:
            await update.message.bot.send_message(u[0], text, parse_mode="HTML", disable_web_page_preview=True)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    
    await update.message.reply_text(f"✅ Рассылка отправлена {success} пользователям")
    context.user_data.pop("awaiting_broadcast", None)


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_handler))
    
    print("🔍 InsightX бот запущен!")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"💾 База данных: {DB_PATH}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()