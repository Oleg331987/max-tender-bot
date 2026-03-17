import os
import json
import logging
import tempfile
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import aiohttp  # оставим для скачивания файлов, если нужно асинхронно, но можно и requests
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# === Конфигурация ===
BOT_TOKEN = os.getenv('MAX_BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("MAX_BOT_TOKEN not set")
    exit(1)

ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', 0))
MANAGER_CHAT_ID = int(os.getenv('MANAGER_CHAT_ID', 0))
if ADMIN_CHAT_ID == 0 or MANAGER_CHAT_ID == 0:
    logger.error("ADMIN_CHAT_ID and MANAGER_CHAT_ID must be set")
    exit(1)

MAX_API_URL = 'https://platform-api.max.ru'

# === Хранилища состояний ===
user_states = {}          # user_id -> состояние (например, "main", "manual_mode")
message_to_user_map = {}  # message_id -> user_id (для ответов менеджера)

# === Импорт бизнес-логики ===
try:
    import core  # ваш модуль с функциями chat_completion и extract_text_from_document
    logger.info("Core module imported")
except ImportError as e:
    logger.error(f"Failed to import core: {e}")
    exit(1)

# === Вспомогательные функции для работы с MAX API ===

def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    """Отправка текстового сообщения"""
    url = f"{MAX_API_URL}/sendMessage"
    headers = {'Authorization': BOT_TOKEN}
    data = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        data['parse_mode'] = parse_mode
    if reply_markup:
        data['reply_markup'] = reply_markup
    try:
        r = requests.post(url, headers=headers, json=data)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"send_message error: {e}")
        return None

def send_document(chat_id, file_data, filename, caption=None):
    """Отправка документа"""
    url = f"{MAX_API_URL}/sendDocument"
    headers = {'Authorization': BOT_TOKEN}
    files = {'document': (filename, file_data)}
    data = {'chat_id': chat_id}
    if caption:
        data['caption'] = caption
    try:
        r = requests.post(url, headers=headers, data=data, files=files)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"send_document error: {e}")
        return None

def get_file(file_id):
    """Получение информации о файле и его содержимого"""
    # 1. Получаем file_path
    url = f"{MAX_API_URL}/getFile?file_id={file_id}"
    headers = {'Authorization': BOT_TOKEN}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    file_info = r.json()
    file_path = file_info['result']['file_path']
    
    # 2. Скачиваем файл
    file_url = f"{MAX_API_URL}/file/{file_path}?token={BOT_TOKEN}"
    r = requests.get(file_url)
    r.raise_for_status()
    return r.content

# === Обработчики команд и сообщений ===

def handle_start(chat_id):
    """Приветствие и установка состояния"""
    user_states[chat_id] = "main"
    send_message(chat_id, 
                 "👋 Добро пожаловать в ООО 'Тритика'!\n\nВыберите действие:",
                 reply_markup=None)  # при необходимости можно добавить клавиатуру

def handle_text(chat_id, text, user_info):
    """Обработка текстовых сообщений"""
    state = user_states.get(chat_id, "main")
    
    if state == "manual_mode":
        # Пересылка менеджеру
        forward_text = f"📩 <b>Сообщение от пользователя:</b>\n\n{user_info}\n\n{text}"
        sent = send_message(MANAGER_CHAT_ID, forward_text, parse_mode="html")
        if sent and 'result' in sent:
            message_to_user_map[sent['result']['message_id']] = chat_id
        send_message(chat_id, "✅ Ваше сообщение переслано менеджеру. Он ответит вам в ближайшее время.")
        return
    
    # Уведомление администратору
    try:
        send_message(ADMIN_CHAT_ID, f"📨 Запрос от {user_info}:\n{text[:200]}")
    except:
        pass
    
    send_message(chat_id, "⏳ Обрабатываю ваш запрос...")
    
    # Вызов бизнес-логики (core.chat_completion может быть синхронной или асинхронной)
    try:
        if asyncio.iscoroutinefunction(core.chat_completion):
            # Если асинхронная, запускаем в цикле событий
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(core.chat_completion(text))
            loop.close()
        else:
            response = core.chat_completion(text)
        send_message(chat_id, response)
    except Exception as e:
        logger.exception("Error in chat_completion")
        send_message(chat_id, "❌ Произошла ошибка при обработке запроса.")

