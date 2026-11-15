import logging
from typing import Optional, List
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
    ChatMemberUpdated
)

from ..database import Database
from ..config import BotSettings

logger = logging.getLogger(__name__)
router = Router(name="admin_router")


async def is_admin(message_or_query: Message | CallbackQuery, settings: BotSettings) -> bool:
    user_id = message_or_query.from_user.id
    if user_id in settings.ADMIN_IDS:
        return True

    # If in a group / supergroup, check chat administrator rights
    chat = message_or_query.message.chat if isinstance(message_or_query, CallbackQuery) else message_or_query.chat
    if chat.type in ["group", "supergroup", "channel"]:
        try:
            bot = message_or_query.bot
            member = await bot.get_chat_member(chat.id, user_id)
            return member.status in ["creator", "administrator"]
        except Exception as e:
            logger.warning(f"Error checking admin status: {e}")
            return False
    return False


def build_chats_list_keyboard(chats: List[dict]) -> InlineKeyboardMarkup:
    """Builds interactive list of all connected groups/channels for the admin."""
    buttons = []
    for c in chats:
        title = c.get("title") or f"Чат {c['chat_id']}"
        cid = c["chat_id"]
        buttons.append([
            InlineKeyboardButton(text=f"💬 {title}", callback_data=f"manage_chat:{cid}")
        ])

    buttons.append([
        InlineKeyboardButton(text="📖 Как подключить новый чат/канал?", callback_data="guide_connect")
    ])
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить список чатов", callback_data="refresh_chats")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_settings_keyboard(chat_settings: dict, chat_id: int, is_private: bool = False) -> InlineKeyboardMarkup:
    def mark(val: int) -> str:
        return "ВКЛ ✅" if val else "ВЫКЛ ❌"

    buttons = [
        [
            InlineKeyboardButton(
                text=f"🔞 Порно: {mark(chat_settings.get('anti_porn', 1))}",
                callback_data=f"toggle_anti_porn:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🚫 Спам: {mark(chat_settings.get('anti_spam', 1))}",
                callback_data=f"toggle_anti_spam:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⚡ Флуд: {mark(chat_settings.get('anti_flood', 1))}",
                callback_data=f"toggle_anti_flood:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🔗 Ссылки: {mark(chat_settings.get('anti_links', 1))}",
                callback_data=f"toggle_anti_links:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🌐 Арабский/Спам-шрифт: {mark(chat_settings.get('anti_foreign', 1))}",
                callback_data=f"toggle_anti_foreign:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"🤬 Мат: {mark(chat_settings.get('anti_profanity', 1))}",
                callback_data=f"toggle_anti_profanity:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🧹 Служебные смс: {mark(chat_settings.get('delete_service', 1))}",
                callback_data=f"toggle_delete_service:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"📷 Запрет медиа: {mark(chat_settings.get('block_media', 0))}",
                callback_data=f"toggle_block_media:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🤫 Тихий режим: {mark(chat_settings.get('silent_mode', 1))}",
                callback_data=f"toggle_silent_mode:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"⚔ Наказание: {chat_settings.get('action_on_violation', 'delete').upper()}",
                callback_data=f"cycle_action:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data=f"show_stats:{chat_id}"),
            InlineKeyboardButton(text="📝 Стоп-слова", callback_data=f"show_words:{chat_id}")
        ]
    ]

    if is_private:
        buttons.append([
            InlineKeyboardButton(text="◀️ Назад ко всем чатам", callback_data="back_to_chats")
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_settings:{chat_id}")
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------------- Bot Added to Chat / Channel Event ---------------- #

@router.my_chat_member()
async def on_bot_added_to_chat(event: ChatMemberUpdated, bot: Bot, db: Database, settings: BotSettings):
    if event.new_chat_member.status not in ["administrator", "member"]:
        return

    chat = event.chat
    title = chat.title or "Без названия"
    chat_id = chat.id

    # Register chat in DB
    await db.get_chat_settings(chat_id, title=title)
    logger.info(f"Bot joined new chat/channel: {title} ({chat_id})")

    # Send welcome / instructions to the group
    if chat.type in ["group", "supergroup"]:
        try:
            await bot.send_message(
                chat_id,
                f"🛡️ <b>Бот-цензор успешно подключен к чату «{title}»!</b>\n\n"
                f"• По умолчанию включена защита от порно, спама, рекламы, левых ссылок и спам-ботов.\n"
                f"• Чтобы настроить фильтры, отправьте команду <code>/settings</code> (доступно администраторам).\n"
                f"• Также вы можете управлять всеми настройками прямо в личных сообщениях с ботом.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"Could not send welcome message to chat {chat_id}: {e}")

    # Notify administrators in PM
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚙️ Настроить «{title}»", callback_data=f"manage_chat:{chat_id}")]
    ])
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🎉 <b>Бот добавлен в новый чат / канал!</b>\n"
                f"📍 Название: <b>{title}</b>\n"
                f"🆔 ID: <code>{chat_id}</code>\n"
                f"Тип: <code>{chat.type}</code>\n\n"
                f"Нажмите кнопку ниже, чтобы настроить параметры фильтрации для этого чата:",
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"Could not notify admin {admin_id}: {e}")


# ---------------- /settings and /chats Command ---------------- #

@router.message(Command("settings", "panel", "chats"))
async def cmd_settings(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Эта команда доступна только администраторам канала/чата.")

    is_private = (message.chat.type == "private")

    if is_private:
        # In Private Messages: show list of all managed channels/chats
        chats = await db.get_managed_chats()
        if not chats:
            text = (
                "⚙️ <b>Панель управления цензурой и антиспамом</b>\n\n"
                "Бот пока не добавлен ни в одну группу комментариев или канал.\n\n"
                "Нажмите кнопку ниже, чтобы посмотреть простую инструкцию по подключению 👇"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📖 Как подключить канал/чат?", callback_data="guide_connect")]
            ])
            return await message.reply(text, reply_markup=kb, parse_mode="HTML")

        text = (
            "⚙️ <b>Центр управления каналами и чатами</b>\n\n"
            "Выберите чат или канал, настройки которого хотите изменить:\n"
            "<i>(Каждый чат настраивается индивидуально)</i>"
        )
        kb = build_chats_list_keyboard(chats)
        return await message.reply(text, reply_markup=kb, parse_mode="HTML")

    # In a Group / Supergroup / Channel
    chat_id = message.chat.id
    chat_title = message.chat.title or "Этот чат"
    cfg = await db.get_chat_settings(chat_id, title=chat_title)

    text = (
        f"⚙️ <b>Панель управления цензурой и антиспамом</b>\n"
        f"💬 Чат: <b>{chat_title}</b> (<code>{chat_id}</code>)\n\n"
        f"Нажмите на кнопку, чтобы включить/выключить нужный фильтр:"
    )
    kb = build_settings_keyboard(cfg, chat_id=chat_id, is_private=False)
    await message.reply(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "back_to_chats")
async def cb_back_to_chats(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chats = await db.get_managed_chats()
    kb = build_chats_list_keyboard(chats)
    text = (
        "⚙️ <b>Центр управления каналами и чатами</b>\n\n"
        "Выберите чат или канал для настройки:"
    )
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await query.answer()


@router.callback_query(F.data == "refresh_chats")
async def cb_refresh_chats(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chats = await db.get_managed_chats()
    kb = build_chats_list_keyboard(chats)
    try:
        await query.message.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        pass
    await query.answer("Список чатов обновлен")


@router.callback_query(F.data.startswith("manage_chat:"))
async def cb_manage_chat(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = int(query.data.split(":")[1])
    cfg = await db.get_chat_settings(chat_id)
    title = cfg.get("title") or f"Чат {chat_id}"

    text = (
        f"⚙️ <b>Настройки фильтрации для:</b>\n"
        f"💬 <b>{title}</b> (<code>{chat_id}</code>)\n\n"
        f"Нажмите на кнопку, чтобы изменить параметр:"
    )
    is_private = (query.message.chat.type == "private")
    kb = build_settings_keyboard(cfg, chat_id=chat_id, is_private=is_private)
    await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await query.answer()


@router.callback_query(F.data.startswith("toggle_"))
async def callback_toggle(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    # Format: toggle_anti_porn:chat_id or toggle_anti_porn
    parts = query.data.split(":")
    key = parts[0].replace("toggle_", "")
    chat_id = int(parts[1]) if len(parts) > 1 else query.message.chat.id

    cfg = await db.get_chat_settings(chat_id)
    curr_val = cfg.get(key, 1)
    new_val = 0 if curr_val else 1
    await db.update_chat_setting(chat_id, key, new_val)

    updated_cfg = await db.get_chat_settings(chat_id)
    is_private = (query.message.chat.type == "private")
    try:
        await query.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_cfg, chat_id=chat_id, is_private=is_private)
        )
    except TelegramBadRequest:
        pass
    await query.answer(f"Параметр {key}: {'ВКЛ ✅' if new_val else 'ВЫКЛ ❌'}")


@router.callback_query(F.data.startswith("cycle_action"))
async def callback_cycle_action(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    parts = query.data.split(":")
    chat_id = int(parts[1]) if len(parts) > 1 else query.message.chat.id

    cfg = await db.get_chat_settings(chat_id)
    actions = ["delete", "warn", "mute_1h", "mute_24h", "ban"]
    curr = cfg.get("action_on_violation", "delete")
    try:
        next_idx = (actions.index(curr) + 1) % len(actions)
    except ValueError:
        next_idx = 0

    new_action = actions[next_idx]
    await db.update_chat_setting(chat_id, "action_on_violation", new_action)

    updated_cfg = await db.get_chat_settings(chat_id)
    is_private = (query.message.chat.type == "private")
    try:
        await query.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_cfg, chat_id=chat_id, is_private=is_private)
        )
    except TelegramBadRequest:
        pass
    await query.answer(f"Действие: {new_action.upper()}")


@router.callback_query(F.data.startswith("refresh_settings"))
async def callback_refresh(query: CallbackQuery, db: Database):
    parts = query.data.split(":")
    chat_id = int(parts[1]) if len(parts) > 1 else query.message.chat.id
    cfg = await db.get_chat_settings(chat_id)
    is_private = (query.message.chat.type == "private")
    try:
        await query.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(cfg, chat_id=chat_id, is_private=is_private)
        )
    except TelegramBadRequest:
        pass
    await query.answer("Настройки обновлены")


@router.callback_query(F.data.startswith("show_stats"))
async def callback_stats(query: CallbackQuery, db: Database):
    parts = query.data.split(":")
    chat_id = int(parts[1]) if len(parts) > 1 else query.message.chat.id
    cfg = await db.get_chat_settings(chat_id)
    title = cfg.get("title") or f"Чат {chat_id}"

    stats = await db.get_chat_stats(chat_id)
    lines = [
        f"📊 <b>Статистика фильтрации для «{title}»:</b>",
        f"Всего заблокировано спама: <b>{stats['total_deleted']}</b>"
    ]
    if stats["top_reasons"]:
        lines.append("\n<b>Топ нарушений:</b>")
        for reason, count in stats["top_reasons"]:
            lines.append(f"• {reason}: {count}")

    await query.answer()
    await query.message.reply("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("show_words"))
async def callback_words(query: CallbackQuery, db: Database):
    parts = query.data.split(":")
    chat_id = int(parts[1]) if len(parts) > 1 else query.message.chat.id
    cfg = await db.get_chat_settings(chat_id)
    title = cfg.get("title") or f"Чат {chat_id}"

    bl = await db.get_custom_words(chat_id, "blacklist")
    wl = await db.get_whitelisted_domains(chat_id)
    bl_str = ", ".join(bl) if bl else "<i>(пусто)</i>"
    wl_str = ", ".join(wl) if wl else "<i>(пусто)</i>"

    text = (
        f"📝 <b>Фильтры слов для «{title}»:</b>\n\n"
        f"🚫 <b>Черный список слов:</b>\n{bl_str}\n\n"
        f"Добавить: <code>/addword слово</code>\n"
        f"Удалить: <code>/delword слово</code>\n\n"
        f"✅ <b>Белый список ссылок:</b>\n{wl_str}\n\n"
        f"Добавить: <code>/addwhitelist ссылка</code>\n"
        f"Удалить: <code>/delwhitelist ссылка</code>"
    )
    await query.answer()
    await query.message.reply(text, parse_mode="HTML")


@router.callback_query(F.data == "guide_connect")
async def cb_guide_connect(query: CallbackQuery):
    guide_text = (
        "📖 <b>Пошаговая инструкция: как подключить бота к любому каналу или чату</b>\n\n"
        "<b>Вариант А: Защита комментариев канала (например, Voron Dolls)</b>\n"
        "1. Зайдите в ваш Telegram-канал → <b>Управление каналом</b> → раздел <b>«Обсуждение»</b>.\n"
        "2. Убедитесь, что к каналу привязана группа для комментариев (если нет — создайте или привяжите существующую).\n"
        "3. Откройте эту привязанную группу → нажмите <b>Добавить участников</b> → найдите бота <code>@voron_dolls_censor_bot</code>.\n"
        "4. Назначьте бота <b>Администратором группы</b> со следующими правами:\n"
        "   ✅ <i>Удаление сообщений (Delete Messages)</i>\n"
        "   ✅ <i>Блокировка пользователей (Ban Users)</i>\n"
        "5. <b>Готово!</b> Бот сразу начнет фильтровать комментарии под постами канала и появится в вашем списке <code>/settings</code>.\n\n"
        "➖➖➖➖➖➖➖➖➖➖\n"
        "<b>Вариант Б: Подключение к любой обычной группе / чату</b>\n"
        "• Просто добавьте бота в нужную группу и дайте права Администратора на удаление сообщений.\n\n"
        "💡 <i>Вы можете подключить одного и того же бота к 10, 20 и более разным каналам и группам — каждый настраивается независимо!</i>"
    )
    await query.answer()
    await query.message.reply(guide_text, parse_mode="HTML")


# ---------------- Custom Words Management ---------------- #

@router.message(Command("addword"))
async def cmd_addword(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/addword запрещенное_слово</code>", parse_mode="HTML")

    word = parts[1].strip()
    success = await db.add_custom_word(message.chat.id, word, "blacklist")
    if success:
        await message.reply(f"✅ Слово <b>«{word}»</b> добавлено в черный список этого чата.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Это слово уже есть в черном списке.")


@router.message(Command("delword"))
async def cmd_delword(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/delword слово</code>", parse_mode="HTML")

    word = parts[1].strip()
    success = await db.remove_custom_word(message.chat.id, word, "blacklist")
    if success:
        await message.reply(f"🗑 Слово <b>«{word}»</b> удалено из черного списка.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Слово не найдено в черном списке.")


@router.message(Command("words", "blacklist"))
async def cmd_words(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    words = await db.get_custom_words(message.chat.id, "blacklist")
    if not words:
        return await message.reply("📝 Черный список слов пуст.")
    
    text = "🚫 <b>Черный список слов:</b>\n" + "\n".join(f"• {w}" for w in words)
    await message.reply(text, parse_mode="HTML")


@router.message(Command("addwhitelist"))
async def cmd_addwhitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/addwhitelist домен_или_ник</code>\nПример: <code>/addwhitelist vorondolls</code> или <code>/addwhitelist vk.com</code>", parse_mode="HTML")

    domain = parts[1].strip().lower().replace("https://", "").replace("http://", "").rstrip('/')
    success = await db.add_whitelisted_domain(message.chat.id, domain)
    if success:
        await message.reply(f"✅ Домен/ссылка <b>«{domain}»</b> добавлена в белый список.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Этот домен уже в белом списке.")


@router.message(Command("delwhitelist"))
async def cmd_delwhitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/delwhitelist домен</code>", parse_mode="HTML")

    domain = parts[1].strip().lower()
    success = await db.remove_whitelisted_domain(message.chat.id, domain)
    if success:
        await message.reply(f"🗑 <b>«{domain}»</b> удален из белого списка.", parse_mode="HTML")
    else:
        await message.reply("⚠️ Домен не найден в белом списке.")


@router.message(Command("whitelist"))
async def cmd_whitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    domains = await db.get_whitelisted_domains(message.chat.id)
    if not domains:
        return await message.reply("✅ Белый список ссылок пуст.")
    
    text = "✅ <b>Белый список разрешенных доменов/ссылок:</b>\n" + "\n".join(f"• {d}" for d in domains)
    await message.reply(text, parse_mode="HTML")


# ---------------- Manual Admin Commands: Ban, Mute, Unmute ---------------- #

@router.message(Command("ban"))
async def cmd_ban(message: Message, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")
    
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ Ответьте этой командой на сообщение нарушителя, которого хотите забанить.")

    target = message.reply_to_message.from_user
    try:
        await message.chat.ban_chat_member(target.id)
        await message.reply(f"🚫 Пользователь <b>{target.full_name}</b> (<code>{target.id}</code>) заблокирован.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Не удалось забанить: {e}")


@router.message(Command("mute"))
async def cmd_mute(message: Message, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")
    
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ Ответьте на сообщение пользователя: <code>/mute 60</code> (на 60 минут)", parse_mode="HTML")

    parts = message.text.split()
    minutes = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 60

    target = message.reply_to_message.from_user
    until_date = datetime.now() + timedelta(minutes=minutes)

    try:
        await message.chat.restrict(
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        await message.reply(f"🔇 Пользователь <b>{target.full_name}</b> переведен в режим только для чтения на {minutes} мин.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка мута: {e}")


@router.message(Command("unmute", "unban"))
async def cmd_unmute(message: Message, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")
    
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return await message.reply("⚠️ Ответьте на сообщение пользователя.")

    target = message.reply_to_message.from_user
    try:
        await message.chat.restrict(
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await message.reply(f"🔊 Ограничения с пользователя <b>{target.full_name}</b> сняты.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings):
        return await message.reply("⛔ Только для администраторов.")

    stats = await db.get_chat_stats(message.chat.id)
    lines = [f"📊 <b>Статистика фильтрации:</b>", f"Всего удалено спама: <b>{stats['total_deleted']}</b>"]
    if stats["top_reasons"]:
        lines.append("\n<b>Топ причин нарушений:</b>")
        for reason, count in stats["top_reasons"]:
            lines.append(f"• {reason}: {count}")
            
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message, settings: BotSettings):
    is_adm = await is_admin(message, settings)
    
    if message.chat.type == "private" and is_adm:
        text = (
            "🤖 <b>Панель управления ботом-цензором и антиспамом</b>\n\n"
            "Этот бот защищает комментарии и личные сообщения любых ваших каналов и групп.\n\n"
            "<b>Основные разделы:</b>\n"
            "• <code>/settings</code> или <code>/chats</code> — Выбрать чат / канал для настройки\n"
            "• <code>/help</code> — Эта справка\n\n"
            "<b>Ручное управление в чате:</b>\n"
            "• <code>/addword [слово]</code> — Добавить слово в черный список\n"
            "• <code>/delword [слово]</code> — Удалить слово из черного списка\n"
            "• <code>/words</code> — Список стоп-слов\n"
            "• <code>/addwhitelist [ссылка]</code> — Разрешить ссылку/домен\n"
            "• <code>/whitelist</code> — Белый список ссылок\n"
            "• <code>/mute [минут]</code> — Замутить нарушителя (ответом на смс)\n"
            "• <code>/unmute</code> — Снять мут\n"
            "• <code>/ban</code> — Забанить нарушителя\n"
            "• <code>/stats</code> — Статистика заблокированного спама\n\n"
            "Нажмите кнопку ниже, чтобы открыть список ваших подключенных чатов или посмотреть инструкцию по подключению 👇"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Выбрать чат / канал для настройки", callback_data="back_to_chats")],
            [InlineKeyboardButton(text="📖 Как подключить новый чат/канал?", callback_data="guide_connect")]
        ])
        return await message.reply(text, reply_markup=kb, parse_mode="HTML")

    text = (
        "🤖 <b>Бот-цензор и антиспам</b>\n\n"
        "• <code>/settings</code> — Панель настройки фильтров в этом чате\n"
        "• <code>/addword [слово]</code> — Добавить стоп-слово\n"
        "• <code>/delword [слово]</code> — Удалить стоп-слово\n"
        "• <code>/words</code> — Список стоп-слов\n"
        "• <code>/addwhitelist [домен]</code> — Добавить ссылку в белый список\n"
        "• <code>/whitelist</code> — Список разрешенных ссылок\n"
        "• <code>/mute [минут]</code> / <code>/unmute</code> / <code>/ban</code> — Модерация\n"
        "• <code>/stats</code> — Статистика нарушений"
    )
    await message.reply(text, parse_mode="HTML")
