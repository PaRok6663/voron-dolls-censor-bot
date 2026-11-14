import aiosqlite
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "bot_data.sqlite3"):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Chat settings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS chat_settings (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    anti_porn INTEGER DEFAULT 1,
                    anti_spam INTEGER DEFAULT 1,
                    anti_flood INTEGER DEFAULT 1,
                    anti_links INTEGER DEFAULT 1,
                    anti_foreign INTEGER DEFAULT 1,
                    anti_profanity INTEGER DEFAULT 1,
                    delete_service INTEGER DEFAULT 1,
                    block_media INTEGER DEFAULT 0,
                    action_on_violation TEXT DEFAULT 'delete',
                    silent_mode INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Custom blacklist & whitelist words
            await db.execute("""
                CREATE TABLE IF NOT EXISTS custom_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    word TEXT,
                    word_type TEXT, -- 'blacklist' or 'whitelist'
                    UNIQUE(chat_id, word, word_type)
                )
            """)

            # 3. Whitelisted domains for links
            await db.execute("""
                CREATE TABLE IF NOT EXISTS whitelisted_domains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    domain TEXT,
                    UNIQUE(chat_id, domain)
                )
            """)

            # 4. User warnings
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_warnings (
                    chat_id INTEGER,
                    user_id INTEGER,
                    warning_count INTEGER DEFAULT 0,
                    last_warning_at TIMESTAMP,
                    PRIMARY KEY(chat_id, user_id)
                )
            """)

            # 5. Moderation log / stats
            await db.execute("""
                CREATE TABLE IF NOT EXISTS moderation_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    reason TEXT,
                    message_text TEXT,
                    action_taken TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()
            logger.info("Database initialized successfully.")

    async def get_chat_settings(self, chat_id: int, title: str = "") -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            if row:
                if title and row["title"] != title:
                    await db.execute("UPDATE chat_settings SET title = ? WHERE chat_id = ?", (title, chat_id))
                    await db.commit()
                    d = dict(row)
                    d["title"] = title
                    return d
                return dict(row)
            
            # Create default settings for new chat
            await db.execute("""
                INSERT OR IGNORE INTO chat_settings (
                    chat_id, title, anti_porn, anti_spam, anti_flood,
                    anti_links, anti_foreign, anti_profanity, delete_service,
                    block_media, action_on_violation, silent_mode
                ) VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 0, 'delete', 1)
            """, (chat_id, title))
            await db.commit()

            cursor = await db.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            return dict(row) if row else {}

    async def get_managed_chats(self) -> List[Dict[str, Any]]:
        """Returns all group / channel chats registered in the bot database."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM chat_settings WHERE chat_id < 0 ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def update_chat_setting(self, chat_id: int, key: str, value: Any):
        allowed_keys = {
            "anti_porn", "anti_spam", "anti_flood", "anti_links",
            "anti_foreign", "anti_profanity", "delete_service",
            "block_media", "action_on_violation", "silent_mode"
        }
        if key not in allowed_keys:
            raise ValueError(f"Invalid setting key: {key}")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE chat_settings SET {key} = ? WHERE chat_id = ?", (value, chat_id))
            await db.commit()

    async def add_custom_word(self, chat_id: int, word: str, word_type: str = "blacklist") -> bool:
        word = word.strip().lower()
        if not word:
            return False
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO custom_words (chat_id, word, word_type) VALUES (?, ?, ?)",
                    (chat_id, word, word_type)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def remove_custom_word(self, chat_id: int, word: str, word_type: str = "blacklist") -> bool:
        word = word.strip().lower()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM custom_words WHERE chat_id = ? AND word = ? AND word_type = ?",
                (chat_id, word, word_type)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_custom_words(self, chat_id: int, word_type: str = "blacklist") -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT word FROM custom_words WHERE chat_id = ? AND word_type = ?",
                (chat_id, word_type)
            )
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    async def add_whitelisted_domain(self, chat_id: int, domain: str) -> bool:
        domain = domain.strip().lower()
        if not domain:
            return False
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute(
                    "INSERT INTO whitelisted_domains (chat_id, domain) VALUES (?, ?)",
                    (chat_id, domain)
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def remove_whitelisted_domain(self, chat_id: int, domain: str) -> bool:
        domain = domain.strip().lower()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM whitelisted_domains WHERE chat_id = ? AND domain = ?",
                (chat_id, domain)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_whitelisted_domains(self, chat_id: int) -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT domain FROM whitelisted_domains WHERE chat_id = ?",
                (chat_id,)
            )
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    async def record_violation(self, chat_id: int, user_id: int, username: str, reason: str, text: str, action: str):
        async with aiosqlite.connect(self.db_path) as db:
            # 1. log
            await db.execute("""
                INSERT INTO moderation_logs (chat_id, user_id, username, reason, message_text, action_taken)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, user_id, username or "", reason, (text or "")[:400], action))

            # 2. warnings
            await db.execute("""
                INSERT INTO user_warnings (chat_id, user_id, warning_count, last_warning_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    warning_count = warning_count + 1,
                    last_warning_at = CURRENT_TIMESTAMP
            """, (chat_id, user_id))
            await db.commit()

    async def get_user_warnings(self, chat_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT warning_count FROM user_warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def reset_user_warnings(self, chat_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM user_warnings WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            await db.commit()

    async def get_chat_stats(self, chat_id: int) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM moderation_logs WHERE chat_id = ?",
                (chat_id,)
            )
            total = (await cursor.fetchone())[0]

            cursor = await db.execute("""
                SELECT reason, COUNT(*) as cnt 
                FROM moderation_logs 
                WHERE chat_id = ? 
                GROUP BY reason 
                ORDER BY cnt DESC 
                LIMIT 5
            """, (chat_id,))
            top_reasons = await cursor.fetchall()

            return {
                "total_deleted": total,
                "top_reasons": [(r[0], r[1]) for r in top_reasons]
            }
