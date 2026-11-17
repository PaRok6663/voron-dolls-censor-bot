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
                    block_stickers INTEGER DEFAULT 0,
                    block_spoilers INTEGER DEFAULT 0,
                    action_on_violation TEXT DEFAULT 'delete',
                    silent_mode INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Safe column migrations for existing databases
            for col in ["block_stickers INTEGER DEFAULT 0", "block_spoilers INTEGER DEFAULT 0"]:
                try:
                    await db.execute(f"ALTER TABLE chat_settings ADD COLUMN {col}")
                except Exception:
                    pass

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

            # 6. Bot administrators (multi-account management)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    role TEXT DEFAULT 'admin', -- 'superadmin' or 'admin'
                    added_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 7. Telegram Business connections
            await db.execute("""
                CREATE TABLE IF NOT EXISTS business_connections (
                    connection_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    user_chat_id INTEGER,
                    can_reply INTEGER DEFAULT 0,
                    is_enabled INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()
            logger.info("Database initialized successfully.")

    # ---------------- Chat Settings ---------------- #

    async def get_chat_settings(self, chat_id: int, title: str = "") -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
            row = await cursor.fetchone()
            if row:
                if title and row["title"] != title:
                    await db.execute("UPDATE chat_settings SET title = ? WHERE chat_id = ?", (title, chat_id))
                    await db.commit()
                    row_dict = dict(row)
                    row_dict["title"] = title
                    return row_dict
                return dict(row)
            
            # Create default settings for new chat
            await db.execute("""
                INSERT OR IGNORE INTO chat_settings (
                    chat_id, title, anti_porn, anti_spam, anti_flood,
                    anti_links, anti_foreign, anti_profanity, delete_service,
                    block_media, block_stickers, block_spoilers, action_on_violation, silent_mode
                ) VALUES (?, ?, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 'delete', 1)
            """, (chat_id, title))
            await db.commit()

            cursor = await db.execute("SELECT * FROM chat_settings WHERE chat_id = ?", (chat_id,))
            new_row = await cursor.fetchone()
            return dict(new_row) if new_row else {}

    async def update_chat_setting(self, chat_id: int, key: str, value: Any):
        allowed_keys = {
            "anti_porn", "anti_spam", "anti_flood", "anti_links",
            "anti_foreign", "anti_profanity", "delete_service",
            "block_media", "block_stickers", "block_spoilers",
            "action_on_violation", "silent_mode"
        }
        if key not in allowed_keys:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE chat_settings SET {key} = ? WHERE chat_id = ?", (value, chat_id))
            await db.commit()

    async def get_managed_chats(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM chat_settings WHERE chat_id < 0 ORDER BY created_at DESC"
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ---------------- Custom Words ---------------- #

    async def add_custom_word(self, chat_id: int, word: str, word_type: str = "blacklist"):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO custom_words (chat_id, word, word_type)
                VALUES (?, ?, ?)
            """, (chat_id, word.lower().strip(), word_type))
            await db.commit()

    async def remove_custom_word(self, chat_id: int, word: str, word_type: str = "blacklist"):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                DELETE FROM custom_words WHERE chat_id = ? AND word = ? AND word_type = ?
            """, (chat_id, word.lower().strip(), word_type))
            await db.commit()

    async def get_custom_words(self, chat_id: int, word_type: str = "blacklist") -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT word FROM custom_words WHERE chat_id = ? AND word_type = ?
            """, (chat_id, word_type))
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    # ---------------- Whitelisted Domains ---------------- #

    async def add_whitelisted_domain(self, chat_id: int, domain: str):
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").strip("/")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR IGNORE INTO whitelisted_domains (chat_id, domain)
                VALUES (?, ?)
            """, (chat_id, clean_domain))
            await db.commit()

    async def remove_whitelisted_domain(self, chat_id: int, domain: str):
        clean_domain = domain.lower().replace("https://", "").replace("http://", "").strip("/")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                DELETE FROM whitelisted_domains WHERE chat_id = ? AND domain = ?
            """, (chat_id, clean_domain))
            await db.commit()

    async def get_whitelisted_domains(self, chat_id: int) -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT domain FROM whitelisted_domains WHERE chat_id = ?
            """, (chat_id,))
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

    # ---------------- Warnings System ---------------- #

    async def add_warning(self, chat_id: int, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT warning_count FROM user_warnings WHERE chat_id = ? AND user_id = ?
            """, (chat_id, user_id))
            row = await cursor.fetchone()
            count = (row[0] + 1) if row else 1

            await db.execute("""
                INSERT INTO user_warnings (chat_id, user_id, warning_count, last_warning_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    warning_count = ?,
                    last_warning_at = CURRENT_TIMESTAMP
            """, (chat_id, user_id, count, count))
            await db.commit()
            return count

    async def reset_warnings(self, chat_id: int, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                DELETE FROM user_warnings WHERE chat_id = ? AND user_id = ?
            """, (chat_id, user_id))
            await db.commit()

    # ---------------- Moderation Logs & Stats ---------------- #

    async def log_action(self, chat_id: int, user_id: int, username: str, reason: str, text: str, action: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO moderation_logs (chat_id, user_id, username, reason, message_text, action_taken)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (chat_id, user_id, username, reason, text[:500], action))
            await db.commit()

    async def get_chat_stats(self, chat_id: int) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM moderation_logs WHERE chat_id = ?", (chat_id,))
            total = (await cursor.fetchone())[0]

            cursor = await db.execute("""
                SELECT reason, COUNT(*) as cnt FROM moderation_logs
                WHERE chat_id = ? GROUP BY reason ORDER BY cnt DESC LIMIT 5
            """, (chat_id,))
            top_reasons = await cursor.fetchall()

            return {
                "total_actions": total,
                "top_reasons": top_reasons
            }

    # ---------------- Bot Admins (Multi-user Management) ---------------- #

    async def is_bot_admin(self, user_id: int, default_admin_ids: List[int]) -> bool:
        if user_id in default_admin_ids:
            return True
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT user_id FROM bot_admins WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return bool(row)

    async def add_bot_admin(self, user_id: int, username: str = "", full_name: str = "", role: str = "admin", added_by: int = 0) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO bot_admins (user_id, username, full_name, role, added_by)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    role = excluded.role
            """, (user_id, username, full_name, role, added_by))
            await db.commit()
            return True

    async def remove_bot_admin(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM bot_admins WHERE user_id = ?", (user_id,))
            await db.commit()
            return True

    async def get_all_bot_admins(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM bot_admins ORDER BY created_at ASC")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ---------------- Telegram Business Connections ---------------- #

    async def save_business_connection(self, connection_id: str, user_id: int, user_chat_id: int, can_reply: bool, is_enabled: bool = True):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO business_connections (connection_id, user_id, user_chat_id, can_reply, is_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(connection_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    user_chat_id = excluded.user_chat_id,
                    can_reply = excluded.can_reply,
                    is_enabled = excluded.is_enabled,
                    updated_at = CURRENT_TIMESTAMP
            """, (connection_id, user_id, user_chat_id, 1 if can_reply else 0, 1 if is_enabled else 0))
            await db.commit()

    async def get_business_connection(self, connection_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM business_connections WHERE connection_id = ?", (connection_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_user_business_connections(self, user_id: int) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM business_connections WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
