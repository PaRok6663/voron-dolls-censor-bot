import re
from typing import Set, List

# Homoglyph translation map (Latin/numbers to Cyrillic equivalents)
HOMOGLYPHS = {
    'a': 'а', '@': 'а',
    'b': 'б', '6': 'б',
    'v': 'в', 'w': 'в',
    'g': 'г',
    'd': 'д',
    'e': 'е', '3': 'е', 'ё': 'е',
    'z': 'з',
    'i': 'и', '1': 'и', '!': 'и', '|': 'и', 'j': 'й',
    'k': 'к',
    'l': 'л',
    'm': 'м',
    'n': 'н',
    'o': 'о', '0': 'о',
    'p': 'р',
    'r': 'р',
    's': 'с', '$': 'с', 'c': 'с',
    't': 'т', '7': 'т',
    'u': 'у', 'y': 'у',
    'f': 'ф',
    'h': 'х', 'x': 'х',
    '4': 'ч'
}

# Regex to detect foreign scripts often used in Russian spam attacks:
# Arabic, Persian, Devanagari, Hebrew, etc.
FOREIGN_SCRIPTS_REGEX = re.compile(
    r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF'  # Arabic / Persian
    r'\u0900-\u097F'  # Devanagari
    r'\u0590-\u05FF'  # Hebrew
    r']+'
)

# Adult / Porn / 18+ Keywords & Patterns
PORN_KEYWORDS = [
    # Russian
    "порно", "порнух", "интим", "интимки", "интимные", "шлюх", "проститутк", "эскорт", 
    "вебкам", "webcam", "онлифанс", "онлик", "onlyfans", "минет", "куни", "куннилингус",
    "дроч", "мастурб", "оргазм", "трахн", "выеб", "ебля", "порноактрис", "сиськи", "сисек",
    "голая", "голые", "нюдс", "нюдсы", "нюдесы", "нюдисы", "nudes", "nude",
    "чпока", "дилдо", "вибратор", "камшот", "буккаке", "секс", "сексик", "секси",
    "трахат", "сосать", "отсос", "анал", "анальн", "клитор", "пенис", "вагин", "член",
    "стояк", "кончил", "кончаю", "кончи", "сперм", "сперма", "порнография", "18+", "ххх",
    "xxx", "porn", "porno", "hentai", "хентай", "эротик", "erotic", "nsfw",
    "сексчат", "сексвайб", "интимчат", "слив интим", "сливы интим", "слив малолеток",
    "сливы фото", "интим видео", "голые девушки", "голые фото", "интим фотки",
    "подглядыван", "сексшоп", "bonga", "bongacams", "chaturbate", "pornhub", "xvideos",
    "проституция", "блядство", "мамба", "сексвайб", "вирт", "интимвирт", "виртчат"
]

# Spam & Scam Phrases (frequently posted in craft / doll / commercial channel comments)
SPAM_PHRASES = [
    "заработок", "пассивный доход", "заработать от", "удаленная работа",
    "работа для девушек", "набираю команду", "ищу партнеров в проект",
    "ищу моделей", "подработка для мам", "работа на дому", "выплаты каждый день",
    "выплаты ежедневно", "легкие деньги", "без вложений", "доход в день",
    "ставки на спорт", "договорные матчи", "казино", "вулкан", "1xbet", "1win",
    "раскрутка счета", "раскрутка депозита", "арбитраж крипты", "криптосигналы",
    "сигналы на крипту", "слив курса", "сливы курсов", "бесплатные сигналы",
    "переходи по ссылке", "ссылка в профиле", "ссылка в описании", "смотри био",
    "чекни био", "в шапке профиля", "переходи в канал", "заходи ко мне",
    "дарю подарок", "забери подарок", "розыгрыш айфон", "выиграй iphone",
    "тебе одобрили", "получи выплату", "компенсация от государства",
    "напиши в лс", "пиши в личку за подробност", "отвечу в лс",
    "инвестиции от", "гарантированный доход", "трейдинг обучение",
    "пробив по базам", "глаз бога", "деанон", "взлом telegram",
    "накрутка подписчиков", "накрутка лайков", "дешевые подписчики"
]

