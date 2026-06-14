import asyncio
import logging
import sqlite3
import os
import json
import httpx
from datetime import datetime
from typing import Dict, Any, Tuple
from io import BytesIO

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== НАСТРОЙКИ ==========
BOT_TOKEN = "8979668811:AAHVemkoyYaTXnQpy2kOnzyKvi8dlb3efLw"
DEEPSCAN_TOKEN = "deepscan_6747528307:EbOVbwAg"
CHANNEL_URL = "https://t.me/Insightix"
SUPPORT_LINK = "https://t.me/bothkm"
ADMIN_ID = 6747528307
MENU_IMAGE_URL = "https://i.ibb.co/Xx9ZftNz/menu.png"

# Премиум эмодзи ID
EMOJI_WELCOME = "5895713431264170680"
EMOJI_POINT = "5886676966102274844"
EMOJI_SEARCHING = "5429411030960711866"
EMOJI_WAIT = "5210838989921106328"
EMOJI_SUCCESS = "5843918217323484232"
EMOJI_WARNING = "5893081007153746175"
EMOJI_PROFILE = "5893161718179173515"
EMOJI_NEWS = "5258023599419171861"
EMOJI_SUPPORT = "5364052602357044385"
EMOJI_SEARCH = "5258274739041883702"
EMOJI_USER = "5902335789798265487"

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BOT_DIR, 'insightx.db')

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ========== СОСТОЯНИЯ FSM ==========
class SearchState(StatesGroup):
    waiting_for_query = State()


class BroadcastState(StatesGroup):
    waiting_for_message = State()


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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            search_type TEXT,
            sources_count INTEGER,
            timestamp TEXT
        )
    ''')
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (ADMIN_ID,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, reg_date, last_reset, is_admin, subscribed_to_channel) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (ADMIN_ID, "admin", "Admin", datetime.now().isoformat(), datetime.now().isoformat(), 1, 1))
    
    conn.commit()
    conn.close()
    print(f"[OK] База данных: {DB_PATH}")


def add_user(user_id: int, username: str, first_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, reg_date, last_reset, subscribed_to_channel) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username or "", first_name or "", datetime.now().isoformat(), datetime.now().isoformat(), 0))
        conn.commit()
    
    conn.close()


def get_user_info(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, requests_today, total_requests, is_admin, subscribed_to_channel 
        FROM users WHERE user_id = ?
    ''', (user_id,))
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
    return None


