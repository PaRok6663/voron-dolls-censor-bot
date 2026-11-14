import logging
from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from ..database import Database
from ..config import BotSettings
from ..filters.moderator import MessageModerator

logger = logging.getLogger(__name__)
router = Router(name="private_dialog_router")
moderator = MessageModerator()


class ReplyState(StatesGroup):
    waiting_for_reply = State()


@router.message(F.chat.type == "private", Command("start"))
async def cmd_start_private(message: Message, settings: BotSettings):
    user_id = message.from_user.id
    if user_id in settings.ADMIN_IDS:
        text = (
            "👋 <b>Здравствуйте, администратор!</b>\n\n"
            "Этот бот защищает комментарии и личные сообщения канала от спама, порно и рекламы.\n\n"
            "<b>Основные возможности:</b>\n"
            "• Автоматическая модерация комментариев под постами\n"
            "• Фильтрация спама, 18+, ссылок, рекламы и нецензурной лексики\n"
            "• Прием входящих сообщений от клиентов с проверкой на спам\n\n"
            "Используйте <code>/settings</code> для открытия панели управления."
        )
    else:
        text = (
            "👋 <b>Здравствуйте!</b>\n\n"
            "Вы можете написать сюда ваш вопрос, отзыв или пожелание по поводу кукол и заказов.\n"
            "Ваше сообщение будет проверено и передано автору канала."
        )
    await message.reply(text, parse_mode="HTML")


@router.message(F.chat.type == "private", Command("reply"))
async def cmd_reply(message: Message, bot: Bot, settings: BotSettings):
    if message.from_user.id not in settings.ADMIN_IDS:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply("Использование: <code>/reply [user_id] [текст ответа]</code>", parse_mode="HTML")

    try:
        target_id = int(parts[1])
        reply_text = parts[2]
        await bot.send_message(
            target_id,
            f"📩 <b>Ответ от автора канала:</b>\n\n{reply_text}",
            parse_mode="HTML"
        )
        await message.reply("✅ Ответ успешно отправлен пользователю.")
    except Exception as e:
        await message.reply(f"❌ Не удалось отправить ответ: {e}")


@router.callback_query(F.data.startswith("reply_to_"))
async def callback_start_reply(query: CallbackQuery, state: FSMContext, settings: BotSettings):
    if query.from_user.id not in settings.ADMIN_IDS:
        return await query.answer("Только для администраторов", show_alert=True)

    target_user_id = int(query.data.replace("reply_to_", ""))
    await state.set_state(ReplyState.waiting_for_reply)
    await state.update_data(target_user_id=target_user_id)

    await query.message.reply(
        f"✍️ Напишите ответ для пользователя <code>{target_user_id}</code> следующим сообщением (или отправьте /cancel для отмены):",
        parse_mode="HTML"
    )
    await query.answer()


@router.message(ReplyState.waiting_for_reply, Command("cancel"))
async def cmd_cancel_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.reply("Действие отменено.")


@router.message(ReplyState.waiting_for_reply)
async def process_admin_reply(message: Message, bot: Bot, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get("target_user_id")

    if not target_user_id:
        await state.clear()
        return

    try:
        await bot.send_message(
            target_user_id,
            f"📩 <b>Ответ от автора канала:</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.reply(f"✅ Сообщение доставлено пользователю <code>{target_user_id}</code>.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка отправки: {e}")
    finally:
        await state.clear()


@router.message(F.chat.type == "private")
async def handle_private_message(message: Message, bot: Bot, db: Database, settings: BotSettings):
    user = message.from_user
    user_id = user.id if user else 0
    username = f"@{user.username}" if user and user.username else (user.full_name if user else "Аноним")

    # If message is from admin, ignore moderation
    if user_id in settings.ADMIN_IDS:
        return

    # Check incoming message for spam / porn / bad words
    chat_cfg = await db.get_chat_settings(user_id, title=username)
    blacklist = await db.get_custom_words(user_id, "blacklist")
    whitelist = await db.get_custom_words(user_id, "whitelist")
    whitelisted_domains = await db.get_whitelisted_domains(user_id)

    result = moderator.check_message(
        message=message,
        chat_settings=chat_cfg,
        custom_blacklist=blacklist,
        custom_whitelist=whitelist,
        whitelisted_domains=whitelisted_domains
    )

    extracted_text = moderator.extract_all_text(message)

    if result.is_violation:
        # Spam / porn detected in PM! Block / reject message
        logger.info(f"Blocked private spam from {username} ({user_id}): {result.reason}")
        await message.reply(
            "⚠️ Ваше сообщение было отклонено системой безопасности (обнаружен спам, 18+ контент или запрещенные ссылки)."
        )

        # Notify admin of blocked attempt
        if settings.LOG_CHAT_ID:
            try:
                alert_text = (
                    f"🛡 <b>Заблокировано входящее сообщение в ЛС!</b>\n"
                    f"👤 От: <b>{username}</b> (ID: <code>{user_id}</code>)\n"
                    f"⚠️ Причина: <b>{result.reason}</b>\n"
                    f"💬 Текст:\n<blockquote>{extracted_text[:350]}</blockquote>"
                )
                await bot.send_message(settings.LOG_CHAT_ID, alert_text, parse_mode="HTML")
            except Exception:
                pass
        return

    # If it's a clean, valid client message:
    await message.reply("✅ Спасибо! Ваше сообщение отправлено автору канала. Мы ответим вам в ближайшее время.")

    # Forward or send to admin / managers
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить клиенту", callback_data=f"reply_to_{user_id}")]
    ])

    admin_notify_text = (
        f"📬 <b>Новое входящее обращение к каналу!</b>\n"
        f"👤 От: <b>{username}</b> (ID: <code>{user_id}</code>)\n\n"
        f"💬 <b>Текст:</b>\n{extracted_text}"
    )

    # Send to LOG_CHAT_ID or first admin
    destinations = []
    if settings.LOG_CHAT_ID:
        destinations.append(settings.LOG_CHAT_ID)
    elif settings.ADMIN_IDS:
        destinations.extend(settings.ADMIN_IDS)

    for dest in destinations:
        try:
            await bot.send_message(dest, admin_notify_text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Could not forward message to admin {dest}: {e}")
