import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatPermissions

from ..database import Database
from ..config import BotSettings
from ..filters.moderator import MessageModerator

logger = logging.getLogger(__name__)
router = Router(name="group_moderation_router")
moderator = MessageModerator()


async def is_sender_admin(message: Message, bot: Bot, settings: BotSettings) -> bool:
    """Checks if sender is admin, channel owner, or anonymous admin."""
    # 1. Message sent on behalf of the channel itself (e.g. automatic post or admin commenting as channel)
    if message.sender_chat and message.sender_chat.id == message.chat.id:
        return True

    # 2. Check if user is in global admin list
    if message.from_user and message.from_user.id in settings.ADMIN_IDS:
        return True

    # 3. Check group administrator status
    if message.from_user and message.chat.type in ["group", "supergroup"]:
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status in ["creator", "administrator"]:
                return True
        except Exception as e:
            logger.debug(f"Could not fetch chat member: {e}")
            
    return False


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_group_message(message: Message, bot: Bot, db: Database, settings: BotSettings):
    chat_id = message.chat.id
    user = message.from_user
    user_id = user.id if user else 0
    username = f"@{user.username}" if user and user.username else (user.full_name if user else "Аноним")

    # Admins are exempt from moderation
    if await is_sender_admin(message, bot, settings):
        return

    # Load chat configuration & custom lists
    chat_cfg = await db.get_chat_settings(chat_id, title=message.chat.title or "")
    blacklist = await db.get_custom_words(chat_id, "blacklist")
    whitelist = await db.get_custom_words(chat_id, "whitelist")
    whitelisted_domains = await db.get_whitelisted_domains(chat_id)

    # Moderate message
    result = moderator.check_message(
        message=message,
        chat_settings=chat_cfg,
        custom_blacklist=blacklist,
        custom_whitelist=whitelist,
        whitelisted_domains=whitelisted_domains
    )

    if not result.is_violation:
        return

    # Violation detected!
    action_type = chat_cfg.get("action_on_violation", "delete")
    extracted_text = moderator.extract_all_text(message)

    # 1. Delete the offensive message
    try:
        await message.delete()
        logger.info(f"Deleted message in chat {chat_id} from {username} ({user_id}). Reason: {result.reason}")
    except Exception as e:
        logger.warning(f"Failed to delete message in {chat_id}: {e}")

    # 2. Record to database
    await db.record_violation(
        chat_id=chat_id,
        user_id=user_id,
        username=username,
        reason=result.reason,
        text=extracted_text,
        action=action_type
    )

    # 3. Apply punishment (if user is real and not a service message)
    if user_id and result.category != "service":
        await apply_action(
            bot=bot,
            message=message,
            action_type=action_type,
            user_id=user_id,
            username=username,
            reason=result.reason,
            db=db,
            settings=settings,
            silent=bool(chat_cfg.get("silent_mode", 1))
        )

    # 4. Forward log report to admin/log channel if configured
    if settings.LOG_CHAT_ID:
        try:
            log_text = (
                f"🚨 <b>Обнаружен спам / нарушение!</b>\n"
                f"📍 Чат / Комментарии: <b>{message.chat.title}</b> (<code>{chat_id}</code>)\n"
                f"👤 Автор: <b>{username}</b> (ID: <code>{user_id}</code>)\n"
                f"⚠️ Причина: <b>{result.reason}</b>\n"
                f"🔍 Совпадение: <code>{result.matched_detail[:80]}</code>\n"
                f"⚔️ Действие: <code>{action_type}</code>\n"
                f"💬 Текст сообщения:\n<blockquote>{extracted_text[:350]}</blockquote>"
            )
            await bot.send_message(settings.LOG_CHAT_ID, log_text, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"Failed to send log to LOG_CHAT_ID: {e}")


async def apply_action(
    bot: Bot,
    message: Message,
    action_type: str,
    user_id: int,
    username: str,
    reason: str,
    db: Database,
    settings: BotSettings,
    silent: bool
):
    chat_id = message.chat.id
    notice_text = None

    try:
        if action_type == "ban":
            await bot.ban_chat_member(chat_id, user_id)
            notice_text = f"🚫 Пользователь {username} заблокирован за нарушение правил ({reason})."

        elif action_type == "mute_1h":
            until = datetime.now() + timedelta(hours=1)
            await bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            notice_text = f"🔇 Пользователь {username} замучен на 1 час за нарушение ({reason})."

        elif action_type == "mute_24h":
            until = datetime.now() + timedelta(hours=24)
            await bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            notice_text = f"🔇 Пользователь {username} замучен на 24 часа за нарушение ({reason})."

        elif action_type == "warn":
            warn_count = await db.get_user_warnings(chat_id, user_id)
            if warn_count >= settings.MAX_WARNINGS:
                until = datetime.now() + timedelta(hours=24)
                await bot.restrict_chat_member(
                    chat_id,
                    user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                await db.reset_user_warnings(chat_id, user_id)
                notice_text = f"🔇 Пользователь {username} получил {warn_count} предупреждений и замучен на 24 часа."
            else:
                notice_text = f"⚠️ Предупреждение для {username} ({warn_count}/{settings.MAX_WARNINGS}): {reason}."

    except Exception as e:
        logger.warning(f"Failed to execute action {action_type} on user {user_id}: {e}")

    # If silent mode is OFF, post notification and auto-delete it after 7 seconds to keep comments clean
    if not silent and notice_text:
        try:
            sent_msg = await bot.send_message(chat_id, notice_text)
            await asyncio.sleep(7)
            await sent_msg.delete()
        except Exception:
            pass
