import io
import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Router, F, Bot
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command

from ..database import Database
from ..config import BotSettings
from ..filters.moderator import MessageModerator
from ..filters.nsfw_analyzer import NSFWAnalyzer

logger = logging.getLogger(__name__)
router = Router(name="group_moderation_router")
moderator = MessageModerator()
nsfw_analyzer = NSFWAnalyzer()


async def is_sender_admin(message: Message, bot: Bot, settings: BotSettings) -> bool:
    """Checks if sender is admin, channel owner, or anonymous admin."""
    # 0. Automatic forward from the linked channel itself (the channel post appearing in comments)
    if getattr(message, "is_automatic_forward", False):
        return True

    # 1. Message sent on behalf of the channel itself
    if message.sender_chat and message.chat and message.sender_chat.id == message.chat.id:
        return True

    # 2. Check if user is in global admin list
    if message.from_user and message.from_user.id in settings.ADMIN_IDS:
        return True

    # 3. If sender is posting on behalf of an EXTERNAL channel:
    # Non-admins often post spam in comments from their own channels.
    # Such messages MUST be moderated!
    if message.sender_chat and message.chat and message.sender_chat.id != message.chat.id:
        # Check if sender_chat is the linked channel of this group
        try:
            chat_info = await bot.get_chat(message.chat.id)
            if chat_info.linked_chat_id and message.sender_chat.id == chat_info.linked_chat_id:
                return True
        except Exception:
            pass
        return False

    # 4. If from_user is GroupAnonymousBot (1087968824) or Telegram (777000)
    if message.from_user and message.from_user.id in [1087968824, 777000]:
        return False

    # 5. Check group administrator status for standard user
    if message.from_user and message.chat.type in ["group", "supergroup"]:
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if member.status in ["creator", "administrator"]:
                return True
        except Exception as e:
            logger.debug(f"Could not fetch chat member: {e}")
            
    return False


