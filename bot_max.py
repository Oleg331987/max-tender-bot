# bot_max.py
import asyncio
import os
import sys
import logging
import aiohttp
from aiohttp import web
from dotenv import load_dotenv

# === НАСТРОЙКА ЛОГГЕРА ===
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

logger.info("🚀 STARTING BOT_MAX.PY")

load_dotenv()

# === ПРОВЕРКА КРИТИЧЕСКИХ ПЕРЕМЕННЫХ ===
BOT_TOKEN = os.getenv("MAX_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ MAX_BOT_TOKEN is not set!")
    sys.exit(1)

try:
    ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
    MANAGER_CHAT_ID = int(os.getenv("MANAGER_CHAT_ID", "0"))
except ValueError:
    logger.error("❌ ADMIN_CHAT_ID or MANAGER_CHAT_ID must be integers!")
    sys.exit(1)

if ADMIN_CHAT_ID == 0 or MANAGER_CHAT_ID == 0:
    logger.error("❌ ADMIN_CHAT_ID and MANAGER_CHAT_ID must be set and non-zero!")
    sys.exit(1)

PORT = int(os.getenv("PORT", "8080"))
logger.info(f"✅ Configuration loaded: PORT={PORT}, ADMIN={ADMIN_CHAT_ID}, MANAGER={MANAGER_CHAT_ID}")

# === ИМПОРТ И ИНИЦИАЛИЗАЦИЯ MAXAPI ===
try:
    from maxapi import Bot, Dispatcher, types
    logger.info("✅ Core maxapi classes imported (Bot, Dispatcher, types)")
except ImportError as e:
    logger.exception("❌ Failed to import Bot/Dispatcher/types")
    sys.exit(1)

# === ИМПОРТ КЛАВИАТУР (Inline / Reply) ===
INLINE_SUPPORTED = False
InlineKeyboardMarkup = None
InlineKeyboardButton = None

# Поиск inline-клавиатур в разных местах
inline_import_paths = [
    ("maxapi.types", "InlineKeyboardMarkup", "InlineKeyboardButton"),
    ("maxapi.keyboard", "InlineKeyboardMarkup", "InlineKeyboardButton"),
    ("maxapi", "InlineKeyboardMarkup", "InlineKeyboardButton"),
]

for module_name, markup_name, button_name in inline_import_paths:
    try:
        module = __import__(module_name, fromlist=[markup_name, button_name])
        if hasattr(module, markup_name) and hasattr(module, button_name):
            InlineKeyboardMarkup = getattr(module, markup_name)
            InlineKeyboardButton = getattr(module, button_name)
            INLINE_SUPPORTED = True
            logger.info(f"✅ Inline keyboards found in {module_name}")
            break
    except ImportError:
        continue

if not INLINE_SUPPORTED:
    logger.warning("⚠️ Inline keyboards not found, will use reply keyboards only")

# Импортируем reply-клавиатуры (они точно должны быть)
try:
    from maxapi import ReplyKeyboardMarkup, KeyboardButton
    logger.info("✅ Reply keyboards imported from maxapi root")
except ImportError:
    try:
        from maxapi.keyboard import ReplyKeyboardMarkup, KeyboardButton
        logger.info("✅ Reply keyboards imported from maxapi.keyboard")
    except ImportError:
        logger.error("❌ Reply keyboards not found, bot cannot function without keyboards!")
        sys.exit(1)

# === ИМПОРТ БИЗНЕС-ЛОГИКИ ===
try:
    import core
    logger.info("✅ core module imported")
except Exception as e:
    logger.exception("❌ Failed to import core module")
    sys.exit(1)

# === ИНИЦИАЛИЗАЦИЯ БОТА ===
try:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(bot)
    logger.info(f"✅ Bot initialized with token: {BOT_TOKEN[:10]}...")
except Exception as e:
    logger.exception("❌ Failed to initialize bot")
    sys.exit(1)

# === ХРАНИЛИЩА СОСТОЯНИЙ ===
user_states = {}
message_to_user_map = {}

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    """Возвращает клавиатуру (inline, если поддерживается, иначе reply)."""
    if INLINE_SUPPORTED:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Прайс-лист (основные услуги)", callback_data="price_main")],
            [InlineKeyboardButton(text="🔐 Прайс ЭЦП для ФЛ", callback_data="price_ecp")],
            [InlineKeyboardButton(text="❓ Задать вопрос менеджеру", callback_data="manual_mode")],
        ])
    else:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📋 Прайс-лист (основные услуги)")],
                [KeyboardButton(text="🔐 Прайс ЭЦП для ФЛ")],
                [KeyboardButton(text="❓ Задать вопрос менеджеру")],
            ],
            resize_keyboard=True,
            one_time_keyboard=False
        )

