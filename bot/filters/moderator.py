import re
import time
from typing import Optional, List, Tuple, Dict
from urllib.parse import urlparse
from pydantic import BaseModel
from aiogram.types import Message

from .word_lists import (
    normalize_text,
    get_collapsed_text,
    FOREIGN_SCRIPTS_REGEX,
    PORN_KEYWORDS,
    SHORT_PORN_BOUNDED,
    SPAM_PHRASES,
    PROFANITY_PATTERNS,
    SUSPICIOUS_LINK_PATTERNS
)


class ModerationResult(BaseModel):
    is_violation: bool
    reason: str = ""
    category: str = ""  # 'porn', 'spam', 'flood', 'link', 'foreign', 'profanity', 'blacklist', 'media', 'service'
    matched_detail: str = ""


class MessageModerator:
    def __init__(self, flood_limit: int = 4, flood_window: int = 6):
        self.flood_limit = flood_limit
        self.flood_window = flood_window
        # { (chat_id, user_id): [timestamps] }
        self._user_msg_times: Dict[Tuple[int, int], List[float]] = {}

    def check_flood(self, chat_id: int, user_id: int) -> bool:
        """Rate limit: returns True if user is flooding."""
        now = time.time()
        key = (chat_id, user_id)
        timestamps = self._user_msg_times.get(key, [])
        # Keep only recent within window
        valid = [t for t in timestamps if now - t < self.flood_window]
        valid.append(now)
        self._user_msg_times[key] = valid
        return len(valid) > self.flood_limit

    def extract_all_text(self, message: Message) -> str:
        """Extracts text, caption, or poll question from a message."""
        parts = []
        if message.text:
            parts.append(message.text)
        if message.caption:
            parts.append(message.caption)
        if message.poll:
            parts.append(message.poll.question)
            for opt in message.poll.options:
                parts.append(opt.text)
        return " ".join(parts)

    def extract_urls_and_mentions(self, message: Message) -> Tuple[List[str], List[str]]:
        """
        Extracts URLs and @mentions from message text, caption and Telegram entities
        (including hidden markdown links).
        """
        urls = []
        mentions = []

        raw_text = self.extract_all_text(message)

        # 1. Regex find direct URLs
        url_regex = re.compile(
            r'(?:https?://|www\.|t\.me/|telegram\.me/)[^\s]+',
            re.IGNORECASE
        )
        for u in url_regex.findall(raw_text):
            urls.append(u.strip('.,!?)('))

        # 2. Check entities for hidden links (text_link, url, mention)
        entities = (message.entities or []) + (message.caption_entities or [])
        text_source = message.text or message.caption or ""
        
        for ent in entities:
            if ent.type == "text_link" and ent.url:
                urls.append(ent.url)
            elif ent.type == "url":
                val = text_source[ent.offset : ent.offset + ent.length]
                urls.append(val)
            elif ent.type == "mention":
                val = text_source[ent.offset : ent.offset + ent.length]
                mentions.append(val)

        return urls, mentions

    def check_message(
        self,
        message: Message,
        chat_settings: dict,
        custom_blacklist: List[str],
        custom_whitelist: List[str],
        whitelisted_domains: List[str]
    ) -> ModerationResult:
        """
        Comprehensive evaluation of message against active filters.
        """
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id

        # 1. Service messages (user join/leave/pin)
        if chat_settings.get("delete_service", 1):
            if (
                message.new_chat_members
                or message.left_chat_member
                or message.pinned_message
                or message.new_chat_title
                or message.new_chat_photo
                or message.delete_chat_photo
            ):
                return ModerationResult(
                    is_violation=True,
                    category="service",
                    reason="Служебное сервисное сообщение",
                    matched_detail="service_message"
                )

        # 2. Anti-Flood Check
        if chat_settings.get("anti_flood", 1) and user_id:
            if self.check_flood(chat_id, user_id):
                return ModerationResult(
                    is_violation=True,
                    category="flood",
                    reason="Флуд (слишком много сообщений подряд)",
                    matched_detail=f">{self.flood_limit} сообщений за {self.flood_window}с"
                )

        # 3. Block Media Check (if chat strictly disables media from non-admins)
        if chat_settings.get("block_media", 0):
            if (
                message.photo
                or message.video
                or message.video_note
                or message.voice
                or message.sticker
                or message.animation
            ):
                return ModerationResult(
                    is_violation=True,
                    category="media",
                    reason="Медиафайлы запрещены настройками чата",
                    matched_detail="photo/video/sticker"
                )

        raw_text = self.extract_all_text(message)
        if not raw_text:
            return ModerationResult(is_violation=False)

        norm_text = normalize_text(raw_text)
        collapsed_text = get_collapsed_text(norm_text)

        # Check whitelist first (if message matches custom whitelist, allow it)
        for w_word in custom_whitelist:
            w_norm = normalize_text(w_word)
            if w_norm and w_norm in norm_text:
                return ModerationResult(is_violation=False)

        # 4. Foreign Scripts (Arabic, Persian, Hebrew, Devanagari spam bots)
        if chat_settings.get("anti_foreign", 1):
            if FOREIGN_SCRIPTS_REGEX.search(raw_text):
                return ModerationResult(
                    is_violation=True,
                    category="foreign",
                    reason="Иностранный спам-алфавит (арабский/персидский и др.)",
                    matched_detail=raw_text[:60]
                )

        # 5. Anti-Porn / Adult Content
        if chat_settings.get("anti_porn", 1):
            # First check short bounded porn words (avoid collisions with 'канал', etc.)
            for kw_short, pat_short in SHORT_PORN_BOUNDED.items():
                if pat_short.search(norm_text):
                    return ModerationResult(
                        is_violation=True,
                        category="porn",
                        reason="18+ / Эротика / Порнография / Эскорт",
                        matched_detail=kw_short
                    )

            # Check general porn keywords
            for kw in PORN_KEYWORDS:
                if kw in SHORT_PORN_BOUNDED:
                    continue
                pattern = r'\b' + re.escape(kw)
                # Word boundary match in normalized text or collapsed
                if re.search(pattern, norm_text) or kw in collapsed_text:
                    return ModerationResult(
                        is_violation=True,
                        category="porn",
                        reason="18+ / Эротика / Порнография / Эскорт",
                        matched_detail=kw
                    )

        # 6. Anti-Spam / Scam Phrases
        if chat_settings.get("anti_spam", 1):
            # Check suspicious patterns (invite links t.me/+ etc)
            for pat in SUSPICIOUS_LINK_PATTERNS:
                if re.search(pat, raw_text, re.IGNORECASE):
                    return ModerationResult(
                        is_violation=True,
                        category="spam",
                        reason="Подозрительная ссылка / инвайт в приватный канал",
                        matched_detail=pat
                    )

            for phrase in SPAM_PHRASES:
                p_norm = normalize_text(phrase)
                if p_norm in norm_text or get_collapsed_text(p_norm) in collapsed_text:
                    return ModerationResult(
                        is_violation=True,
                        category="spam",
                        reason="Реклама / Спам / Скам-фраза",
                        matched_detail=phrase
                    )

        # 7. Anti-Links & Invites
        if chat_settings.get("anti_links", 1):
            urls, mentions = self.extract_urls_and_mentions(message)
            
            # Check URLs
            for url in urls:
                clean_url = url.lower().replace("https://", "").replace("http://", "").rstrip('/')
                parsed = urlparse(url if "://" in url else "https://" + url)
                domain = (parsed.netloc or parsed.path).lower()

                is_allowed = False
                for w_dom in whitelisted_domains:
                    w_clean = w_dom.lower().replace("https://", "").replace("http://", "").rstrip('/')
                    if w_clean and (w_clean in clean_url or domain == w_clean or domain.endswith("." + w_clean)):
                        is_allowed = True
                        break

                if not is_allowed:
                    return ModerationResult(
                        is_violation=True,
                        category="link",
                        reason="Запрещенная внешняя ссылка",
                        matched_detail=url
                    )

            # Check @channel mentions (often used to advertise other telegram channels in comments)
            for mention in mentions:
                is_allowed = False
                for w_dom in whitelisted_domains:
                    if w_dom.lower().lstrip('@') == mention.lower().lstrip('@'):
                        is_allowed = True
                        break
                if not is_allowed:
                    return ModerationResult(
                        is_violation=True,
                        category="link",
                        reason="Упоминание стороннего канала/аккаунта (@)",
                        matched_detail=mention
                    )

        # 8. Anti-Profanity (Russian Mat)
        if chat_settings.get("anti_profanity", 1):
            for pat in PROFANITY_PATTERNS:
                m = pat.search(norm_text)
                if m:
                    return ModerationResult(
                        is_violation=True,
                        category="profanity",
                        reason="Нецензурная брань (мат)",
                        matched_detail=m.group(0)[:30]
                    )

        # 9. Custom Chat Blacklist Words
        for b_word in custom_blacklist:
            b_norm = normalize_text(b_word)
            b_coll = get_collapsed_text(b_norm)
            if b_norm in norm_text or (b_coll and b_coll in collapsed_text):
                return ModerationResult(
                    is_violation=True,
                    category="blacklist",
                    reason="Пользовательский стоп-лист чата",
                    matched_detail=b_word
                )

        return ModerationResult(is_violation=False)
