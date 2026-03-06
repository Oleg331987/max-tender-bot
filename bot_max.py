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

# === ДИАГНОСТИКА: ВЫВОДИМ ВСЁ, ЧТО ЕСТЬ В maxapi И Dispatcher ===
logger.info("🔍 ========== ДИАГНОСТИКА maxapi ==========")
try:
    import maxapi
    logger.info(f"📦 maxapi root dir: {dir(maxapi)}")
    
    # Проверим основные подмодули
    for sub in ['types', 'handlers', 'filters', 'keyboard', 'inlinekeyboard']:
        try:
            module = __import__(f'maxapi.{sub}', fromlist=[''])
            logger.info(f"📦 maxapi.{sub} dir: {dir(module)}")
        except ImportError:
            logger.warning(f"⚠️ maxapi.{sub} not found")
except Exception as e:
    logger.exception("Error during maxapi introspection")

# === ИНИЦИАЛИЗАЦИЯ БОТА ===
try:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(bot)
    logger.info(f"✅ Bot initialized with token: {BOT_TOKEN[:10]}...")
except Exception as e:
    logger.exception("❌ Failed to initialize bot")
    sys.exit(1)

# === ДИАГНОСТИКА: АНАЛИЗИРУЕМ ОБЪЕКТ Dispatcher ===
logger.info("🔍 ========== АНАЛИЗ ОБЪЕКТА Dispatcher ==========")
logger.info(f"📦 dp type: {type(dp)}")
logger.info(f"📦 dp dir: {dir(dp)}")
logger.info(f"📦 dp methods (callable): {[m for m in dir(dp) if callable(getattr(dp, m, None)) and not m.startswith('_')]}")

# Проверим, есть ли атрибут 'handlers' или что-то похожее
handler_related = [attr for attr in dir(dp) if 'handler' in attr.lower()]
logger.info(f"📦 handler-related attributes: {handler_related}")

# === ИМПОРТ БИЗНЕС-ЛОГИКИ ===
try:
    import core
    logger.info("✅ core module imported")
except Exception as e:
    logger.exception("❌ Failed to import core module")
    sys.exit(1)

# === ХРАНИЛИЩА СОСТОЯНИЙ ===
user_states = {}
message_to_user_map = {}

# === ОПРЕДЕЛЕНИЕ ФУНКЦИЙ-ОБРАБОТЧИКОВ ===
async def cmd_start(message):
    try:
        user_id = message.chat.id
        user_states[user_id] = "main"
        logger.info(f"User {user_id} started bot")
        await message.reply(
            "👋 Добро пожаловать в ООО 'Тритика'!\n\nВыберите действие:",
            reply_markup=None  # Клавиатуры не поддерживаются, но можно добавить позже
        )
    except Exception as e:
        logger.exception(f"Error in cmd_start: {e}")

async def handle_text(message):
    try:
        user_id = message.chat.id
        text = message.text
        state = user_states.get(user_id, "main")
        
        if state == "manual_mode":
            user_info = f"{message.from_user.first_name} (@{message.from_user.username or 'нет'}, ID: {user_id})"
            forward_text = f"📩 <b>Сообщение от пользователя:</b>\n\n{user_info}\n\n{text}"
            sent = await bot.send_message(MANAGER_CHAT_ID, forward_text, parse_mode="html")
            message_to_user_map[sent.message_id] = user_id
            await message.reply(
                "✅ Ваше сообщение переслано менеджеру. Он ответит вам в ближайшее время."
            )
            return
        
        try:
            await bot.send_message(ADMIN_CHAT_ID, f"📨 Запрос от {message.from_user.first_name} (ID: {user_id}):\n{text[:200]}")
        except:
            pass
        
        await message.reply("⏳ Обрабатываю ваш запрос...")
        
        if asyncio.iscoroutinefunction(core.chat_completion):
            response = await core.chat_completion(text)
        else:
            response = await asyncio.to_thread(core.chat_completion, text)
        
        await bot.send_message(chat_id=user_id, text=response)
    except Exception as e:
        logger.exception(f"Error in handle_text: {e}")

