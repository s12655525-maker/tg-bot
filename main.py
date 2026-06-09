import asyncio
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
import os

# ─── Конфигурация ─────────────────────────────
BOT_TOKEN = "твой токен"
DB_NAME = "reservations.db"

# Информация о ресторане
RESTAURANT_NAME = "Gourmet House"
RESTAURANT_ADDRESS = "ул. Тверская, 15"
RESTAURANT_PHONE = "+7 (495) 123-45-67"

# Типы столов
TABLE_TYPES = {
    "standard": {"name": "Стандартный", "capacity": 4, "price": 0},
    "window": {"name": "У окна", "capacity": 4, "price": 500},
    "booth": {"name": "Кабина", "capacity": 6, "price": 1000},
    "vip": {"name": "VIP-зона", "capacity": 8, "price": 2000}
}

# ─── База данных ──────────────────────────────
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            name TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            table_type TEXT,
            guests_count INTEGER,
            reservation_time TIMESTAMP,
            status TEXT DEFAULT 'confirmed',
            special_requests TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_user(telegram_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (telegram_id) VALUES (?)", (telegram_id,))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()
    conn.close()
    return user

def create_reservation(user_id, table_type, guests_count, reservation_time, special_requests=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reservations (user_id, table_type, guests_count, reservation_time, special_requests)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, table_type, guests_count, reservation_time, special_requests))
    reservation_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return reservation_id