def mark_subscribed(user_id: int):
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
    
    if not row:
        conn.close()
        return False
    
    requests_today, last_reset = row
    
    if last_reset:
        last_reset_date = datetime.fromisoformat(last_reset)
        if datetime.now().date() > last_reset_date.date():
            requests_today = 0
    
    if requests_today >= 50:
        conn.close()
        return False
    
    cursor.execute('''
        UPDATE users SET requests_today = ?, total_requests = total_requests + 1, last_reset = ? 
        WHERE user_id = ?
    ''', (requests_today + 1, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()
    return True


def log_search(user_id: int, query: str, search_type: str, sources_count: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO search_logs (user_id, query, search_type, sources_count, timestamp) 
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, query[:100], search_type, sources_count, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscribed_to_channel = 1")
    subscribed_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(total_requests) FROM users")
    total_requests = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT SUM(requests_today) FROM users")
    today_requests = cursor.fetchone()[0] or 0
    
    conn.close()
    return total_users, subscribed_users, total_requests, today_requests


def get_recent_logs(limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, query, search_type, sources_count, timestamp 
        FROM search_logs ORDER BY id DESC LIMIT ?
    ''', (limit,))
    logs = cursor.fetchall()
    conn.close()
    return logs


def get_users_list():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, first_name, total_requests, subscribed_to_channel FROM users")
    users = cursor.fetchall()
    conn.close()
    return users


# ========== КЛАВИАТУРЫ ==========
def get_main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="НАЧАТЬ ПОИСК", callback_data="main_start")],
        [
            InlineKeyboardButton(text="ПРОФИЛЬ", callback_data="menu_profile"),
            InlineKeyboardButton(text="НОВОСТИ", callback_data="menu_news"),
        ],
        [
            InlineKeyboardButton(text="ПОДДЕРЖКА", callback_data="menu_support"),
        ],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="АДМИН ПАНЕЛЬ", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ НАЗАД", callback_data="main_menu")]
    ])


def get_channel_check_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ПРОВЕРИТЬ ПОДПИСКУ", callback_data="check_subscribe")],
        [InlineKeyboardButton(text="ПЕРЕЙТИ НА КАНАЛ", url=CHANNEL_URL)],
    ])


def get_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="СТАТИСТИКА", callback_data="admin_stats")],
        [InlineKeyboardButton(text="ЛОГИ ПОИСКА", callback_data="admin_logs")],
        [InlineKeyboardButton(text="ПОЛЬЗОВАТЕЛИ", callback_data="admin_users")],
        [InlineKeyboardButton(text="РАССЫЛКА", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="◀ НАЗАД", callback_data="main_menu")],
    ])


# ========== DEEPSCAN API ==========
async def deepscan_search(query: str) -> Tuple[bool, Dict[str, Any]]:
    clean_query = query.strip()
    url = "https://deepscan.cc/api/v1/search"
    payload = {"token": DEEPSCAN_TOKEN, "search": clean_query}
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return True, data
                return False, {"error": "Ничего не найдено"}
            return False, {"error": f"Ошибка API: {response.status_code}"}
    except Exception as e:
        logger.error(f"DeepScan error: {e}")
        return False, {"error": f"Ошибка: {str(e)}"}


# ========== HTML ОТЧЁТ ==========
def generate_html_report(data: dict, query: str) -> str:
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
        if name and name not in all_names:
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
    
    all_ips = []
    for item in full_result:
        if item.get('ip_address') and item['ip_address'] not in all_ips:
            all_ips.append(item['ip_address'])
    
    tg_link = None
    tg_username = None
    if telegram_data:
        tg_username = telegram_data.get('username')
        if tg_username:
            tg_link = f"https://t.me/{tg_username}"
    
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>InsightX | {query}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background: #0D0D0F; font-family: 'Inter', sans-serif; color: #FFFFFF; line-height: 1.5; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
        .header {{ text-align: center; padding: 32px; background: linear-gradient(135deg, rgba(113,170,235,0.1), rgba(0,0,0,0.3)); border-radius: 20px; margin-bottom: 24px; border: 1px solid rgba(113,170,235,0.2); }}
        .header h1 {{ font-size: 28px; color: #71aaeb; }}
        .query-card {{ background: rgba(255,255,255,0.03); border-radius: 16px; padding: 24px; margin-bottom: 24px; border: 1px solid rgba(255,255,255,0.08); }}
        .query-card .value {{ font-size: 18px; font-weight: 600; word-break: break-all; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 24px; }}
        .stat-card {{ background: rgba(255,255,255,0.03); border-radius: 16px; padding: 20px; text-align: center; border: 1px solid rgba(255,255,255,0.08); }}
        .stat-number {{ font-size: 28px; font-weight: 700; color: #71aaeb; }}
        .stat-label {{ font-size: 12px; color: #8E8E93; margin-top: 8px; }}
        .data-block {{ background: rgba(255,255,255,0.03); border-radius: 16px; margin-bottom: 16px; border: 1px solid rgba(255,255,255,0.08); overflow: hidden; }}
        .block-header {{ display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; cursor: pointer; background: rgba(255,255,255,0.02); }}
        .block-header:hover {{ background: rgba(255,255,255,0.05); }}
        .block-title {{ font-weight: 600; }}
        .block-toggle {{ transition: transform 0.3s; }}
        .block-toggle.collapsed {{ transform: rotate(-90deg); }}
        .block-content {{ padding: 16px 20px; border-top: 1px solid rgba(255,255,255,0.08); }}
        .block-content.collapsed {{ display: none; }}
        .data-row {{ display: flex; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }}
        .data-key {{ width: 180px; color: #8E8E93; font-size: 13px; }}
        .data-value {{ flex: 1; word-break: break-word; font-size: 13px; }}
        .data-value a {{ color: #71aaeb; text-decoration: none; }}
        .tag {{ display: inline-block; background: rgba(113,170,235,0.12); padding: 6px 14px; border-radius: 20px; font-size: 13px; margin: 4px; color: #71aaeb; cursor: pointer; }}
        .footer {{ text-align: center; padding: 24px; color: #8E8E93; font-size: 12px; border-top: 1px solid rgba(255,255,255,0.08); margin-top: 24px; }}
        @media (max-width: 768px) {{ .stats-grid {{ grid-template-columns: repeat(2, 1fr); }} .data-row {{ flex-direction: column; }} .data-key {{ width: 100%; margin-bottom: 4px; }} }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header"><h1>INSIGHT X</h1><p style="color: #8E8E93; margin-top: 8px;">Профессиональный поиск информации</p></div>
        <div class="query-card"><div class="value">Запрос: {query}</div><div style="margin-top: 12px; font-size: 12px; color: #666;">Тип: {search_type} | UUID: {uuid[:8]}</div></div>
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-number">{sources_count}</div><div class="stat-label">Источников</div></div>
            <div class="stat-card"><div class="stat-number">{len(links)}</div><div class="stat-label">Связей</div></div>
            <div class="stat-card"><div class="stat-number">{len(all_names)}</div><div class="stat-label">Имён</div></div>
            <div class="stat-card"><div class="stat-number">{len(banks)}</div><div class="stat-label">Банков</div></div>
            <div class="stat-card"><div class="stat-number">{len(all_ips)}</div><div class="stat-label">IP</div></div>
        </div>'''
    
    if phone_info:
        html += f'''
        <div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">📞 Информация о номере</div><div class="block-toggle">▼</div></div>
        <div class="block-content">
            <div class="data-row"><div class="data-key">Страна:</div><div class="data-value">{phone_info.get('country', '—')}</div></div>
            <div class="data-row"><div class="data-key">Оператор:</div><div class="data-value">{phone_info.get('operator', '—')}</div></div>
            <div class="data-row"><div class="data-key">Регион:</div><div class="data-value">{phone_info.get('region', '—')}</div></div>
        </div></div>'''
    
    if all_names:
        names_html = ''.join(f'<span class="tag" onclick="copyText(\'{name}\')">{name}</span>' for name in all_names[:30])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">👥 Возможные имена</div><div class="block-toggle">▼</div></div><div class="block-content">{names_html}</div></div>'
    
    if all_emails:
        emails_html = ''.join(f'<div class="data-row"><div class="data-key">Email:</div><div class="data-value"><a href="mailto:{e}">{e}</a></div></div>' for e in all_emails[:20])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">📧 Email адреса</div><div class="block-toggle">▼</div></div><div class="block-content">{emails_html}</div></div>'
    
    if all_phones:
        phones_html = ''.join(f'<div class="data-row"><div class="data-key">Номер:</div><div class="data-value">{p}</div></div>' for p in all_phones[:20])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">📱 Телефоны</div><div class="block-toggle">▼</div></div><div class="block-content">{phones_html}</div></div>'
    
    if banks:
        banks_html = ''.join(f'<div class="data-row"><div class="data-key">{b.get("bank", "Банк")}:</div><div class="data-value">{b.get("name", "—")}</div></div>' for b in banks[:20])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">🏦 Банковские сервисы</div><div class="block-toggle">▼</div></div><div class="block-content">{banks_html}</div></div>'
    
    if all_ips:
        ips_html = ''.join(f'<div class="data-row"><div class="data-key">IP:</div><div class="data-value">{ip}</div></div>' for ip in all_ips[:10])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">🌐 IP-адреса</div><div class="block-toggle">▼</div></div><div class="block-content">{ips_html}</div></div>'
    
    if tg_link:
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">💬 Telegram</div><div class="block-toggle">▼</div></div><div class="block-content"><div class="data-row"><div class="data-key">Профиль:</div><div class="data-value"><a href="{tg_link}" target="_blank">@{tg_username}</a></div></div></div></div>'
    
    if registers:
        regs_html = ''.join(f'<span class="tag">{reg}</span>' for reg in registers[:15])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">📚 Реестры</div><div class="block-toggle">▼</div></div><div class="block-content">{regs_html}</div></div>'
    
    if links:
        links_html = ''.join(f'<div class="data-row"><div class="data-key">Связь:</div><div class="data-value"><a href="{l}" target="_blank">{l}</a></div></div>' for l in links[:30])
        html += f'<div class="data-block"><div class="block-header" onclick="toggleBlock(this)"><div class="block-title">🔗 Найденные связи</div><div class="block-toggle">▼</div></div><div class="block-content">{links_html}</div></div>'
    
    html += f'''
        <div class="footer"><p>INSIGHTX — профессиональный поиск информации</p><p><a href="{CHANNEL_URL}" target="_blank" style="color: #71aaeb;">@Insightix</a></p></div>
    </div>
    <script>
        function toggleBlock(header) {{
            var content = header.nextElementSibling;
            var toggle = header.querySelector('.block-toggle');
            content.classList.toggle('collapsed');
            toggle.classList.toggle('collapsed');
        }}
        function copyText(text) {{
            navigator.clipboard.writeText(text);
            var notification = document.createElement('div');
            notification.textContent = 'Скопировано!';
            notification.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#71aaeb;color:#000;padding:8px 16px;border-radius:8px;z-index:9999;';
            document.body.appendChild(notification);
            setTimeout(function() {{ notification.remove(); }}, 1500);
        }}
    </script>
</body>
</html>'''
    
    return html


# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user = message.from_user
    add_user(user.id, user.username or "", user.first_name or "")
    user_info = get_user_info(user.id)
    is_admin = user_info.get("is_admin", False) if user_info else False
    
    await state.clear()
    
    text = f'<tg-emoji emoji-id="{EMOJI_WELCOME}">✅</tg-emoji> <b>Добро пожаловать в InsightX, {user.first_name}!</b>\n\n<blockquote>Получите полное представление: узнайте всё о людях, их контактах, связях, местоположении, имуществе и криминальном прошлом.</blockquote>\n\n<tg-emoji emoji-id="{EMOJI_POINT}">👇</tg-emoji> <b>Выберите действие:</b>'
    
    try:
        await message.answer_photo(
            photo=MENU_IMAGE_URL,
            caption=text,
            parse_mode="HTML",
            reply_markup=get_main_menu(is_admin)
        )
    except:
        await message.answer(text, parse_mode="HTML", reply_markup=get_main_menu(is_admin))


@dp.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    user_info = get_user_info(callback.from_user.id)
    is_admin = user_info.get("is_admin", False) if user_info else False
    
    text = f'<tg-emoji emoji-id="{EMOJI_WELCOME}">✅</tg-emoji> <b>Добро пожаловать в InsightX!</b>\n\n<blockquote>Получите полное представление: узнайте всё о людях, их контактах, связях, местоположении, имуществе и криминальном прошлом.</blockquote>\n\n<tg-emoji emoji-id="{EMOJI_POINT}">👇</tg-emoji> <b>Выберите действие:</b>'
    
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=MENU_IMAGE_URL,
        caption=text,
        parse_mode="HTML",
        reply_markup=get_main_menu(is_admin)
    )


@dp.callback_query(F.data == "main_start")
async def callback_main_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.delete()
    
    text = f'<tg-emoji emoji-id="{EMOJI_SEARCHING}">🔍</tg-emoji> <b>Введите данные для поиска</b>\n\n<blockquote>Система автоматически определит тип запроса</blockquote>'
    
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_menu())
    await state.set_state(SearchState.waiting_for_query)


@dp.callback_query(F.data == "menu_profile")
async def callback_menu_profile(callback: types.CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    user_info = get_user_info(user_id)
    
    if user_info:
        requests_today = user_info.get("requests_today", 0)
        total_requests = user_info.get("total_requests", 0)
        text = f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> <b>ПРОФИЛЬ</b>\n\n<blockquote>\n├ ID: <code>{user_id}</code>\n├ Запросов сегодня: {requests_today}/50\n├ Всего запросов: {total_requests}\n</blockquote>'
    else:
        text = f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> <b>ПРОФИЛЬ</b>\n\n<blockquote>\n├ ID: <code>{user_id}</code>\n├ Запросов сегодня: 0/50\n├ Всего запросов: 0\n</blockquote>'
    
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_menu())


@dp.callback_query(F.data == "menu_support")
async def callback_menu_support(callback: types.CallbackQuery):
    await callback.answer()
    text = f'<tg-emoji emoji-id="{EMOJI_SUPPORT}">🆘</tg-emoji> <b>ПОДДЕРЖКА</b>\n\n<blockquote>\n📢 Канал: {CHANNEL_URL}\n👨‍💻 Техподдержка: {SUPPORT_LINK}\n</blockquote>'
    
    await callback.message.delete()
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="НАПИСАТЬ", url=SUPPORT_LINK)],
            [InlineKeyboardButton(text="◀ НАЗАД", callback_data="main_menu")]
        ])
    )