def handle_document(chat_id, file_id, file_name, user_info):
    """Обработка полученного документа/фото"""
    state = user_states.get(chat_id, "main")
    
    # Скачиваем файл
    try:
        file_data = get_file(file_id)
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        send_message(chat_id, "❌ Не удалось скачать файл.")
        return
    
    if state == "manual_mode":
        # Пересылка менеджеру
        caption = f"📎 Вложение от {user_info}"
        send_document(MANAGER_CHAT_ID, file_data, file_name, caption)
        send_message(chat_id, "✅ Файл переслан менеджеру.")
        return
    
    send_message(chat_id, "⏳ Анализирую документ...")
    
    # Извлечение текста из документа через core
    try:
        if asyncio.iscoroutinefunction(core.extract_text_from_document):
            loop = asyncio.new_event_loop()
            file_text = loop.run_until_complete(core.extract_text_from_document(file_data, file_name))
            loop.close()
        else:
            file_text = core.extract_text_from_document(file_data, file_name)
    except Exception as e:
        logger.exception("Error extracting text")
        send_message(chat_id, "❌ Не удалось извлечь текст из документа.")
        return
    
    if not file_text.strip():
        send_message(chat_id, "❌ Не удалось извлечь текст.")
        return
    
    # Анализ через chat_completion
    prompt = f"Проанализируй этот документ о закупке: {file_text}"
    try:
        if asyncio.iscoroutinefunction(core.chat_completion):
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(core.chat_completion(prompt))
            loop.close()
        else:
            response = core.chat_completion(prompt)
        send_message(chat_id, response)
    except Exception as e:
        logger.exception("Error in chat_completion for document")
        send_message(chat_id, "❌ Ошибка при анализе документа.")

def handle_manager_reply(chat_id, text, replied_msg_id):
    """Ответ менеджера пользователю"""
    original_user_id = message_to_user_map.pop(replied_msg_id, None)
    if original_user_id:
        send_message(original_user_id,
                     f"💬 <b>Ответ от менеджера:</b>\n\n{text}",
                     parse_mode="html")
        send_message(chat_id, "✅ Ответ отправлен пользователю.")
    else:
        send_message(chat_id, "❌ Не удалось найти пользователя.")

# === Webhook endpoint ===

@app.route('/webhook', methods=['POST'])
def webhook():
    """Главный обработчик входящих обновлений от MAX"""
    update = request.json
    logger.info(f"Update received: {json.dumps(update, ensure_ascii=False)}")
    
    try:
        update_type = update.get('update_type')
        
        if update_type == 'bot_started':
            chat_id = update['chat_id']
            handle_start(chat_id)
        
        elif update_type == 'new_message':
            message = update['message']
            chat_id = message['chat']['chat_id']
            
            # Информация о пользователе
            user = message.get('from', {})
            user_info = f"{user.get('first_name', '')} (@{user.get('username', 'нет')}, ID: {chat_id})"
            
            # Текст сообщения
            text = message.get('text', '')
            
            # Проверка на наличие документа/фото
            if 'document' in message:
                doc = message['document']
                file_id = doc['file_id']
                file_name = doc.get('file_name', 'document')
                handle_document(chat_id, file_id, file_name, user_info)
            elif 'photo' in message:
                # Берём последнее (самое большое) фото
                photo = message['photo'][-1]
                file_id = photo['file_id']
                file_name = 'photo.jpg'
                handle_document(chat_id, file_id, file_name, user_info)
            elif text:
                # Проверка на команды
                if text == '/start':
                    handle_start(chat_id)
                elif text == '/help':
                    send_message(chat_id, "Справка: ...")
                elif chat_id == MANAGER_CHAT_ID and message.get('reply_to_message'):
                    # Ответ менеджера на пересланное сообщение
                    replied = message['reply_to_message']
                    replied_msg_id = replied['message_id']
                    handle_manager_reply(chat_id, text, replied_msg_id)
                else:
                    # Обычное текстовое сообщение
                    handle_text(chat_id, text, user_info)
            else:
                logger.warning("Unsupported message type")
    
    except Exception as e:
        logger.exception("Error processing update")
    
    return jsonify({'ok': True})

@app.route('/', methods=['GET'])
def index():
    return "Tender bot is running"

# === Для локального тестирования (необязательно) ===
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
