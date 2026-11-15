import re
from typing import Set, List, Dict

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
    'ch': 'ч', '4': 'ч',
    'sh': 'ш',
    'ya': 'я', 'r': 'я',
}

# Regex to detect Arabic, Persian, Devanagari, Hebrew characters
FOREIGN_SCRIPTS_REGEX = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\u0590-\u05FF\u0900-\u097F]')

# Comprehensive Adult / 18+ / Porn keywords and patterns
PORN_KEYWORDS = [
    # Russian roots & slang
    "порно", "порнух", "порнушк", "порнограф", "секс", "эротик", "интим", "интимн",
    "минет", "куни", "куннилингус", "дроч", "дрочил", "мастурб", "шлюх", "проститут",
    "эскорт", "вебкам", "webcam", "онлифанс", "онлик", "onlyfans", "нюдс", "нюдсы",
    "нюдес", "голая", "голые", "сиськи", "сисек", "сиська", "писька", "писечка",
    "влагалищ", "клитор", "пенис", "стояк", "сперм", "оргазм", "трах", "трахнул",
    "отсос", "сосалк", "сосать", "защекан", "голыедевушки", "сливы", "слившкур",
    "сливфото", "интимфото", "интимвидео", "интимки", "попочка", "попка", "анал", "анальн",
    "буккаке", "страпон", "бдсм", "фистинг", "дильдо", "вибратор",

    # English / International terms
    "porn", "porno", "xxx", "sex", "sexy", "nude", "nudes", "nudity", "nsfw",
    "hentai", "hentay", "erotic", "erotica", "boobs", "tits", "pussy", "dick",
    "cock", "blowjob", "cumpilation", "cumshot", "deepthroat", "anal", "creampie",
    "escort", "webcam", "strip", "stripper", "fetish", "milf", "bdsm"
]

# Short porn keywords that need bounded matching so they don't collide with 'канал', 'анализ', etc.
SHORT_PORN_BOUNDED = {
    "анал": re.compile(r'(?<![а-яёa-z])а[\s._\-*~]*н[\s._\-*~]*а[\s._\-*~]*л(?![а-яёa-z])', re.IGNORECASE),
    "член": re.compile(r'(?<![а-яёa-z])ч[\s._\-*~]*л[\s._\-*~]*е[\s._\-*~]*н(?![а-яёa-z])', re.IGNORECASE),
    "секс": re.compile(r'(?<![а-яёa-z])с[\s._\-*~]*е[\s._\-*~]*к[\s._\-*~]*с(?![а-яёa-z])', re.IGNORECASE),
    "sex": re.compile(r'(?<![а-яёa-z])s[\s._\-*~]*e[\s._\-*~]*x(?![а-яёa-z])', re.IGNORECASE),
    "porn": re.compile(r'(?<![а-яёa-z])p[\s._\-*~]*o[\s._\-*~]*r[\s._\-*~]*n(?![а-яёa-z])', re.IGNORECASE),
    "ххх": re.compile(r'(?<![а-яёa-z])х[\s._\-*~]*х[\s._\-*~]*х(?![а-яёa-z])', re.IGNORECASE),
    "xxx": re.compile(r'(?<![а-яёa-z])x[\s._\-*~]*x[\s._\-*~]*x(?![а-яёa-z])', re.IGNORECASE),
    "18+": re.compile(r'18\s*\+', re.IGNORECASE),
}

# Scam, fraud and unsolicited commercial advertising phrases
SPAM_PHRASES = [
    "заработок в интернете", "пассивный доход", "набираю команду",
    "ищу людей в команду", "работа для студентов", "работа для мам",
    "работа на дому", "выплаты каждый день", "доход от 5000",
    "доход от 10000", "доход от 1000", "в день без опыта", "без вложений",
    "легкий заработок", "заработок от", "доход от",
    "пиши в лс за подробностями", "напиши в лс", "подробности в лс",
    "в профиле ссылка", "переходи по ссылке в описании", "ссылка в описании профиля",
    "криптовалюта заработок", "бесплатные сигналы", "раскрутка счета",
    "ставках на спорт", "дарю подарок", "заберите свой подарок",
    "ищу моделей", "требуются модели", "слив интим",
    "канал со сливами", "все сливы тут", "арбитраж крипты", "крипто бот",
    "быстрый заработок", "легкие деньги", "онлайн казино", "бонус при регистрации",
    "получи 5000 рублей", "переходи в канал", "жми на ссылку", "вступай в закрытый канал"
]