@dp.callback_query(F.data == "menu_news")
async def callback_menu_news(callback: types.CallbackQuery):
    await callback.answer()
    text = f'<tg-emoji emoji-id="{EMOJI_NEWS}">📰</tg-emoji> <b>НОВОСТИ</b>\n\n<blockquote>Все актуальные новости в нашем канале:\n{CHANNEL_URL}</blockquote>'
    
    await callback.message.delete()
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="ПЕРЕЙТИ", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="◀ НАЗАД", callback_data="main_menu")]
        ])
    )


@dp.callback_query(F.data == "check_subscribe")
async def callback_check_subscribe(callback: types.CallbackQuery):
    await callback.answer()
    mark_subscribed(callback.from_user.id)
    await callback_main_menu(callback, None)


# ========== АДМИН ПАНЕЛЬ ==========
@dp.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: types.CallbackQuery):
    await callback.answer()
    user_info = get_user_info(callback.from_user.id)
    if not user_info or not user_info.get("is_admin"):
        await callback.message.answer("❌ Нет доступа")
        return
    
    await callback.message.delete()
    await callback.message.answer("⚙️ <b>АДМИН ПАНЕЛЬ</b>\n\nВыбери действие:", parse_mode="HTML", reply_markup=get_admin_menu())


@dp.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: types.CallbackQuery):
    await callback.answer()
    user_info = get_user_info(callback.from_user.id)
    if not user_info or not user_info.get("is_admin"):
        return
    
    total_users, subscribed_users, total_requests, today_requests = get_stats()
    text = f"📊 <b>СТАТИСТИКА</b>\n\n<blockquote>├ 👥 Пользователей: {total_users}\n├ ✅ Подписаны на канал: {subscribed_users}\n├ 📝 Запросов всего: {total_requests}\n├ 📊 Запросов сегодня: {today_requests}\n└ 📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}</blockquote>"
    
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_menu())


