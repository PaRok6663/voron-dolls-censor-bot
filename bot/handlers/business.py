import io
import logging
from aiogram import Router, F, Bot
from aiogram.types import BusinessConnection, Message

from ..database import Database
from ..config import BotSettings
from ..filters.moderator import MessageModerator
from ..filters.nsfw_analyzer import NSFWAnalyzer

logger = logging.getLogger(__name__)
router = Router(name="business_router")
moderator = MessageModerator()
nsfw_analyzer = NSFWAnalyzer()


# ---------------- Business Connection Updates ---------------- #

@router.business_connection()
async def handle_business_connection(event: BusinessConnection, bot: Bot, db: Database, settings: BotSettings):
    user_id = event.user.id
    username = f"@{event.user.username}" if event.user.username else event.user.full_name
    conn_id = event.id
    is_enabled = event.is_enabled
    can_reply = event.can_reply

    logger.info(
        f"Business connection update: user={username} ({user_id}), conn_id={conn_id}, "
        f"enabled={is_enabled}, can_reply={can_reply}"
    )

    await db.save_business_connection(
        connection_id=conn_id,
        user_id=user_id,
        user_chat_id=event.user_chat_id,
        can_reply=can_reply,
        is_enabled=is_enabled
    )

    # Ensure this business user has default moderation settings for their account
    await db.get_chat_settings(user_id, title=f"ЛС {username}")

    # Notify the user in their private chat with the bot
    if is_enabled:
        text = (
            f"🤝 <b>Telegram Business успешно подключен!</b>\n\n"
            f"Бот теперь защищает ваши личные входящие сообщения от спама, порнографии и рекламы.\n"
            f"🆔 ID подключения: <code>{conn_id}</code>\n"
            f"Права на отправку сообщений: {'✅ Есть' if can_reply else '❌ Нет'}\n\n"
            f"Вы можете настроить параметры фильтрации ваших личных сообщений командой <code>/settings</code> в этом чате."
        )
    else:
        text = f"🔌 Подключение Telegram Business (ID: <code>{conn_id}</code>) было отключено."

    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"Could not notify business user {user_id}: {e}")


# ---------------- Business Messages Moderation ---------------- #

@router.business_message()
@router.edited_business_message()
async def handle_business_message(message: Message, bot: Bot, db: Database, settings: BotSettings):
    conn_id = message.business_connection_id
    if not conn_id:
        return

    chat_id = message.chat.id
    from_user = message.from_user
    user_id = from_user.id if from_user else 0
    username = f"@{from_user.username}" if from_user and from_user.username else (from_user.full_name if from_user else "Аноним")

    # Get connection owner
    conn = await db.get_business_connection(conn_id)
    owner_id = conn["user_id"] if conn else None

    # If the message is sent by the account owner themselves, do not moderate it
    if owner_id and user_id == owner_id:
        return

    # Check if sender is in bot admin list (also skip)
    if await db.is_bot_admin(user_id, settings.ADMIN_IDS):
        return

    extracted_text = moderator.extract_all_text(message)
    logger.info(
        f"Incoming business message [{message.message_id}] in chat {chat_id} "
        f"via connection {conn_id} from {username} ({user_id}): {extracted_text[:60]}"
    )

    # Use the account owner's custom settings for their business chat
    settings_target_id = owner_id if owner_id else chat_id
    chat_cfg = await db.get_chat_settings(settings_target_id, title=f"Бизнес-чат {owner_id}")
    blacklist = await db.get_custom_words(settings_target_id, "blacklist")
    whitelist = await db.get_custom_words(settings_target_id, "whitelist")
    whitelisted_domains = await db.get_whitelisted_domains(settings_target_id)

    # Run core text / link / keyword moderation
    result = moderator.check_message(
        message=message,
        chat_settings=chat_cfg,
        custom_blacklist=blacklist,
        custom_whitelist=whitelist,
        whitelisted_domains=whitelisted_domains
    )

    # Visual NSFW AI inspection on media (photos, video thumbnails, GIF animations)
    if not result.is_violation and chat_cfg.get("anti_porn", 1):
        file_id = None
        if getattr(message, "photo", None):
            file_id = message.photo[0].file_id
        elif getattr(message, "video", None) and getattr(message.video, "thumbnail", None):
            file_id = message.video.thumbnail.file_id
        elif getattr(message, "animation", None) and getattr(message.animation, "thumbnail", None):
            file_id = message.animation.thumbnail.file_id
        elif getattr(message, "video_note", None) and getattr(message.video_note, "thumbnail", None):
            file_id = message.video_note.thumbnail.file_id

        if file_id:
            try:
                file_info = await bot.get_file(file_id)
                file_io = io.BytesIO()
                await bot.download_file(file_info.file_path, file_io)
                nsfw_score = nsfw_analyzer.predict(file_io)
                logger.info(f"Visual NSFW check in business chat {chat_id}: score={nsfw_score:.2f}")
                if nsfw_score >= 0.70:
                    result = ModerationResult(
                        is_violation=True,
                        category="porn",
                        reason=f"18+ / Обнаружена нагота или порнография в медиа (AI score: {nsfw_score:.0%})",
                        matched_detail=f"AI NSFW: {nsfw_score:.2f}"
                    )
            except Exception as e:
                logger.warning(f"Error checking visual media for NSFW in business chat: {e}")

    if not result.is_violation:
        return

    # Violation detected: Delete the business message
    logger.info(
        f"VIOLATION in business message from {username} ({user_id}) "
        f"via conn {conn_id}: reason='{result.reason}', detail='{result.matched_detail}'"
    )

    deleted = False
    try:
        # Use Telegram Bot API delete_business_messages
        if hasattr(bot, "delete_business_messages"):
            await bot.delete_business_messages(business_connection_id=conn_id, message_ids=[message.message_id])
            deleted = True
        else:
            await bot.delete_message(chat_id=chat_id, message_id=message.message_id)
            deleted = True
    except Exception as e:
        logger.warning(f"Failed to delete business message {message.message_id}: {e}")

    # Log action to database
    await db.log_action(
        chat_id=settings_target_id,
        user_id=user_id,
        username=username,
        reason=f"Business: {result.reason} ({result.matched_detail})",
        text=extracted_text,
        action="delete" if deleted else "failed_delete"
    )

    # Notify account owner
    if owner_id:
        try:
            owner_text = (
                f"🛡️ <b>Удалено нежелательное сообщение в ваших ЛС (Telegram Business)!</b>\n\n"
                f"👤 <b>Отправитель:</b> {username} (<code>{user_id}</code>)\n"
                f"🚫 <b>Причина:</b> {result.reason}\n"
                f"🔍 <b>Деталь:</b> <code>{result.matched_detail}</code>\n"
                f"📝 <b>Текст сообщения:</b>\n<i>{extracted_text[:200]}</i>"
            )
            await bot.send_message(owner_id, owner_text, parse_mode="HTML")
        except Exception as e:
            logger.debug(f"Could not notify business owner {owner_id}: {e}")