@router.message(Command("test", "check"))
async def cmd_test_text(message: Message, bot: Bot, db: Database, settings: BotSettings):
    target_msg = message.reply_to_message or message
    test_text = ""
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        test_text = parts[1]
    elif message.reply_to_message:
        test_text = moderator.extract_all_text(message.reply_to_message)

    chat_cfg = await db.get_chat_settings(message.chat.id)
    blacklist = await db.get_custom_words(message.chat.id, "blacklist")
    whitelist = await db.get_custom_words(message.chat.id, "whitelist")
    whitelisted_domains = await db.get_whitelisted_domains(message.chat.id)

    # 1. Text & metadata moderation
    res = moderator.check_message(
        message=target_msg,
        chat_settings=chat_cfg,
        custom_blacklist=blacklist,
        custom_whitelist=whitelist,
        whitelisted_domains=whitelisted_domains
    )

    # 2. Visual AI check if media present
    visual_score = None
    file_id = None
    if target_msg.photo:
        file_id = target_msg.photo[0].file_id
    elif target_msg.video and getattr(target_msg.video, "thumbnail", None):
        file_id = target_msg.video.thumbnail.file_id
    elif target_msg.animation and getattr(target_msg.animation, "thumbnail", None):
        file_id = target_msg.animation.thumbnail.file_id

    if file_id:
        try:
            file_info = await bot.get_file(file_id)
            file_io = io.BytesIO()
            await bot.download_file(file_info.file_path, file_io)
            visual_score = nsfw_analyzer.predict(file_io)
            if visual_score >= 0.70 and not res.is_violation:
                res = ModerationResult(
                    is_violation=True,
                    category="porn",
                    reason=f"18+ / Обнаружена нагота или порнография в медиа (AI score: {visual_score:.0%})",
                    matched_detail=f"AI NSFW: {visual_score:.2f}"
                )
        except Exception as e:
            logger.warning(f"Error testing visual media: {e}")

    lines = ["🔍 <b>Результат проверки:</b>\n"]
    if test_text:
        lines.append(f"💬 Текст: <code>{test_text[:120]}</code>")
    if visual_score is not None:
        lines.append(f"🖼 Визуальный AI NSFW score: <b>{visual_score:.1%}</b> (порог: 70%)")

    if res.is_violation:
        lines.extend([
            f"\n❌ <b>НАРУШЕНИЕ ОБНАРУЖЕНО!</b>",
            f"• <b>Причина:</b> {res.reason}",
            f"• <b>Категория:</b> {res.category}",
            f"• <b>Совпадение:</b> <code>{res.matched_detail[:80]}</code>",
            f"• <b>Действие:</b> <code>{chat_cfg.get('action_on_violation', 'delete').upper()}</code>"
        ])
    else:
        lines.extend([
            f"\n✅ <b>Чисто (нарушений не найдено).</b>",
            f"Сообщение полностью проходит фильтры этого чата."
        ])
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(F.chat.type.in_({"group", "supergroup"}))
@router.edited_message(F.chat.type.in_({"group", "supergroup"}))
@router.channel_post()
@router.edited_channel_post()
async def handle_group_message(message: Message, bot: Bot, db: Database, settings: BotSettings):
    chat_id = message.chat.id
    user = message.from_user
    user_id = user.id if user else (message.sender_chat.id if message.sender_chat else 0)
    username = f"@{user.username}" if user and user.username else (user.full_name if user else (message.sender_chat.title if message.sender_chat else "Аноним"))
    extracted_text = moderator.extract_all_text(message)

    logger.info(f"Incoming message [{message.message_id}] in chat {chat_id} ({message.chat.title}) from {username} ({user_id}): {extracted_text[:60]}")

    # Admins and channel posts are exempt from moderation
    if await is_sender_admin(message, bot, settings):
        logger.info(f"Skipping admin/channel sender {username} ({user_id}) in {chat_id}")
        return

    # Load chat configuration & custom lists
    chat_cfg = await db.get_chat_settings(chat_id, title=message.chat.title or "")
    blacklist = await db.get_custom_words(chat_id, "blacklist")
    whitelist = await db.get_custom_words(chat_id, "whitelist")
    whitelisted_domains = await db.get_whitelisted_domains(chat_id)

    # Moderate message (text, links, patterns, metadata)
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
        if message.photo:
            file_id = message.photo[0].file_id
        elif message.video and getattr(message.video, "thumbnail", None):
            file_id = message.video.thumbnail.file_id
        elif message.animation and getattr(message.animation, "thumbnail", None):
            file_id = message.animation.thumbnail.file_id
        elif message.video_note and getattr(message.video_note, "thumbnail", None):
            file_id = message.video_note.thumbnail.file_id

        if file_id:
            try:
                file_info = await bot.get_file(file_id)
                file_io = io.BytesIO()
                await bot.download_file(file_info.file_path, file_io)
                nsfw_score = nsfw_analyzer.predict(file_io)
                logger.info(f"Visual AI NSFW check in {chat_id} from {username}: score={nsfw_score:.2f}")
                if nsfw_score >= 0.70:
                    result = ModerationResult(
                        is_violation=True,
                        category="porn",
                        reason=f"18+ / Обнаружена нагота или порнография в медиа (AI score: {nsfw_score:.0%})",
                        matched_detail=f"AI NSFW score: {nsfw_score:.2f}"
                    )
            except Exception as e:
                logger.warning(f"Error checking visual media for NSFW: {e}")

    if not result.is_violation:
        return

    # Violation detected!
    action_type = chat_cfg.get("action_on_violation", "delete")
    logger.info(f"🚨 VIOLATION in {chat_id} from {username}: {result.reason} (matched: {result.matched_detail}) -> Action: {action_type}")

    # 1. Delete the offensive message
    try:
        await message.delete()
        logger.info(f"Deleted message {message.message_id} in {chat_id} from {username} ({user_id})")
    except Exception as e:
        logger.warning(f"Failed to delete message {message.message_id} in {chat_id}: {e}")

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