@dp.callback_query(F.data == "admin_logs")
async def callback_admin_logs(callback: types.CallbackQuery):
    await callback.answer()
    user_info = get_user_info(callback.from_user.id)
    if not user_info or not user_info.get("is_admin"):
        return
    
    logs = get_recent_logs(20)
    text = "📋 <b>ПОСЛЕДНИЕ ЗАПРОСЫ</b>\n\n"
    for log in logs:
        uid, q, st, sc, ts = log
        text += f"├ {ts[:16]} | {uid} | {st} | {sc} ист.\n"
    if not logs:
        text += "├ Нет запросов\n"
    
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_menu())


@dp.callback_query(F.data == "admin_users")
async def callback_admin_users(callback: types.CallbackQuery):
    await callback.answer()
    user_info = get_user_info(callback.from_user.id)
    if not user_info or not user_info.get("is_admin"):
        return
    
    users = get_users_list()
    text = "👥 <b>СПИСОК ПОЛЬЗОВАТЕЛЕЙ</b>\n\n"
    for u in users[:20]:
        uid, uname, fname, treq, sub = u
        name = uname or fname or f"id{uid}"
        sub_status = "✅" if sub else "❌"
        text += f"├ {sub_status} {name} — {treq} запросов\n"
    if not users:
        text += "├ Нет пользователей\n"
    
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_back_menu())