# Obscene Russian profanity (Russian Mat) regex patterns
# Engineered to catch ANY prefixes and endings of obscene roots while protecting safe words (рубль, оскорблять, колебаться)
PROFANITY_PATTERNS = [
    # 1. ХУЙ (хуй, хуя, хуе, хуи, хую, нахуй, похуй, дохуя, нихуя, схуяли, хуйня, хуета, хуила, хуесос, хули, хуле, отхуярить, etc.)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[опанавыразсбедонидопризапере]*[хx][\s._\-*~]*[уy][\s._\-*~]*[йиеяюеёl]|хули|хуле)', re.IGNORECASE),

    # 2. ПИЗД (пизда, пиздец, спиздил, распиздяй, пиздюк, допизделся, отпиздить, впизду, etc.)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[свыразприрасдоотв]*[пn][\s._\-*~]*[иi1!][\s._\-*~]*[зz3][\s._\-*~]*[дd])', re.IGNORECASE),

    # 3. ЕБ / ЁБ / ЕБЛ (ебать, ебу, ебет, ебут, ебал, ебаный, ёбаный, заебал, выебал, наебал, подъебал, приебался, доебался, отъебись, съебись, переебал, ебло, ебало, ебанат)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:(?:за|вы|по|пере|под|подъ|подь|при|об|от|отъ|на|раз|разъ|разье|у|съ|сь|с|не|до|в|долбо|мозго)?(?:[еёe][\s._\-*~]*[бb6][\s._\-*~]*[аеёулиоы]|ебло|ебла|ебли|ебле|ебуч|ебат))', re.IGNORECASE),

    # 4. УЕБОК, ДОЛБОЕБ
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:долбо[её]б[а-я]*|у[её]б[оы][кч][а-я]*|у[её]бищ[а-я]*)', re.IGNORECASE),

    # 5. БЛЯ (блядь, блять, бляди, блядина, блядство, бля, бляха)
    # Strictly disallowing prefixes like руб-, оскор-, употре-, влю-
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:[ппо]*[бb6][\s._\-*~]*[лl][\s._\-*~]*[яy][\s._\-*~]*(?:[дт][ьэеи]?|дин[а-я]*|дств[а-я]*|х[а-я]*)?)(?![а-яёa-z])', re.IGNORECASE),

    # 6. ХЕР (хер, хера, херу, хером, похер, нахер, с хера, херово, нихера)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:(?:по|на|ни|до|с|о)?(?:[хx][\s._\-*~]*[еёe][\s._\-*~]*[рr][\s._\-*~]*[аеиоуеёы]?[а-я]*))(?![а-яёa-z])', re.IGNORECASE),

    # 7. СУКА (сука, суки, сучка, сучара, сучий)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))[сc$][\s._\-*~]*[уy][\s._\-*~]*[кk][\s._\-*~]*[аеиуой]', re.IGNORECASE),

    # 8. МУДАК, МУДИЛА, ГОНДОН, ГАНДОН, ЗАЛУПА, МАНДА
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:мудак[а-я]*|мудил[а-я]*|мудозвон[а-я]*|гондон[а-я]*|гандон[а-я]*|залуп[а-я]*|манда|манды|манде|манду|мандой|мандовошк[а-я]*)', re.IGNORECASE),

    # 9. ПИДОР, ПИДОРАС, ПЕДИК, ПИДРИЛА (excluding скипидар)
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?<!ски)(?:пидор[а-я]*|пидар[а-я]*|пидрила|педик[а-я]*|пидераст[а-я]*)', re.IGNORECASE),

    # 10. ШЛЮХА, ШАЛАВА, ПРОСТИТУТКА, КУРВА, ЛЯРВА, ПОТАСКУХА
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:шлюх[а-я]*|шалав[а-я]*|проститут[а-я]*|курва|лярв[а-я]*|потаскух[а-я]*)', re.IGNORECASE),

    # 11. ДРОЧИТЬ, ЗАДРОТ, ДРОЧЕР
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:дроч[а-я]*|задрот[а-я]*)', re.IGNORECASE),

    # 12. ОТСОС, ОТСОСИ, СОСИ ХУЙ
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:отсос[а-я]*|соси|отсоси|защекан[а-я]*)', re.IGNORECASE),

    # 13. ЖОПА, ГОВНО, ГАВНО, ОБОСРАЛСЯ, СРАТЬ, ССАТЬ, ДЕРЬМО
    re.compile(r'(?:^|(?<=[^а-яёa-z]))(?:жоп[аеуыо][а-я]*|говн[а-я]*|гавн[а-я]*|дерьм[а-я]*|обоср[а-я]*|засран[а-я]*|обосс[а-я]*|ссанин[а-я]*)', re.IGNORECASE)
]

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
    text = "".join(normalized_chars)
    
    return text


def get_collapsed_text(text: str) -> str:
    """
    Removes all non-alphanumeric characters and whitespace to catch spaced/dotted words
    e.g. 'п_о_р_н_о' -> 'порно', 'с.е.к.с' -> 'секс'
    """
    return re.sub(r'[^a-zа-я0-9]', '', text.lower())
