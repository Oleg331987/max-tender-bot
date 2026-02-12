# core.py
import os
import base64
import uuid
import time
import tempfile
from aiohttp import ClientSession
from PyPDF2 import PdfReader
import docx

# ==== КОНФИГИ (читаем из .env) ====
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
GIGACHAT_CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

# ==== GigaChat Client (ваш оригинальный код) ====
TOKEN_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
SCOPE = "GIGACHAT_API_PERS"
_token_cache = {"access_token": None, "expires_at": 0}

def _encode_auth_key(client_id, client_secret):
    return base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

async def get_access_token():
    """Получение токена GigaChat (без изменений)"""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 10:
        return _token_cache["access_token"]
    # ... (ваш полный код из ТГ бота)
    # ВАЖНО: скопируйте сюда всю функцию get_access_token из вашего кода
    pass

async def chat_completion(message_text: str) -> str:
    """Запрос к GigaChat (без изменений)"""
    # ... (ваш полный код из ТГ бота)
    pass

# ==== ПРАЙС-ЛИСТЫ ====
def get_price_list() -> str:
    return """
📌 ПРАЙС-ЛИСТ ООО "ТРИТИКА" (основные услуги)
1. Базовое сопровождение по 44-ФЗ — от 7 000 ₽
...
"""  # Полностью скопируйте ваш текст

def get_ecp_price() -> str:
    return """
🔐 ПРАЙС ЭЦП для различных систем и площадок
...
"""

# ==== ОБРАБОТКА ФАЙЛОВ ====
async def extract_text_from_document(file_content: bytes, filename: str) -> str:
    """Извлечение текста из PDF/DOCX/TXT (ваш код)"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name
    
    try:
        if filename.lower().endswith('.pdf'):
            reader = PdfReader(tmp_path)
            text = "\n".join([page.extract_text() or "" for page in reader.pages])
        elif filename.lower().endswith('.docx'):
            doc = docx.Document(tmp_path)
            text = "\n".join([p.text for p in doc.paragraphs])
        else:
            with open(tmp_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
    finally:
        os.unlink(tmp_path)
    
    return text[:8000]  # Ограничение для GigaChat
