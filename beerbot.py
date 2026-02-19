
import asyncio
import logging
import os
import sqlite3
from dataclasses import dataclass

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

DB_PATH = "beer_sport.db"


DEFAULT_RATE = {
    "beer": 0.75,
    "wine": 0.30,
    "strong": 0.15,
}

DRINK_LABEL = {
    "beer": "Пиво 🍺",
    "wine": "Вино 🍷",
    "strong": "Крепкое 🥃",
}

INFO_TEXT = (
    "Как мне кажется, алкоголь является отличным мотиватором. Надеюсь, этот бот поможет меньше пить и больше тренироваться.\n\n"
    "Бот считает доступный баланс в литрах выбранного напитка. Баланс может быть отрицательным, но это значит, что его все равно нужно будет отработать.\n"
    "• «Выпить» уменьшает баланс.\n"
    "• «Спорт» увеличивает баланс по текущей формуле.\n"
    "• «Сменить напиток» переключает напиток и пересчитывает баланс.\n\n"
    "Команды:\n"
    "/start — меню\n"
    "/info — справка\n"
    "/change — сменить напиток\n"
    "/setrate X — задать формулу для текущего напитка (литров за 60 минут)\n\n"
    "Сделано @gesxn\n"
    "Поддержать хостинг сервера: 2202 2032 5095 1219"
)



def db_connect():
    return sqlite3.connect(DB_PATH)

def _has_column(con: sqlite3.Connection, table: str, col: str) -> bool:
    cur = con.execute(f"PRAGMA table_info({table})")
    cols = {row[1] for row in cur.fetchall()}
    return col in cols

