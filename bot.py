import os
import asyncio
import logging
import sqlite3
import secrets
from aiohttp import web
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, ChatMemberUpdated,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, Update,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
RULES_URL = "https://telegra.ph/Pravila-chata-FOSTIN-CHAT-11-17"
GROUP_USERNAME = "fostin_chat"

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in your hosting environment.")
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

db = sqlite3.connect("fostin_bot.sqlite3")
db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
db.commit()
for admin_id in ADMIN_IDS:
    db.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (admin_id,))
db.commit()


def admins():
    return {row[0] for row in db.execute("SELECT user_id FROM admins").fetchall()}


def is_admin(user_id: int) -> bool:
    return user_id in admins()


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Правила чата"), KeyboardButton(text="🚨 Репорты")],
            [KeyboardButton(text="🛡 Администрация"), KeyboardButton(text="ℹ️ Помощь")],
            [KeyboardButton(text="📝 Unban | Fostin"), KeyboardButton(text="💼 Fostin Business")],
        ],
        resize_keyboard=True,
    )


class Flow(StatesGroup):
    business_coop = State()
    business_info = State()
    business_other = State()
    unban = State()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Это CHAT BOT для FOSTIN CHAT.\nВыбери нужный раздел в меню.",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("myid"))
async def myid(message: Message):
    await message.answer(f"Твой Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


@dp.message(Command("addadmin"))
async def add_admin(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /addadmin 123456789")
        return
    uid = int(parts[1])
    db.execute("INSERT OR IGNORE INTO admins(user_id) VALUES (?)", (uid,))
    db.commit()
    await message.answer(f"Администратор добавлен: {uid}. Он должен сначала открыть бота и нажать Start.")


@dp.message(Command("deladmin"))
async def del_admin(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /deladmin 123456789")
        return
    uid = int(parts[1])
    if uid == OWNER_ID:
        await message.answer("Владельца нельзя удалить из администраторов.")
        return
    db.execute("DELETE FROM admins WHERE user_id=?", (uid,))
    db.commit()
    await message.answer(f"Администратор удалён: {uid}")


@dp.message(F.new_chat_members)
async def welcome(message: Message):
    for member in message.new_chat_members:
        name = member.full_name
        await message.answer(f"Добро пожаловать, {name}! 👋")


@dp.message(F.text.casefold() == "!правила")
async def rules_command(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Правила", url=RULES_URL)]
    ])
    await message.reply(
        "😈 Чтобы не вылететь отсюда быстрее, чем зашёл, советуем ознакомиться с правилами.",
        reply_markup=kb,
    )


@dp.message(F.text.casefold() == "!репорт")
async def report_command(message: Message):
    if not message.reply_to_message:
        await message.reply("Ответь на сообщение нарушителя командой !репорт.")
        return
    target = message.reply_to_message.from_user
    if not target:
        await message.reply("Не удалось определить автора сообщения.")
        return
    reporter = message.from_user
    if target.id == reporter.id:
        await message.reply("Нельзя отправить репорт на себя.")
        return
    report_text = message.reply_to_message.text or message.reply_to_message.caption or "[сообщение без текста]"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Принять", callback_data=f"rep:yes:{message.chat.id}:{message.message_id}"),
        InlineKeyboardButton(text="Отклонить", callback_data=f"rep:no:{message.chat.id}:{message.message_id}"),
    ]])
    sent = 0
    for admin_id in admins():
        try:
            await bot.send_message(
                admin_id,
                "🚨 Новый репорт\n"
                f"От: {reporter.full_name} (@{reporter.username or 'нет'}) — ID {reporter.id}\n"
                f"На: {target.full_name} (@{target.username or 'нет'}) — ID {target.id}\n"
                f"Чат: {message.chat.title or message.chat.id}\n"
                f"Сообщение: {report_text}",
                reply_markup=kb,
            )
            sent += 1
        except Exception:
            pass
    await message.reply("Репорт отправлен администрации." if sent else
                        "Не удалось доставить репорт. Администраторы должны сначала нажать Start у бота.")


@dp.callback_query(F.data.startswith("rep:"))
async def report_decision(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    _, decision, chat_id, report_message_id = callback.data.split(":")
    result = "✅ Репорт принят" if decision == "yes" else "❌ Репорт отклонён"
    await callback.message.answer(f"{result}\nМодератор: {callback.from_user.full_name}")
    await callback.answer("Готово")


@dp.message(F.text == "📖 Правила чата")
async def menu_rules(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Правила", url=RULES_URL)]
    ])
    await message.answer("Ознакомься с правилами FOSTIN CHAT:", reply_markup=kb)


@dp.message(F.text == "🚨 Репорты")
async def reports_help(message: Message):
    await message.answer("Чтобы пожаловаться, ответь на сообщение пользователя командой !репорт.")


@dp.message(F.text == "🛡 Администрация")
async def administration(message: Message):
    names = []
    for uid in sorted(admins()):
        try:
            chat = await bot.get_chat(uid)
            names.append(f"• {chat.full_name} (@{chat.username or 'нет'})")
        except Exception:
            names.append(f"• ID {uid}")
    await message.answer("Администрация FOSTIN CHAT:\n" + ("\n".join(names) if names else "Пока не настроена."))