@dp.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_info = get_user_info(callback.from_user.id)
    if not user_info or not user_info.get("is_admin"):
        return
    
    await callback.message.delete()
    await callback.message.answer("📢 <b>РАССЫЛКА</b>\n\nОтправь сообщение для всех пользователей:", parse_mode="HTML", reply_markup=get_back_menu())
    await state.set_state(BroadcastState.waiting_for_message)


# ========== ПОИСК ==========
@dp.message(SearchState.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    query = message.text.strip()
    
    if not query:
        await message.answer("❌ Введите данные для поиска!")
        return
    
    if not increment_request(user_id):
        await message.answer("❌ Лимит исчерпан!\n\n50 запросов в день")
        await state.clear()
        return
    
    await state.clear()
    
    status_msg = await message.answer(
        f'<tg-emoji emoji-id="{EMOJI_SEARCHING}">🔍</tg-emoji> <b>Ищем данные, подождите...</b>\n\n<code>{query}</code>\n\n<tg-emoji emoji-id="{EMOJI_WAIT}">⏳</tg-emoji> <i>Это может занять до 2 минут</i>',
        parse_mode="HTML"
    )
    
    success, result = await deepscan_search(query)
    
    if success:
        search_type = result.get('type', 'unknown')
        sources_count = len(result.get('full-result', []))
        log_search(user_id, query, search_type, sources_count)
        
        html_content = generate_html_report(result, query)
        html_bytes = BytesIO(html_content.encode('utf-8'))
        html_bytes.name = f"insightx_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        
        await status_msg.delete()
        await message.answer_document(
            document=types.BufferedInputFile(html_bytes.getvalue(), filename=html_bytes.name),
            caption=f'<tg-emoji emoji-id="{EMOJI_SUCCESS}">✅</tg-emoji> <b>Результат найден!</b>\n\n<tg-emoji emoji-id="{EMOJI_SEARCH}">🔍</tg-emoji> <b>Запрос:</b> <code>{query}</code>\n\n<tg-emoji emoji-id="{EMOJI_USER}">👤</tg-emoji> <b>Найдено источников:</b> {sources_count}',
            parse_mode="HTML"
        )
    else:
        await status_msg.edit_text(
            f'❌ <b>НИЧЕГО НЕ НАЙДЕНО</b>\n\n<blockquote>\n{result.get("error", "Попробуйте другой запрос")}\n🔎 Запрос: <code>{query}</code>\n</blockquote>',
            parse_mode="HTML",
            reply_markup=get_back_menu()
        )


# ========== РАССЫЛКА ==========
@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_info = get_user_info(user_id)
    
    if not user_info or not user_info.get("is_admin"):
        await state.clear()
        return
    
    users = get_all_users()
    
    if not users:
        await message.answer("❌ Нет пользователей для рассылки")
        await state.clear()
        return
    
    total = len(users)
    success = 0
    
    status_msg = await message.answer(f"📢 НАЧИНАЮ РАССЫЛКУ {total} ПОЛЬЗОВАТЕЛЯМ...\n\n⏳ 0/{total} отправлено")
    
    if message.photo:
        photo = message.photo[-1].file_id
        caption = message.caption or ""
        for i, uid in enumerate(users):
            try:
                await bot.send_photo(chat_id=uid, photo=photo, caption=caption, parse_mode="HTML")
                success += 1
                if (i + 1) % 5 == 0 or i == total - 1:
                    await status_msg.edit_text(f"📢 РАССЫЛКА\n\n✅ {success}/{total} отправлено\n⏳ {total - success} осталось")
                await asyncio.sleep(0.1)
            except:
                pass
    elif message.video:
        video = message.video.file_id
        caption = message.caption or ""
        for i, uid in enumerate(users):
            try:
                await bot.send_video(chat_id=uid, video=video, caption=caption, parse_mode="HTML")
                success += 1
                if (i + 1) % 5 == 0 or i == total - 1:
                    await status_msg.edit_text(f"📢 РАССЫЛКА\n\n✅ {success}/{total} отправлено\n⏳ {total - success} осталось")
                await asyncio.sleep(0.1)
            except:
                pass
    else:
        text = message.text
        for i, uid in enumerate(users):
            try:
                await bot.send_message(chat_id=uid, text=text, parse_mode="HTML", disable_web_page_preview=True)
                success += 1
                if (i + 1) % 5 == 0 or i == total - 1:
                    await status_msg.edit_text(f"📢 РАССЫЛКА\n\n✅ {success}/{total} отправлено\n⏳ {total - success} осталось")
                await asyncio.sleep(0.1)
            except:
                pass
    
    await status_msg.edit_text(f"✅ РАССЫЛКА ЗАВЕРШЕНА\n\n📊 Отправлено: {success}/{total} пользователям\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    await state.clear()


@dp.message()
async def handle_other_messages(message: types.Message):
    await message.answer(
        '🔍 Нажмите кнопку "НАЧАТЬ ПОИСК" в меню',
        parse_mode="HTML",
        reply_markup=get_back_menu()
    )


# ========== ЗАПУСК ==========
async def main():
    init_db()
    print("=" * 50)
    print("INSIGHT X БОТ ЗАПУЩЕН (aiogram)!")
    print(f"Админ ID: {ADMIN_ID}")
    print(f"База данных: {DB_PATH}")
    print("=" * 50)
    
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