def get_back_keyboard():
    """Кнопка возврата в меню."""
    if INLINE_SUPPORTED:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
        ])
    else:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="◀️ Назад в меню")]],
            resize_keyboard=True
        )

# ========== СКАЧИВАНИЕ ФАЙЛОВ ==========
async def download_file(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.read()
            else:
                raise Exception(f"Failed to download file: {resp.status}")

# ========== ОБРАБОТЧИКИ ==========
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    try:
        user_id = message.chat.id
        user_states[user_id] = "main"
        logger.info(f"User {user_id} started bot")
        await message.reply(
            "👋 Добро пожаловать в ООО 'Тритика'!\n\nВыберите действие:",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.exception(f"Error in cmd_start: {e}")

# Обработчики callback-запросов (только если inline поддерживаются)
if INLINE_SUPPORTED:
    @dp.callback_query_handler(func=lambda call: call.data == "price_main")
    async def callback_price_main(call: types.CallbackQuery):
        try:
            await call.answer()
            await bot.send_message(
                chat_id=call.from_user.id,
                text=core.get_price_list(),
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.exception(f"Error in callback_price_main: {e}")

    @dp.callback_query_handler(func=lambda call: call.data == "price_ecp")
    async def callback_price_ecp(call: types.CallbackQuery):
        try:
            await call.answer()
            await bot.send_message(
                chat_id=call.from_user.id,
                text=core.get_ecp_price(),
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.exception(f"Error in callback_price_ecp: {e}")

    @dp.callback_query_handler(func=lambda call: call.data == "manual_mode")
    async def callback_manual_mode(call: types.CallbackQuery):
        try:
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
        except Exception as e:
            logger.exception(f"Error in callback_manual_mode: {e}")

    @dp.callback_query_handler(func=lambda call: call.data == "back_to_menu")
    async def callback_back_to_menu(call: types.CallbackQuery):
        try:
            user_id = call.from_user.id
            user_states[user_id] = "main"
            await call.answer("Возврат в меню")
            await bot.send_message(
                chat_id=user_id,
                text="Главное меню:",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.exception(f"Error in callback_back_to_menu: {e}")

# Обработка текстовых сообщений (включая reply-клавиатуру, если inline не поддерживается)
@dp.message_handler(content_types=['text'])
async def handle_text(message: types.Message):
    try:
        user_id = message.chat.id
        text = message.text
        state = user_states.get(user_id, "main")
        
        # Если используется reply-клавиатура, обрабатываем нажатия по тексту
        if not INLINE_SUPPORTED:
            if text == "📋 Прайс-лист (основные услуги)":
                await bot.send_message(user_id, core.get_price_list(), reply_markup=get_main_keyboard())
                return
            elif text == "🔐 Прайс ЭЦП для ФЛ":
                await bot.send_message(user_id, core.get_ecp_price(), reply_markup=get_main_keyboard())
                return
            elif text == "❓ Задать вопрос менеджеру":
                # Переход в ручной режим
                user_states[user_id] = "manual_mode"
                user_info = f"{message.from_user.first_name} (@{message.from_user.username or 'нет'}, ID: {user_id})"
                manager_text = f"⚠️ ПОЛЬЗОВАТЕЛЬ ПЕРЕШЕЛ В РЕЖИМ РУЧНОГО ОБЩЕНИЯ\n\n👤 {user_info}"
                sent = await bot.send_message(MANAGER_CHAT_ID, manager_text)
                message_to_user_map[sent.message_id] = user_id
                await bot.send_message(
                    chat_id=user_id,
                    text="💬 <b>Режим диалога с менеджером активирован!</b>\n\nОтправьте ваш вопрос. Для возврата в меню нажмите кнопку ниже.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="html"
                )
                return
            elif text == "◀️ Назад в меню":
                user_states[user_id] = "main"
                await bot.send_message(user_id, "Главное меню:", reply_markup=get_main_keyboard())
                return
        
        # Обычная обработка текста (когда не в режиме меню)
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
        except:
            pass
        
        # Отправляем "печатает..." если метод поддерживается
        try:
            await bot.send_chat_action(user_id, "typing")
        except:
            pass
        
        await message.reply("⏳ Обрабатываю ваш запрос...")
        
        if asyncio.iscoroutinefunction(core.chat_completion):
            response = await core.chat_completion(text)
        else:
            response = await asyncio.to_thread(core.chat_completion, text)
        
        await bot.send_message(chat_id=user_id, text=response, reply_markup=get_main_keyboard())
    except Exception as e:
        logger.exception(f"Error in handle_text: {e}")

@dp.message_handler(content_types=['document', 'photo'])
async def handle_document(message: types.Message):
    try:
        user_id = message.chat.id
        state = user_states.get(user_id, "main")
        
        if message.document:
            file_info = message.document
            file_name = file_info.name or "document"
        elif message.photo:
            file_info = message.photo[-1]
            file_name = "photo.jpg"
        else:
            await message.reply("Не удалось обработать вложение.")
            return
        
        # Получаем file_id и скачиваем файл через bot.get_file
        try:
            file_id = file_info.file_id
            file = await bot.get_file(file_id)
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
            file_data = await download_file(file_url)
        except Exception as e:
            logger.exception("Failed to download file via get_file")
            await message.reply("❌ Не удалось скачать файл. Попробуйте позже.")
            return
        
        if state == "manual_mode":
            user_info = f"{message.from_user.first_name} (@{message.from_user.username or 'нет'}, ID: {user_id})"
            caption = f"📎 Вложение от {user_info}"
            await bot.send_document(
                chat_id=MANAGER_CHAT_ID,
                document=file_data,
                filename=file_name,
                caption=caption
            )
            await message.reply("✅ Файл переслан менеджеру.", reply_markup=get_back_keyboard())
            return
        
        await message.reply("⏳ Скачиваю и анализирую документ...")
        
        if asyncio.iscoroutinefunction(core.extract_text_from_document):
            file_text = await core.extract_text_from_document(file_data, file_name)
        else:
            file_text = await asyncio.to_thread(core.extract_text_from_document, file_data, file_name)
        
        if not file_text.strip():
            await message.reply("❌ Не удалось извлечь текст из файла. Убедитесь, что файл содержит текст.")
            return
        
        prompt = f"Проанализируй этот документ о закупке: {file_text}"
        if asyncio.iscoroutinefunction(core.chat_completion):
            response = await core.chat_completion(prompt)
        else:
            response = await asyncio.to_thread(core.chat_completion, prompt)
        
        await bot.send_message(chat_id=user_id, text=response, reply_markup=get_main_keyboard())
    except Exception as e:
        logger.exception(f"Error in handle_document: {e}")

# ВНИМАНИЕ: вместо Filters используем лямбда-функцию для фильтрации ответов менеджера
@dp.message_handler(lambda msg: msg.chat.id == MANAGER_CHAT_ID and msg.reply_to_message)
async def handle_manager_reply(message: types.Message):
    try:
        replied_msg = message.reply_to_message
        original_user_id = message_to_user_map.pop(replied_msg.message_id, None)
        if original_user_id:
            await bot.send_message(
                chat_id=original_user_id,
                text=f"💬 <b>Ответ от менеджера:</b>\n\n{message.text}",
                parse_mode="html"
            )
            await message.reply("✅ Ответ отправлен пользователю.")
        else:
            await message.reply("❌ Не удалось найти пользователя для этого сообщения.")
    except Exception as e:
        logger.exception(f"Error in handle_manager_reply: {e}")

# ========== HEALTH-CHECK СЕРВЕР ==========
async def health_check(request):
    logger.debug("Healthcheck ping received")
    return web.Response(text="OK", status=200)

async def run_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    
    try:
        await site.start()
        logger.info(f"✅ Health-check server is RUNNING on port {PORT}")
    except Exception as e:
        logger.exception(f"❌ Failed to start health server: {e}")
        return
    
    await asyncio.Event().wait()

# ========== ЗАПУСК POLLING С ЗАЩИТОЙ ==========
async def run_polling():
    while True:
        try:
            logger.info("🔄 Starting polling...")
            await dp.start_polling()
        except Exception as e:
            logger.exception(f"❌ Polling crashed: {e}")
            logger.info("🔄 Restarting polling in 5 seconds...")
            await asyncio.sleep(5)
            continue
        break

# ========== MAIN ==========
async def main():
    logger.info("🚀 Entered main()")
    
    health_task = asyncio.create_task(run_health_server())
    logger.info("✅ Health server task created")
    
    await asyncio.sleep(3)
    
    await run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"❌ Unhandled exception: {e}")
        sys.exit(1)