@dp.message(F.text == "ℹ️ Помощь")
async def help_message(message: Message):
    await message.answer(
        "Команды в группе:\n"
        "• !правила — ссылка на правила\n"
        "• ответ на сообщение + !репорт — жалоба администрации\n\n"
        "Для личных обращений используй Fostin Business или Unban."
    )


@dp.message(F.text == "📝 Unban | Fostin")
async def unban_start(message: Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("Открой бота в личных сообщениях и нажми Start, затем выбери Unban | Fostin.")
        return
    await state.set_state(Flow.unban)
    await message.answer(
        "📝 Заявка на разблокировку в FOSTIN CHAT\n\n"
        "❗️ ЕСЛИ ВАШ АККАУНТ НАХОДИТСЯ В СКАМ-БАЗАХ, РАЗБЛОКИРОВКА НЕ ПРОИЗВОДИТСЯ! ❗️\n\n"
        "Отправь одним сообщением:\n"
        "1️⃣ Твой @username и примерную дату бана.\n"
        "2️⃣ Знаешь ли ты причину бана и какое правило могло быть нарушено?\n"
        "3️⃣ Подробно опиши обстоятельства произошедшего.\n"
        "4️⃣ Почему администрация должна пересмотреть наказание и почему это не повторится?\n\n"
        "Заявки без подробного объяснения рассматриваться не будут."
    )


@dp.message(Flow.unban)
async def unban_submit(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    user = message.from_user
    delivered = 0
    for admin_id in admins():
        try:
            await bot.send_message(
                admin_id,
                f"📝 Заявка на разбан\nОт: {user.full_name} (@{user.username or 'нет'}), ID {user.id}"
            )
            await bot.forward_message(admin_id, message.chat.id, message.message_id)
            delivered += 1
        except Exception:
            pass
    await state.clear()
    await message.answer("Заявка отправлена администрации." if delivered else
                         "Не удалось отправить заявку. Попробуй позже.")


@dp.message(F.text == "💼 Fostin Business")
async def business_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Сотрудничество", callback_data="biz:coop")],
        [InlineKeyboardButton(text="❗️Важная информация", callback_data="biz:info")],
        [InlineKeyboardButton(text="💬 Другое", callback_data="biz:other")],
    ])
    await message.answer("Выбери тему обращения:", reply_markup=kb)


@dp.callback_query(F.data.startswith("biz:"))
async def business_choice(callback: CallbackQuery, state: FSMContext):
    prompts = {
        "coop": ("Пришлите ссылку на продукт или канал, который вы хотите рекламировать.", Flow.business_coop),
        "info": ("Укажите тему, к которой относится данная информация.", Flow.business_info),
        "other": ("Укажите тему обращения.", Flow.business_other),
    }
    key = callback.data.split(":")[1]
    prompt, flow_state = prompts[key]
    await state.set_state(flow_state)
    await callback.message.answer(prompt)
    await callback.answer()


@dp.message(Flow.business_coop)
@dp.message(Flow.business_info)
@dp.message(Flow.business_other)
async def business_submit(message: Message, state: FSMContext):
    if message.chat.type != "private":
        return
    if not OWNER_ID:
        await message.answer("Раздел временно не настроен. Попробуй позже.")
        await state.clear()
        return
    user = message.from_user
    try:
        await bot.send_message(
            OWNER_ID,
            f"💼 Fostin Business\n"
            f"Раздел: {state_name(await state.get_state())}\n"
            f"От: {user.full_name} (@{user.username or 'нет'}), ID {user.id}"
        )
        await bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
        await message.answer("Обращение отправлено. Спасибо!")
    except Exception:
        await message.answer("Не удалось отправить обращение. Попробуй позже.")
    await state.clear()


def state_name(value):
    return {
        "Flow:business_coop": "Сотрудничество",
        "Flow:business_info": "Важная информация",
        "Flow:business_other": "Другое",
    }.get(value, "Обращение")


async def main():
    # Render Web Service: receive Telegram updates through a webhook.
    port = int(os.getenv("PORT", "10000"))
    external_url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not external_url:
        raise RuntimeError("Render did not provide RENDER_EXTERNAL_URL.")
    secret = os.getenv("WEBHOOK_SECRET") or secrets.token_urlsafe(24)

    app = web.Application()

    async def health(_request):
        return web.Response(text="FOSTIN bot is running")

    async def telegram_webhook(request):
        if request.match_info.get("secret") != secret:
            raise web.HTTPForbidden()
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
        return web.Response(text="OK")

    app.router.add_get("/", health)
    app.router.add_post("/webhook/{secret}", telegram_webhook)

    await bot.set_webhook(f"{external_url}/webhook/{secret}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Webhook server started on port %s", port)

    try:
        await asyncio.Event().wait()
    finally:
        await bot.delete_webhook()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())