# Obscene Russian profanity (Russian Mat) regex patterns
# Carefully designed to NOT trigger on safe words like 'рубль', 'рублей', 'оскорблять', 'колебаться'
PROFANITY_PATTERNS = [
    # хуй, хуя, хуе, хуи, хую, охуел, нахуй, похуй, хули, etc.
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[опанавыразсбедо]*[хx][\s._\-*~]*[уy][\s._\-*~]*[йиеяюеёl])', re.IGNORECASE),
    # пизд (пизда, пиздец, спиздил, etc.)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[свыразприрас]*[пn][\s._\-*~]*[иi1!][\s._\-*~]*[зz3][\s._\-*~]*[дd])', re.IGNORECASE),
    # ебат, ебан, ебут, ебет, заеб, выеб
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[завыпопереразподприобв]*[еёe][\s._\-*~]*[бb6][\s._\-*~]*[аеёулиоы])', re.IGNORECASE),
    # бля, блядь, блять (strictly word boundary or prefix, excluding рубля, оскорблять)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[ппо]*[бb6][\s._\-*~]*[лl][\s._\-*~]*[яy][\s._\-*~]*[дтх]?[ьэеа]?)(?![а-яёa-z])', re.IGNORECASE),
    # сука (когда отдельное слово или сучара)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))[сc$][\s._\-*~]*[уy][\s._\-*~]*[кk][\s._\-*~]*[аеиуой]?(?![а-яёa-z])', re.IGNORECASE),
    # мудак, пидор, гондон, залупа
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:мудак|мудил|гондон|гандон|залуп|пидор|пидар|манда)', re.IGNORECASE)
]

# Short porn keywords that need bounded matching so they don't collide with 'канал', 'анализ', etc.
SHORT_PORN_BOUNDED = {
    "анал": re.compile(r'(?<![а-яёa-z])а[\s._\-*~]*н[\s._\-*~]*а[\s._\-*~]*л(?![а-яёa-z])', re.IGNORECASE),
    "член": re.compile(r'(?<![а-яёa-z])ч[\s._\-*~]*л[\s._\-*~]*е[\s._\-*~]*н(?![а-яёa-z])', re.IGNORECASE),
    "секс": re.compile(r'(?<![а-яёa-z])с[\s._\-*~]*е[\s._\-*~]*к[\s._\-*~]*с(?![а-яёa-z])', re.IGNORECASE),
    "porn": re.compile(r'(?<![а-яёa-z])p[\s._\-*~]*o[\s._\-*~]*r[\s._\-*~]*n(?![а-яёa-z])', re.IGNORECASE),
    "ххх": re.compile(r'(?<![а-яёa-z])х[\s._\-*~]*х[\s._\-*~]*х(?![а-яёa-z])', re.IGNORECASE),
    "xxx": re.compile(r'(?<![а-яёa-z])x[\s._\-*~]*x[\s._\-*~]*x(?![а-яёa-z])', re.IGNORECASE),
    "18+": re.compile(r'18\s*\+', re.IGNORECASE),
}

# Suspicious URL shorteners or scam link formats
SUSPICIOUS_LINK_PATTERNS = [
    r't\.me/\+[a-zA-Z0-9_\-]+',        # Private Telegram invite link: t.me/+...
    r't\.me/joinchat/[a-zA-Z0-9_\-]+',  # Telegram joinchat link
    r'telegram\.me/\+[a-zA-Z0-9_\-]+',
    r'bit\.ly/',
    r'tinyurl\.com/',
    r'cutt\.ly/',
    r'goo\.su/',
    r'clck\.ru/',
    r'is\.gd/'
]


def normalize_text(text: str) -> str:
    """
    Cleans and normalizes text for robust censorship matching:
    - Lowercases
    - Strips zero-width characters and excessive spaces
    - Replaces homoglyphs (Latin characters mixed with Cyrillic, numbers looking like letters)
    - Strips repetitive punctuation like 'с.е.к.с' -> 'секс'
    """
    if not text:
        return ""
    
    text = text.lower()
    
    # Remove zero-width spaces, soft hyphens, zalgo marks
    text = re.sub(r'[\u200B-\u200D\uFEFF\u00AD]', '', text)
    
    # Replace homoglyphs
    normalized_chars = []
    for ch in text:
        normalized_chars.append(HOMOGLYPHS.get(ch, ch))
    text_norm = "".join(normalized_chars)
    
    # Also create a collapsed version with punctuation/spaces removed
    # (e.g. 'с. е. к. с.' or 'п_о_р_н_о' -> 'секс', 'порно')
    return text_norm


def get_collapsed_text(normalized_text: str) -> str:
    """Removes all non-alphanumeric characters for catching hidden words."""
    return re.sub(r'[^а-яёa-z0-9]', '', normalized_text)