def db_init():
    with db_connect() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            drink TEXT NOT NULL DEFAULT 'beer',
            balance_minutes REAL NOT NULL DEFAULT 0.0,
            rate_beer REAL NOT NULL DEFAULT 0.75,
            rate_wine REAL NOT NULL DEFAULT 0.30,
            rate_strong REAL NOT NULL DEFAULT 0.15
        )
        """)
        con.commit()


    with db_connect() as con:
       
        old_balance = _has_column(con, "users", "balance_liters")
        old_rate = _has_column(con, "users", "rate_lph")
        old_drink = _has_column(con, "users", "drink")

        if not _has_column(con, "users", "balance_minutes"):
            con.execute("ALTER TABLE users ADD COLUMN balance_minutes REAL NOT NULL DEFAULT 0.0")
        if not _has_column(con, "users", "rate_beer"):
            con.execute("ALTER TABLE users ADD COLUMN rate_beer REAL NOT NULL DEFAULT 0.75")
        if not _has_column(con, "users", "rate_wine"):
            con.execute("ALTER TABLE users ADD COLUMN rate_wine REAL NOT NULL DEFAULT 0.30")
        if not _has_column(con, "users", "rate_strong"):
            con.execute("ALTER TABLE users ADD COLUMN rate_strong REAL NOT NULL DEFAULT 0.15")
        if not old_drink:
            con.execute("ALTER TABLE users ADD COLUMN drink TEXT NOT NULL DEFAULT 'beer'")

        con.commit()

       
        if old_balance and old_rate:
          
            cur = con.execute("SELECT user_id, balance_liters, rate_lph, drink FROM users")
            rows = cur.fetchall()
            for user_id, balance_liters, rate_lph, drink in rows:
                try:
                    balance_liters = float(balance_liters)
                    rate_lph = float(rate_lph)
                    drink = str(drink) if drink else "beer"
                    if drink not in DEFAULT_RATE:
                        drink = "beer"
                    minutes = 0.0
                    if rate_lph > 0:
                        minutes = (balance_liters / rate_lph) * 60.0

                    con.execute("UPDATE users SET balance_minutes = ? WHERE user_id = ?", (minutes, user_id))

                   
                    if drink == "beer":
                        con.execute("UPDATE users SET rate_beer = ? WHERE user_id = ?", (rate_lph, user_id))
                    elif drink == "wine":
                        con.execute("UPDATE users SET rate_wine = ? WHERE user_id = ?", (rate_lph, user_id))
                    elif drink == "strong":
                        con.execute("UPDATE users SET rate_strong = ? WHERE user_id = ?", (rate_lph, user_id))
                except Exception:
                    continue

            con.commit()

def db_ensure_user(user_id: int):
    with db_connect() as con:
        cur = con.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cur.fetchone() is None:
            con.execute(
                """
                INSERT INTO users(user_id, drink, balance_minutes, rate_beer, rate_wine, rate_strong)
                VALUES(?, 'beer', 0.0, ?, ?, ?)
                """,
                (user_id, DEFAULT_RATE["beer"], DEFAULT_RATE["wine"], DEFAULT_RATE["strong"]),
            )
            con.commit()

@dataclass
class UserData:
    user_id: int
    drink: str
    balance_minutes: float
    rate_beer: float
    rate_wine: float
    rate_strong: float

    def rate_for_current_drink(self) -> float:
        if self.drink == "beer":
            return self.rate_beer
        if self.drink == "wine":
            return self.rate_wine
        if self.drink == "strong":
            return self.rate_strong
        return self.rate_beer

def db_get_user(user_id: int) -> UserData:
    db_ensure_user(user_id)
    with db_connect() as con:
        cur = con.execute(
            "SELECT user_id, drink, balance_minutes, rate_beer, rate_wine, rate_strong FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        return UserData(
            user_id=int(row[0]),
            drink=str(row[1]),
            balance_minutes=float(row[2]),
            rate_beer=float(row[3]),
            rate_wine=float(row[4]),
            rate_strong=float(row[5]),
        )

def db_set_balance_minutes(user_id: int, minutes: float):
    db_ensure_user(user_id)
    with db_connect() as con:
        con.execute("UPDATE users SET balance_minutes = ? WHERE user_id = ?", (minutes, user_id))
        con.commit()

def db_set_drink(user_id: int, drink: str):
    db_ensure_user(user_id)
    if drink not in DEFAULT_RATE:
        drink = "beer"
    with db_connect() as con:
        con.execute("UPDATE users SET drink = ? WHERE user_id = ?", (drink, user_id))
        con.commit()

def db_set_rate_for_drink(user_id: int, drink: str, rate_lph: float):
    db_ensure_user(user_id)
    if drink not in DEFAULT_RATE:
        drink = "beer"
    col = {"beer": "rate_beer", "wine": "rate_wine", "strong": "rate_strong"}[drink]
    with db_connect() as con:
        con.execute(f"UPDATE users SET {col} = ? WHERE user_id = ?", (rate_lph, user_id))
        con.commit()



class InputStates(StatesGroup):
    waiting_custom_drink_amount = State()
    waiting_custom_sport_minutes = State()


def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🍻 Выпить", callback_data="menu:drink")
    kb.button(text="🏋️ Спорт", callback_data="menu:sport")
    kb.button(text="🔁 Сменить напиток", callback_data="menu:change")
    kb.button(text="ℹ️ Инфо", callback_data="menu:info")
    kb.adjust(2, 2)
    return kb.as_markup()

def drink_amount_kb(drink: str):
    presets = {
        "beer":  [0.5, 1.0, 1.5],
        "wine":  [0.15, 0.3, 0.5],
        "strong":[0.05, 0.1, 0.2],
    }.get(drink, [0.5, 1.0, 1.5])

    kb = InlineKeyboardBuilder()
    for v in presets:
    
        label = str(v).rstrip("0").rstrip(".")
        kb.button(text=f"{label} л", callback_data=f"drink:{v}")
    kb.button(text="✍️ Свое значение", callback_data="drink:custom")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(3, 1, 1)
    return kb.as_markup()


def sport_time_kb():
    kb = InlineKeyboardBuilder()
    for m in [30, 60, 90]:
        kb.button(text=f"{m} мин", callback_data=f"sport:{m}")
    kb.button(text="✍️ Свое значение", callback_data="sport:custom")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(3, 1, 1)
    return kb.as_markup()

def change_drink_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🍺 Пиво", callback_data="change:beer")
    kb.button(text="🍷 Вино", callback_data="change:wine")
    kb.button(text="🥃 Крепкое", callback_data="change:strong")
    kb.button(text="⬅️ Назад", callback_data="menu:back")
    kb.adjust(3, 1)
    return kb.as_markup()

def liters_from_minutes(balance_minutes: float, rate_lph: float) -> float:
    # rate_lph = литров за 60 минут
    return (balance_minutes / 60.0) * rate_lph

def minutes_from_liters(liters: float, rate_lph: float) -> float:
    # minutes = liters / (liters_per_60) * 60
    if rate_lph <= 0:
        return 0.0
    return (liters / rate_lph) * 60.0

def fmt_status(u: UserData) -> str:
    rate = u.rate_for_current_drink()
    drink_label = DRINK_LABEL.get(u.drink, u.drink)
    balance_liters = liters_from_minutes(u.balance_minutes, rate)
    return (
        f"Напиток: {drink_label}\n"
        f"Текущий баланс: {balance_liters:.2f} л\n"
        f"Текущая формула: 60 мин = {rate:.2f} л"
    )

def fmt_screen(u: UserData, header: str | None = None) -> str:
    base = fmt_status(u)
    return f"{header}\n\n{base}" if header else base



async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    db_ensure_user(message.from_user.id)
    u = db_get_user(message.from_user.id)
    await message.answer(fmt_screen(u), reply_markup=main_menu_kb())

async def cmd_info(message: Message):
    await message.answer(INFO_TEXT)

async def cmd_change(message: Message, state: FSMContext):
    await state.clear()
    db_ensure_user(message.from_user.id)
    await message.answer("Выберите напиток:", reply_markup=change_drink_kb())

async def cmd_setrate(message: Message, command: CommandObject):
    db_ensure_user(message.from_user.id)
    u = db_get_user(message.from_user.id)

    if not command.args:
        await message.answer("Использование: /setrate 0.5 (литров за 60 минут) — для текущего напитка.")
        return

    try:
        val = float(command.args.replace(",", "."))
    except ValueError:
        await message.answer("Не понял число. Пример: /setrate 0.75")
        return

    if val <= 0 or val > 10:
        await message.answer("Значение должно быть > 0 и разумным (например 0.1–2.0).")
        return

    db_set_rate_for_drink(u.user_id, u.drink, val)
    u2 = db_get_user(u.user_id)
    await message.answer("Формула обновлена для текущего напитка.\n\n" + fmt_status(u2), reply_markup=main_menu_kb())



async def on_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    db_ensure_user(user_id)
    u = db_get_user(user_id)

    action = call.data.split(":", 1)[1]

    if action == "drink":
        await call.message.edit_text(
            f"Сколько выпить? ({DRINK_LABEL.get(u.drink, u.drink)})",
            reply_markup=drink_amount_kb(u.drink)
        )

    elif action == "sport":
        await call.message.edit_text("Сколько тренировался?", reply_markup=sport_time_kb())
    elif action == "change":
        await call.message.edit_text("Выберите напиток:", reply_markup=change_drink_kb())
    elif action == "info":
        await call.message.edit_text(INFO_TEXT, reply_markup=main_menu_kb())
    elif action == "back":
        await call.message.edit_text(fmt_screen(u), reply_markup=main_menu_kb())

    await call.answer()

async def on_drink_choice(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    db_ensure_user(user_id)
    u = db_get_user(user_id)
    rate = u.rate_for_current_drink()

    payload = call.data.split(":", 1)[1]
    if payload == "custom":
        await state.set_state(InputStates.waiting_custom_drink_amount)
        await call.message.edit_text("Введи объём в литрах (например 0.33):")
        await call.answer()
        return

    liters = float(payload)
    delta_minutes = minutes_from_liters(liters, rate)
    new_minutes = u.balance_minutes - delta_minutes
    db_set_balance_minutes(user_id, new_minutes)

    u2 = db_get_user(user_id)
    await call.message.edit_text(fmt_screen(u2, f"Учтено: -{liters:.2f} л"), reply_markup=main_menu_kb())
    await call.answer()

async def on_sport_choice(call: CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    db_ensure_user(user_id)
    u = db_get_user(user_id)

    payload = call.data.split(":", 1)[1]
    if payload == "custom":
        await state.set_state(InputStates.waiting_custom_sport_minutes)
        await call.message.edit_text("Введи время в минутах (например 45):")
        await call.answer()
        return

    minutes = float(payload)
    new_minutes = u.balance_minutes + minutes
    db_set_balance_minutes(user_id, new_minutes)

    u2 = db_get_user(user_id)
    # Сколько это в литрах текущего напитка:
    gained_liters = liters_from_minutes(minutes, u2.rate_for_current_drink())
    await call.message.edit_text(
        fmt_screen(u2, f"Учтено: +{gained_liters:.2f} л за {minutes:.0f} мин"),
        reply_markup=main_menu_kb()
    )
    await call.answer()

async def on_change_drink(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    db_ensure_user(user_id)

    drink = call.data.split(":", 1)[1]
    if drink not in DEFAULT_RATE:
        await call.answer("Неизвестный напиток", show_alert=True)
        return


    db_set_drink(user_id, drink)

    u2 = db_get_user(user_id)
    await call.message.edit_text(fmt_screen(u2, f"Напиток изменён: {DRINK_LABEL[drink]}"), reply_markup=main_menu_kb())
    await call.answer()



async def on_custom_drink_amount(message: Message, state: FSMContext):
    user_id = message.from_user.id
    db_ensure_user(user_id)
    u = db_get_user(user_id)
    rate = u.rate_for_current_drink()

    try:
        liters = float(message.text.replace(",", "."))
    except Exception:
        await message.answer("Не понял число. Пример: 0.5")
        return

    if liters <= 0 or liters > 20:
        await message.answer("Значение должно быть > 0 и разумным.")
        return

    delta_minutes = minutes_from_liters(liters, rate)
    new_minutes = u.balance_minutes - delta_minutes
    db_set_balance_minutes(user_id, new_minutes)

    await state.clear()
    u2 = db_get_user(user_id)
    await message.answer(fmt_screen(u2, f"Учтено: -{liters:.2f} л"), reply_markup=main_menu_kb())

async def on_custom_sport_minutes(message: Message, state: FSMContext):
    user_id = message.from_user.id
    db_ensure_user(user_id)
    u = db_get_user(user_id)

    try:
        minutes = float(message.text.replace(",", "."))
    except Exception:
        await message.answer("Не понял число. Пример: 60")
        return

    if minutes <= 0 or minutes > 600:
        await message.answer("Значение должно быть > 0 и разумным (до 600).")
        return

    new_minutes = u.balance_minutes + minutes
    db_set_balance_minutes(user_id, new_minutes)

    await state.clear()
    u2 = db_get_user(user_id)
    gained_liters = liters_from_minutes(minutes, u2.rate_for_current_drink())
    await message.answer(
        fmt_screen(u2, f"Учтено: +{gained_liters:.2f} л за {minutes:.0f} мин"),
        reply_markup=main_menu_kb()
    )



async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Не найден BOT_TOKEN в переменных окружения.")

    db_init()

    bot = Bot(token=token)
    dp = Dispatcher()

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_info, Command("info"))
    dp.message.register(cmd_change, Command("change"))
    dp.message.register(cmd_setrate, Command("setrate"))

    dp.callback_query.register(on_menu, F.data.startswith("menu:"))
    dp.callback_query.register(on_drink_choice, F.data.startswith("drink:"))
    dp.callback_query.register(on_sport_choice, F.data.startswith("sport:"))
    dp.callback_query.register(on_change_drink, F.data.startswith("change:"))

    dp.message.register(on_custom_drink_amount, InputStates.waiting_custom_drink_amount)
    dp.message.register(on_custom_sport_minutes, InputStates.waiting_custom_sport_minutes)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
