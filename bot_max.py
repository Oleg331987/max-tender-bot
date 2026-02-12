# bot_max.py
import asyncio
import os
import logging
import aiohttp
from aiohttp import web
from dotenv import load_dotenv

from maxapi import Bot, Dispatcher, types
from maxapi.types import InlineKeyboardMarkup, InlineKeyboardButton
from maxapi.filters import Filters

import core  # ваша бизнес-логика

load_dotenv()

# === Конфигурация ===
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))  # Railway передаёт сюда порт

# === Логирование ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# === Инициализация бота и диспетчера ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# === Хранилища состояний ===
user_states = {}
message_to_user_map = {}

# === Клавиатуры (Inline) ===
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Прайс-лист (основные услуги)", callback_data="price_main")],
        [InlineKeyboardButton(text="🔐 Прайс ЭЦП для ФЛ", callback_data="price_ecp")],
        [InlineKeyboardButton(text="❓ Задать вопрос менеджеру", callback_data="manual_mode")],
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
    ])

# === Скачивание файлов ===
async def download_file(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.read()

# === ОБРАБОТЧИКИ (ваши, без изменений) ===
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.chat.id
    user_states[user_id] = "main"
    logger.info(f"User {user_id} started bot")
    await message.reply(
        "👋 Добро пожаловать в ООО 'Тритика'!\n\nВыберите действие:",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query_handler(func=lambda call: call.data == "price_main")
async def callback_price_main(call: types.CallbackQuery):
    await call.answer()
    await bot.send_message(
        chat_id=call.from_user.id,
        text=core.get_price_list(),
        reply_markup=get_main_keyboard()
    )

@dp.callback_query_handler(func=lambda call: call.data == "price_ecp")
async def callback_price_ecp(call: types.CallbackQuery):
    await call.answer()
    await bot.send_message(
        chat_id=call.from_user.id,
        text=core.get_ecp_price(),
        reply_markup=get_main_keyboard()
    )

@dp.callback_query_handler(func=lambda call: call.data == "manual_mode")
async def callback_manual_mode(call: types.CallbackQuery):
    user_id = call.from_user.id
    user_states[user_id] = "manual_mode"
    await call.answer("Режим ручного общения активирован")
    user_info = f"{call.from_user.first_name} (@{call.from_user.username or 'нет'}, ID: {user_id})"
    manager_text = f"⚠️ ПОЛЬЗОВАТЕЛЬ ПЕРЕШЕЛ В РЕЖИМ РУЧНОГО ОБЩЕНИЯ\n\n👤 {user_info}"
    sent = await bot.send_message(MANAGER_CHAT_ID, manager_text)
    message_to_user_map[sent.message_id] = user_id
    await bot.send_message(
        chat_id=user_id,
        text="💬 <b>Режим диалога с менеджером активирован!</b>\n\nОтправьте ваш вопрос. Для возврата в меню нажмите кнопку ниже.",
        reply_markup=get_back_keyboard(),
        parse_mode="html"
    )

@dp.callback_query_handler(func=lambda call: call.data == "back_to_menu")
async def callback_back_to_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    user_states[user_id] = "main"
    await call.answer("Возврат в меню")
    await bot.send_message(
        chat_id=user_id,
        text="Главное меню:",
        reply_markup=get_main_keyboard()
    )

@dp.message_handler(content_types=['text'])
async def handle_text(message: types.Message):
    user_id = message.chat.id
    text = message.text
    state = user_states.get(user_id, "main")
    if state == "manual_mode":
        user_info = f"{message.from_user.first_name} (@{message.from_user.username or 'нет'}, ID: {user_id})"
        forward_text = f"📩 <b>Сообщение от пользователя:</b>\n\n{user_info}\n\n{text}"
        sent = await bot.send_message(MANAGER_CHAT_ID, forward_text, parse_mode="html")
        message_to_user_map[sent.message_id] = user_id
        await message.reply(
            "✅ Ваше сообщение переслано менеджеру. Он ответит вам в ближайшее время.",
            reply_markup=get_back_keyboard()
        )
        return
    try:
        await bot.send_message(ADMIN_CHAT_ID, f"📨 Запрос от {message.from_user.first_name} (ID: {user_id}):\n{text[:200]}")
    except: pass
    await bot.send_chat_action(user_id, "typing")
    await message.reply("⏳ Обрабатываю ваш запрос...")
    response = await core.chat_completion(text)
    await bot.send_message(chat_id=user_id, text=response, reply_markup=get_main_keyboard())

@dp.message_handler(content_types=['document', 'photo'])
async def handle_document(message: types.Message):
    user_id = message.chat.id
    state = user_states.get(user_id, "main")
    file_info = message.document or (message.photo[-1] if message.photo else None)
    if not file_info:
        await message.reply("Не удалось обработать вложение.")
        return
    if state == "manual_mode":
        user_info = f"{message.from_user.first_name} (@{message.from_user.username or 'нет'}, ID: {user_id})"
        file_data = await download_file(file_info.url)
        caption = f"📎 Вложение от {user_info}"
        await bot.send_document(
            chat_id=MANAGER_CHAT_ID,
            document=file_data,
            filename=file_info.name or "file",
            caption=caption
        )
        await message.reply("✅ Файл переслан менеджеру.", reply_markup=get_back_keyboard())
        return
    await message.reply("⏳ Скачиваю и анализирую документ...")
    file_data = await download_file(file_info.url)
    file_name = file_info.name or "document"
    file_text = await core.extract_text_from_document(file_data, file_name)
    if not file_text.strip():
        await message.reply("❌ Не удалось извлечь текст из файла.")
        return
    prompt = f"Проанализируй этот документ о закупке: {file_text}"
    response = await core.chat_completion(prompt)
    await bot.send_message(chat_id=user_id, text=response, reply_markup=get_main_keyboard())

@dp.message_handler(Filters.chat(chat_id=MANAGER_CHAT_ID), Filters.reply)
async def handle_manager_reply(message: types.Message):
    replied_msg = message.reply_to_message
    original_user_id = message_to_user_map.get(replied_msg.message_id)
    if original_user_id:
        await bot.send_message(
            chat_id=original_user_id,
            text=f"💬 <b>Ответ от менеджера:</b>\n\n{message.text}",
            parse_mode="html"
        )
        await message.reply("✅ Ответ отправлен пользователю.")
        del message_to_user_map[replied_msg.message_id]
    else:
        await message.reply("❌ Не удалось найти пользователя для этого сообщения.")

# === HEALTH-CHECK СЕРВЕР ДЛЯ RAILWAY ===
async def health_check(request):
    """Простой ответ для проверки, что приложение живо"""
    return web.Response(text="OK", status=200)

async def start_health_server():
    """Запуск HTTP сервера на PORT"""
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health-check server started on port {PORT}")
    # Держим сервер запущенным
    await asyncio.Event().wait()

# === ЗАПУСК ===
async def main():
    logger.info(f"Запуск бота с токеном: {BOT_TOKEN[:10]}...")
    # Запускаем polling и health-сервер одновременно
    polling_task = asyncio.create_task(dp.start_polling())
    health_task = asyncio.create_task(start_health_server())
    await asyncio.gather(polling_task, health_task)

if __name__ == "__main__":
    asyncio.run(main())