def get_user_reservations(telegram_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.* FROM reservations r
        JOIN users u ON r.user_id = u.id
        WHERE u.telegram_id = ? AND r.status != 'cancelled'
        ORDER BY r.reservation_time DESC
    """, (telegram_id,))
    reservations = cursor.fetchall()
    conn.close()
    return reservations

def cancel_reservation(reservation_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE reservations SET status = 'cancelled' WHERE id = ?", (reservation_id,))
    conn.commit()
    conn.close()

# ─── FSM States ───────────────────────────────
class ReservationState(StatesGroup):
    waiting_for_table_type = State()
    waiting_for_guests = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_requests = State()

# ─── Клавиатуры ───────────────────────────────
def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📅 Новое бронирование")],
            [types.KeyboardButton(text="📋 Мои бронирования")],
            [types.KeyboardButton(text="ℹ️ О ресторане")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_table_type_keyboard():
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="🪑 Стандартный (до 4 чел)", callback_data="table_standard")],
            [types.InlineKeyboardButton(text="🪟 У окна (+500₽)", callback_data="table_window")],
            [types.InlineKeyboardButton(text="🛋️ Кабина (до 6 чел, +1000₽)", callback_data="table_booth")],
            [types.InlineKeyboardButton(text="👑 VIP-зона (до 8 чел, +2000₽)", callback_data="table_vip")]
        ]
    )
    return keyboard

def get_reservation_actions(reservation_id):
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ Отменить бронь", callback_data=f"cancel_{reservation_id}")]
        ]
    )
    return keyboard

# ─── Handlers ─────────────────────────────────
async def start(message: types.Message):
    """Команда /start"""
    user = get_user(message.from_user.id)
    await message.answer(
        f"👋 Добро пожаловать в <b>{RESTAURANT_NAME}</b>!\n\n"
        f"📍 {RESTAURANT_ADDRESS}\n"
        f"📞 {RESTAURANT_PHONE}\n\n"
        f"Выберите действие:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

async def cmd_about(message: types.Message):
    """О ресторане"""
    await message.answer(
        f"🏨 <b>{RESTAURANT_NAME}</b>\n\n"
        f"📍 Адрес: {RESTAURANT_ADDRESS}\n"
        f"📞 Телефон: {RESTAURANT_PHONE}\n\n"
        f"🕒 <b>Режим работы:</b>\n"
        f"Пн-Чт: 12:00 - 23:00\n"
        f"Пт-Сб: 12:00 - 00:00\n"
        f"Вс: 12:00 - 22:00",
        parse_mode="HTML"
    )

async def new_reservation(message: types.Message, state: FSMContext):
    """Начать бронирование"""
    await message.answer(
        "🪑 <b>Выберите тип стола:</b>\n\n"
        "💰 Доплата взимается за место",
        reply_markup=get_table_type_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(ReservationState.waiting_for_table_type)

async def callback_table_type(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора типа стола"""
    table_type = callback.data.replace("table_", "")
    table_info = TABLE_TYPES[table_type]
    await state.update_data(table_type=table_type)
    
    await callback.message.edit_text(
        f"✅ Выбран: <b>{table_info['name']}</b>\n"
        f"👥 Вместимость: до {table_info['capacity']} человек\n"
        f"💰 Доплата: {table_info['price']}₽\n\n"
        f"Сколько гостей будет?",
        parse_mode="HTML"
    )
    await state.set_state(ReservationState.waiting_for_guests)
    await callback.answer()

async def process_guests(message: types.Message, state: FSMContext):
    """Обработка количества гостей"""
    try:
        guests = int(message.text)
        if guests < 1 or guests > 10:
            await message.answer("Пожалуйста, введите число от 1 до 10:")
            return
        
        data = await state.get_data()
        table_info = TABLE_TYPES[data['table_type']]
        
        if guests > table_info['capacity']:
            await message.answer(f"Этот тип стола вмещает максимум {table_info['capacity']} человек.")
            await new_reservation(message, state)
            return
        
        await state.update_data(guests_count=guests)
        
        today = datetime.now().date()
        keyboard = types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text=(today + timedelta(days=i)).strftime("%d.%m"), 
                                           callback_data=f"date_{today + timedelta(days=i)}")]
                for i in range(7)
            ]
        )
        
        await message.answer(
            f"✅ Количество гостей: <b>{guests}</b>\n\n"
            f"Выберите дату:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(ReservationState.waiting_for_date)
    except ValueError:
        await message.answer("Пожалуйста, введите число:")

async def callback_date(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора даты"""
    if callback.data.startswith("date_"):
        selected_date = callback.data.replace("date_", "")
        await state.update_data(reservation_date=selected_date)
        
        hour = datetime.now().hour
        slots = []
        for h in range(hour if hour > 12 else 12, 23):
            for m in [0, 30]:
                if h < 23 or (h == 23 and m == 0):
                    time_str = f"{h:02d}:{m:02d}"
                    slots.append(types.InlineKeyboardButton(text=time_str, callback_data=f"time_{time_str}"))
        
        keyboard = types.InlineKeyboardMarkup(inline_keyboard=[[slot] for slot in slots[:12]])
        
        await callback.message.edit_text(
            f"✅ Дата: <b>{selected_date}</b>\n\n"
            f"Выберите время:",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await state.set_state(ReservationState.waiting_for_time)
        await callback.answer()

async def callback_time(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора времени"""
    if callback.data.startswith("time_"):
        selected_time = callback.data.replace("time_", "")
        await state.update_data(reservation_time=selected_time)
        await callback.message.edit_text("📝 <b>Ваше имя:</b>", parse_mode="HTML")
        await state.set_state(ReservationState.waiting_for_name)
        await callback.answer()

async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("📱 <b>Ваш номер телефона:</b>", parse_mode="HTML")
    await state.set_state(ReservationState.waiting_for_phone)

async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("📝 <b>Особые пожелания (необязательно):</b>", parse_mode="HTML")
    await state.set_state(ReservationState.waiting_for_requests)

async def process_requests(message: types.Message, state: FSMContext):
    """Завершение бронирования"""
    data = await state.get_data()
    special_requests = message.text if message.text else "Нет"
    
    user = get_user(message.from_user.id)
    reservation_id = create_reservation(
        user_id=user[0],
        table_type=data['table_type'],
        guests_count=data['guests_count'],
        reservation_time=f"{data['reservation_date']} {data['reservation_time']}",
        special_requests=special_requests
    )
    
    table_info = TABLE_TYPES[data['table_type']]
    salary = table_info['price']  # Доплата = зарплата
    
    await message.answer(
        f"✅ <b>Бронирование подтверждено!</b>\n\n"
        f"📅 Дата: {data['reservation_date']}\n"
        f"⏰ Время: {data['reservation_time']}\n"
        f"🪑 Стол: {table_info['name']}\n"
        f"👥 Гостей: {data['guests_count']}\n"
        f"💰 Доплата: {salary}₽\n\n"
        f"Ожидаем вас!",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()
    
async def show_my_reservations(message: types.Message):
    """Показать мои бронирования"""
    reservations = get_user_reservations(message.from_user.id)
    
    if not reservations:
        await message.answer(
            "У вас нет активных бронирований.\n\n"
            "Создайте новое через меню!",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "📋 <b>Ваши бронирования:</b>\n\n"
    for res in reservations:
        table_info = TABLE_TYPES[res[2]]
        salary = table_info['price']  # Зарплата = доплата
        text += (
            f"🆔 <b>#{res[0]}</b>\n"
            f"📅 {res[4]}\n"
            f"🪑 {table_info['name']}, {res[3]} гостя\n"
            f"💰 Доплата: {salary}₽\n"
            f"Статус: {res[5]}\n\n"
        )
    
    await message.answer(text, parse_mode="HTML")

async def cancel_reservation_callback(callback: types.CallbackQuery):
    """Отмена бронирования"""
    if callback.data.startswith("cancel_"):
        reservation_id = int(callback.data.replace("cancel_", ""))
        cancel_reservation(reservation_id)
        await callback.message.edit_text(
            "✅ Бронирование отменено!",
            reply_markup=get_main_keyboard()
        )
        await callback.answer()

async def handle_menu_text(message: types.Message, state: FSMContext):
    """Обработка меню"""
    if message.text == "📅 Новое бронирование":
        await new_reservation(message, state)
    elif message.text == "📋 Мои бронирования":
        await show_my_reservations(message)
    elif message.text == "ℹ️ О ресторане":
        await cmd_about(message)
    else:
        await message.answer(
            "Используйте кнопки меню или /start",
            reply_markup=get_main_keyboard()
        )

# ─── Main ──────────────────────────────────────
def main():
    """Запуск бота"""
    init_db()
    
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Команды
    dp.message.register(start, Command("start"))
    dp.message.register(cmd_about, Command("about"))
    
    # Меню
    dp.message.register(handle_menu_text, F.text.in_(["📅 Новое бронирование", "📋 Мои бронирования", "ℹ️ О ресторане"]))
    
    # Callback handlers
    dp.callback_query.register(callback_table_type, F.data.startswith("table_"))
    dp.callback_query.register(callback_date, F.data.startswith("date_"))
    dp.callback_query.register(callback_time, F.data.startswith("time_"))
    dp.callback_query.register(cancel_reservation_callback, F.data.startswith("cancel_"))
    
    # FSM handlers
    dp.message.register(process_guests, ReservationState.waiting_for_guests)
    dp.message.register(process_name, ReservationState.waiting_for_name)
    dp.message.register(process_phone, ReservationState.waiting_for_phone)
    dp.message.register(process_requests, ReservationState.waiting_for_requests)
    
    print("Bot started. Ctrl+C to stop.")
    
    try:
        dp.run_polling(bot)
    except KeyboardInterrupt:
        print("Bot stopped")
    finally:
        asyncio.run(bot.close())

if __name__ == "__main__":
    main()