async def handle_document(message):
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
        
        try:
            file_id = file_info.file_id
            file = await bot.get_file(file_id)
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    file_data = await resp.read()
        except Exception as e:
            logger.exception("Failed to download file")
            await message.reply("❌ Не удалось скачать файл.")
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
            await message.reply("✅ Файл переслан менеджеру.")
            return
        
        await message.reply("⏳ Анализирую документ...")
        
        if asyncio.iscoroutinefunction(core.extract_text_from_document):
            file_text = await core.extract_text_from_document(file_data, file_name)
        else:
            file_text = await asyncio.to_thread(core.extract_text_from_document, file_data, file_name)
        
        if not file_text.strip():
            await message.reply("❌ Не удалось извлечь текст.")
            return
        
        prompt = f"Проанализируй этот документ о закупке: {file_text}"
        if asyncio.iscoroutinefunction(core.chat_completion):
            response = await core.chat_completion(prompt)
        else:
            response = await asyncio.to_thread(core.chat_completion, prompt)
        
        await bot.send_message(chat_id=user_id, text=response)
    except Exception as e:
        logger.exception(f"Error in handle_document: {e}")

async def handle_manager_reply(message):
    try:
        if not message.reply_to_message:
            return
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
            await message.reply("❌ Не удалось найти пользователя.")
    except Exception as e:
        logger.exception(f"Error in handle_manager_reply: {e}")

# ========== РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ==========
def register_handlers():
    """Пытается зарегистрировать обработчики разными способами."""
    logger.info("🔍 ========== ПОПЫТКА РЕГИСТРАЦИИ ==========")

    # Способ 1: register_message_handler (aiogram 3.x style)
    if hasattr(dp, 'register_message_handler'):
        logger.info("✅ Using register_message_handler")
        dp.register_message_handler(cmd_start, commands=['start'])
        dp.register_message_handler(handle_text, content_types=['text'])
        dp.register_message_handler(handle_document, content_types=['document', 'photo'])
        dp.register_message_handler(handle_manager_reply, 
                                    lambda msg: msg.chat.id == MANAGER_CHAT_ID and msg.reply_to_message)
        return True

    # Способ 2: add_handler (python-telegram-bot style)
    if hasattr(dp, 'add_handler'):
        logger.info("✅ Using add_handler")
        try:
            # Попробуем импортировать классы хэндлеров из maxapi.handlers
            from maxapi.handlers import MessageHandler, CommandHandler
            # Также нужен Filters, если есть
            try:
                from maxapi.filters import Filters
            except ImportError:
                Filters = None
                logger.warning("Filters not found, using dict filters")

            dp.add_handler(CommandHandler('start', cmd_start))
            
            if Filters:
                dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
                dp.add_handler(MessageHandler(Filters.document | Filters.photo, handle_document))
                dp.add_handler(MessageHandler(Filters.chat(MANAGER_CHAT_ID) & Filters.reply, handle_manager_reply))
            else:
                # Используем фильтры в виде словаря
                dp.add_handler(MessageHandler(handle_text, {'content_types': ['text']}))
                dp.add_handler(MessageHandler(handle_document, {'content_types': ['document', 'photo']}))
                dp.add_handler(MessageHandler(handle_manager_reply, {'chat_id': MANAGER_CHAT_ID, 'reply': True}))
            return True
        except ImportError as e:
            logger.warning(f"Could not import handlers from maxapi.handlers: {e}")
            # Универсальный способ: передаём кортеж (функция, фильтр)
            dp.add_handler((cmd_start, {'commands': ['start']}))
            dp.add_handler((handle_text, {'content_types': ['text']}))
            dp.add_handler((handle_document, {'content_types': ['document', 'photo']}))
            dp.add_handler((handle_manager_reply, {'chat_id': MANAGER_CHAT_ID, 'reply': True}))
            return True

    # Способ 3: декораторный стиль (если есть message_handler)
    if hasattr(dp, 'message_handler'):
        logger.info("✅ Using message_handler decorator style")
        dp.message_handler(commands=['start'])(cmd_start)
        dp.message_handler(content_types=['text'])(handle_text)
        dp.message_handler(content_types=['document', 'photo'])(handle_document)
        dp.message_handler(lambda msg: msg.chat.id == MANAGER_CHAT_ID and msg.reply_to_message)(handle_manager_reply)
        return True

    logger.error("❌ No known registration method found. Handlers will NOT be registered.")
    return False

# Пытаемся зарегистрировать обработчики
handlers_registered = register_handlers()
if not handlers_registered:
    logger.error("❌ Handlers registration failed. Bot will not respond to messages.")
else:
    logger.info("✅ Handlers registration attempted. Check logs above to confirm method used.")

# ========== HEALTH-CHECK СЕРВЕР ==========
async def health_check(request):
    status = f"Bot is alive. Handlers registered: {handlers_registered}"
    logger.debug("Healthcheck ping received")
    return web.Response(text=status, status=200)

async def run_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
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
            # ВАЖНО: передаём bot в start_polling, как требует ошибка
            await dp.start_polling(bot)
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
