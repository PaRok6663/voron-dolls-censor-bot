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


async def is_admin(message_or_query: Message | CallbackQuery, settings: BotSettings, db: Optional[Database] = None) -> bool:
    user_id = message_or_query.from_user.id
    if user_id in settings.ADMIN_IDS:
        return True

    # Check database-added bot admins
    if db:
        if await db.is_bot_admin(user_id, settings.ADMIN_IDS):
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
        InlineKeyboardButton(text="👥 Управление администраторами", callback_data="list_admins")
    ])
    buttons.append([
        InlineKeyboardButton(text="💼 Подключить Telegram Business", callback_data="guide_business")
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
                text=f"🌐 Спам-шрифт: {mark(chat_settings.get('anti_foreign', 1))}",
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
                text=f"📷 Запрет всех медиа: {mark(chat_settings.get('block_media', 0))}",
                callback_data=f"toggle_block_media:{chat_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🎭 Запрет стикеров/GIF: {mark(chat_settings.get('block_stickers', 0))}",
                callback_data=f"toggle_block_stickers:{chat_id}"
            ),
            InlineKeyboardButton(
                text=f"👁 Блок спойлеров: {mark(chat_settings.get('block_spoilers', 0))}",
                callback_data=f"toggle_block_spoilers:{chat_id}"
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
            InlineKeyboardButton(
                text="📊 Статистика",
                callback_data=f"show_stats:{chat_id}"
            ),
            InlineKeyboardButton(
                text="📝 Стоп-слова",
                callback_data=f"show_words:{chat_id}"
            )
        ]
    ]

    if is_private:
        buttons.append([
            InlineKeyboardButton(text="◀️ Назад ко всем чатам", callback_data="back_to_chats"),
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_settings:{chat_id}")
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
    chat_id = chat.id
    title = chat.title or f"Чат {chat_id}"

    logger.info(f"Bot joined new chat/channel: {title} ({chat_id})")

    # Automatically register chat in database with default settings
    await db.get_chat_settings(chat_id, title=title)

    # If added to a group or supergroup, send a brief notification
    if chat.type in ["group", "supergroup"]:
        try:
            await bot.send_message(
                chat_id,
                f"🛡️ <b>Бот-цензор и антиспам активирован в этом чате!</b>\n\n"
                f"Фильтры порнографии, спама, нецензурной лексики и вредоносных ссылок включены.\n"
                f"Администраторы могут открыть панель настроек командой <code>/settings</code> прямо здесь или в личных сообщениях с ботом.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"Could not send welcome message to {chat_id}: {e}")

    # Notify all global bot administrators in private messages
    all_admins = await db.get_all_bot_admins()
    admin_id_set = set(settings.ADMIN_IDS) | {a["user_id"] for a in all_admins}

    for admin_id in admin_id_set:
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Настроить этот чат", callback_data=f"manage_chat:{chat_id}")],
                [InlineKeyboardButton(text="◀️ К списку всех чатов", callback_data="back_to_chats")]
            ])
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
    if not await is_admin(message, settings, db):
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
                [InlineKeyboardButton(text="📖 Как подключить канал/чат?", callback_data="guide_connect")],
                [InlineKeyboardButton(text="👥 Управление администраторами", callback_data="list_admins")]
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
        f"Чат: <b>{chat_title}</b> (<code>{chat_id}</code>)\n\n"
        f"Нажмите на нужную кнопку ниже для мгновенного переключения параметра:"
    )
    kb = build_settings_keyboard(cfg, chat_id=chat_id, is_private=False)
    await message.reply(text, reply_markup=kb, parse_mode="HTML")


# ---------------- Navigation Callbacks ---------------- #

@router.callback_query(F.data == "back_to_chats")
async def cb_back_to_chats(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chats = await db.get_managed_chats()
    kb = build_chats_list_keyboard(chats)
    text = (
        "⚙️ <b>Центр управления каналами и чатами</b>\n\n"
        "Выберите подключенный чат или канал для индивидуальной настройки:"
    )
    try:
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await query.answer()


@router.callback_query(F.data == "refresh_chats")
async def cb_refresh_chats(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
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
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = int(query.data.split(":")[1])
    cfg = await db.get_chat_settings(chat_id)
    chat_title = cfg.get("title") or f"Чат {chat_id}"

    text = (
        f"⚙️ <b>Настройки фильтрации для чата:</b>\n"
        f"📍 <b>{chat_title}</b> (ID: <code>{chat_id}</code>)\n\n"
        f"Нажмите на кнопку, чтобы включить или выключить нужный фильтр:"
    )
    kb = build_settings_keyboard(cfg, chat_id=chat_id, is_private=True)
    try:
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await query.answer()


# ---------------- Connection Guide Callbacks ---------------- #

@router.callback_query(F.data == "guide_connect")
async def cb_guide_connect(query: CallbackQuery):
    text = (
        "📖 <b>Инструкция по подключению любого канала или группы</b>\n\n"
        "Вы можете подключить к этому боту любое количество каналов и групп:\n\n"
        "<b>1. Для комментариев под постами канала:</b>\n"
        "• Откройте настройки канала в Telegram → <b>«Обсуждение»</b> (привяжите группу для комментариев, если её нет).\n"
        "• Перейдите в эту группу обсуждений → <b>«Администраторы»</b> → <b>«Добавить администратора»</b>.\n"
        "• Найдите юзернейм вашего бота и добавьте с правами:\n"
        "  ✅ <i>Удаление сообщений</i>\n"
        "  ✅ <i>Блокировка пользователей</i>\n\n"
        "<b>2. Для защиты самого канала от спам-постов:</b>\n"
        "• Зайдите в канал → <b>«Администраторы»</b> → добавьте бота администратором с правом публикации и удаления постов.\n\n"
        "<b>3. Для защиты личных сообщений (Telegram Business):</b>\n"
        "• Нажмите кнопку ниже <b>«💼 Подключить Telegram Business»</b>.\n\n"
        "После добавления чат автоматически появится в меню <code>/settings</code>!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Как подключить Telegram Business?", callback_data="guide_business")],
        [InlineKeyboardButton(text="◀️ Назад к списку чатов", callback_data="back_to_chats")]
    ])
    try:
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await query.answer()


@router.callback_query(F.data == "guide_business")
async def cb_guide_business(query: CallbackQuery, bot: Bot):
    bot_info = await bot.get_me()
    text = (
        "💼 <b>Как подключить защиту личных сообщений через Telegram Business:</b>\n\n"
        "Если у вас есть подписка Telegram Premium / Business, вы можете подключить бота к вашему личному аккаунту для автоматической чистки спама в ЛС:\n\n"
        "1. Откройте в Telegram: <b>«Настройки» → «Telegram для бизнеса»</b>.\n"
        "2. Выберите пункт <b>«Чат-боты»</b>.\n"
        f"3. В поле поиска введите юзернейм бота: <code>@{bot_info.username}</code>.\n"
        "4. Выберите нужные чаты (например, «Все новые чаты» или «Все ЛС кроме контактов»).\n"
        "5. Включите разрешение <b>«Управление сообщениями»</b> (чтобы бот мог удалять спам).\n\n"
        "✨ <b>Готово!</b> Как только бот будет подключен, он пришлет вам подтверждение в ЛС, и все входящие сообщения в вашем профиле будут автоматически защищены от спама и порнографии."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к списку чатов", callback_data="back_to_chats")]
    ])
    try:
        await query.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await query.answer()


# ---------------- Multi-Admin Management ---------------- #

@router.callback_query(F.data == "list_admins")
async def cb_list_admins(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    db_admins = await db.get_all_bot_admins()
    
    text_lines = [
        "👥 <b>Управление администраторами бота</b>\n",
        "Администраторы могут открывать меню <code>/settings</code>, настраивать любые подключенные каналы и добавлять свои чаты.\n",
        "<b>Владельцы из конфигурации (Superadmin):</b>"
    ]
    for uid in settings.ADMIN_IDS:
        text_lines.append(f"• ID: <code>{uid}</code> (Config)")

    text_lines.append("\n<b>Дополнительные администраторы:</b>")
    if db_admins:
        for a in db_admins:
            name = a.get("username") or a.get("full_name") or f"ID {a['user_id']}"
            text_lines.append(f"• <b>{name}</b> (<code>{a['user_id']}</code>) — роль: {a.get('role', 'admin')}")
    else:
        text_lines.append("<i>Пока нет дополнительных администраторов.</i>")

    text_lines.append(
        "\n<b>Команды для управления:</b>\n"
        "• <code>/addadmin [user_id]</code> — Добавить администратора\n"
        "• <code>/deladmin [user_id]</code> — Удалить администратора\n"
        "• <code>/admins</code> — Список всех администраторов"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад к списку чатов", callback_data="back_to_chats")]
    ])
    try:
        await query.message.edit_text("\n".join(text_lines), reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await query.answer()


@router.message(Command("addadmin"))
async def cmd_add_admin(message: Message, db: Database, settings: BotSettings):
    # Only superadmins (from config) or existing admins can add new admins
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Недостаточно прав для добавления администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        return await message.reply(
            "Использование: <code>/addadmin [Telegram ID пользователя]</code>\n\n"
            "<i>(Узнать свой Telegram ID можно у бота @userinfobot)</i>",
            parse_mode="HTML"
        )

    new_admin_id = int(parts[1].strip())
    await db.add_bot_admin(
        user_id=new_admin_id,
        role="admin",
        added_by=message.from_user.id
    )

    await message.reply(
        f"✅ Пользователь с ID <code>{new_admin_id}</code> успешно добавлен в администраторы бота!\n\n"
        f"Теперь он может зайти в ЛС к боту, нажать <code>/start</code> или <code>/settings</code> и настраивать каналы.",
        parse_mode="HTML"
    )


@router.message(Command("deladmin"))
async def cmd_del_admin(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Недостаточно прав.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        return await message.reply("Использование: <code>/deladmin [Telegram ID пользователя]</code>", parse_mode="HTML")

    target_id = int(parts[1].strip())
    if target_id in settings.ADMIN_IDS:
        return await message.reply("⛔ Нельзя удалить главного супер-администратора из файла конфигурации.")

    await db.remove_bot_admin(target_id)
    await message.reply(f"✅ Администратор с ID <code>{target_id}</code> удален из бота.", parse_mode="HTML")


@router.message(Command("admins"))
async def cmd_list_admins(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Доступно только администраторам.")

    db_admins = await db.get_all_bot_admins()
    lines = ["👥 <b>Список администраторов бота:</b>\n", "<b>Главные администраторы:</b>"]
    for uid in settings.ADMIN_IDS:
        lines.append(f"• ID: <code>{uid}</code> (Config)")

    lines.append("\n<b>Добавленные администраторы:</b>")
    if db_admins:
        for a in db_admins:
            name = a.get("username") or a.get("full_name") or f"ID {a['user_id']}"
            lines.append(f"• <b>{name}</b> (<code>{a['user_id']}</code>)")
    else:
        lines.append("<i>Нет</i>")

    await message.reply("\n".join(lines), parse_mode="HTML")


# ---------------- Settings Interactive Toggles ---------------- #

@router.callback_query(F.data.startswith("toggle_"))
async def callback_toggle(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    data = query.data.replace("toggle_", "")
    key, chat_id_str = data.split(":")
    chat_id = int(chat_id_str)

    cfg = await db.get_chat_settings(chat_id)
    current_val = cfg.get(key, 0)
    new_val = 0 if current_val else 1

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


@router.callback_query(F.data.startswith("cycle_action:"))
async def callback_cycle_action(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = int(query.data.split(":")[1])
    actions = ["delete", "warn", "mute_1h", "mute_24h", "ban"]
    cfg = await db.get_chat_settings(chat_id)
    current_action = cfg.get("action_on_violation", "delete")

    try:
        idx = actions.index(current_action)
        new_action = actions[(idx + 1) % len(actions)]
    except ValueError:
        new_action = "delete"

    await db.update_chat_setting(chat_id, "action_on_violation", new_action)

    updated_cfg = await db.get_chat_settings(chat_id)
    is_private = (query.message.chat.type == "private")
    try:
        await query.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(updated_cfg, chat_id=chat_id, is_private=is_private)
        )
    except TelegramBadRequest:
        pass
    await query.answer(f"Наказание: {new_action.upper()}")


@router.callback_query(F.data.startswith("refresh_settings:"))
async def callback_refresh(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = int(query.data.split(":")[1])
    cfg = await db.get_chat_settings(chat_id)
    is_private = (query.message.chat.type == "private")
    try:
        await query.message.edit_reply_markup(
            reply_markup=build_settings_keyboard(cfg, chat_id=chat_id, is_private=is_private)
        )
    except TelegramBadRequest:
        pass
    await query.answer("Настройки обновлены")


@router.callback_query(F.data.startswith("show_stats:"))
async def callback_stats(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = int(query.data.split(":")[1])
    stats = await db.get_chat_stats(chat_id)
    lines = [f"📊 <b>Статистика чата {chat_id}:</b>\n", f"Всего заблокировано нарушений: <b>{stats['total_actions']}</b>"]
    if stats["top_reasons"]:
        lines.append("\n<b>Топ причин:</b>")
        for reason, count in stats["top_reasons"]:
            lines.append(f"• {reason}: {count}")

    await query.message.reply("\n".join(lines), parse_mode="HTML")
    await query.answer()


@router.callback_query(F.data.startswith("show_words:"))
async def callback_words(query: CallbackQuery, db: Database, settings: BotSettings):
    if not await is_admin(query, settings, db):
        return await query.answer("⛔ Недостаточно прав!", show_alert=True)

    chat_id = int(query.data.split(":")[1])
    words = await db.get_custom_words(chat_id, "blacklist")
    if not words:
        text = (
            f"📝 В чате <code>{chat_id}</code> нет дополнительных стоп-слов.\n"
            f"Чтобы добавить: <code>/addword слово</code>"
        )
    else:
        text = f"📝 <b>Стоп-слова для чата {chat_id}:</b>\n" + ", ".join(f"<code>{w}</code>" for w in words)

    await query.message.reply(text, parse_mode="HTML")
    await query.answer()


# ---------------- Custom Words and Whitelist Commands ---------------- #

@router.message(Command("addword"))
async def cmd_add_word(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/addword [слово]</code>", parse_mode="HTML")

    word = parts[1].strip()
    await db.add_custom_word(message.chat.id, word, "blacklist")
    await message.reply(f"✅ Слово <code>{word}</code> добавлено в черный список этого чата.", parse_mode="HTML")


@router.message(Command("delword"))
async def cmd_del_word(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/delword [слово]</code>", parse_mode="HTML")

    word = parts[1].strip()
    await db.remove_custom_word(message.chat.id, word, "blacklist")
    await message.reply(f"✅ Слово <code>{word}</code> удалено из черного списка этого чата.", parse_mode="HTML")


@router.message(Command("words"))
async def cmd_list_words(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    words = await db.get_custom_words(message.chat.id, "blacklist")
    if not words:
        return await message.reply("В черном списке этого чата пока нет добавленных слов.")

    text = "📝 <b>Черный список слов этого чата:</b>\n" + ", ".join(f"<code>{w}</code>" for w in words)
    await message.reply(text, parse_mode="HTML")


@router.message(Command("addwhitelist"))
async def cmd_add_whitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/addwhitelist [домен или канал]</code> (например: <code>t.me/vorondolls</code>)", parse_mode="HTML")

    domain = parts[1].strip()
    await db.add_whitelisted_domain(message.chat.id, domain)
    await message.reply(f"✅ Ссылка <code>{domain}</code> добавлена в белый список этого чата.", parse_mode="HTML")


@router.message(Command("delwhitelist"))
async def cmd_del_whitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Использование: <code>/delwhitelist [домен]</code>", parse_mode="HTML")

    domain = parts[1].strip()
    await db.remove_whitelisted_domain(message.chat.id, domain)
    await message.reply(f"✅ Ссылка <code>{domain}</code> удалена из белого списка.", parse_mode="HTML")


@router.message(Command("whitelist"))
async def cmd_list_whitelist(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    domains = await db.get_whitelisted_domains(message.chat.id)
    if not domains:
        return await message.reply("Белый список ссылок этого чата пуст.")

    text = "🔗 <b>Разрешенные ссылки и домены этого чата:</b>\n" + "\n".join(f"• <code>{d}</code>" for d in domains)
    await message.reply(text, parse_mode="HTML")


# ---------------- Manual Moderation Commands ---------------- #

@router.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot, settings: BotSettings, db: Database):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    if not message.reply_to_message:
        return await message.reply("Команда должна быть ответом на сообщение нарушителя!")

    target = message.reply_to_message.from_user
    if not target:
        return await message.reply("Не удалось определить пользователя.")

    parts = message.text.split()
    minutes = 60
    if len(parts) > 1 and parts[1].isdigit():
        minutes = int(parts[1])

    until = datetime.now() + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await message.reply(f"🔇 Пользователь <b>{target.full_name}</b> замучен на <b>{minutes}</b> мин.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Не удалось выдать мут: {e}")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot, settings: BotSettings, db: Database):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    if not message.reply_to_message:
        return await message.reply("Команда должна быть ответом на сообщение пользователя.")

    target = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        await message.reply(f"🔊 Мут с пользователя <b>{target.full_name}</b> снят.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка: {e}")


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot, settings: BotSettings, db: Database):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    if not message.reply_to_message:
        return await message.reply("Команда должна быть ответом на сообщение нарушителя!")

    target = message.reply_to_message.from_user
    try:
        await bot.ban_chat_member(chat_id=message.chat.id, user_id=target.id)
        await message.reply(f"⛔ Пользователь <b>{target.full_name}</b> заблокирован.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"❌ Ошибка при блокировке: {e}")


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, settings: BotSettings):
    if not await is_admin(message, settings, db):
        return await message.reply("⛔ Только для администраторов.")

    stats = await db.get_chat_stats(message.chat.id)
    lines = [f"📊 <b>Статистика фильтрации:</b>", f"Всего удалено спама: <b>{stats['total_actions']}</b>"]
    if stats["top_reasons"]:
        lines.append("\n<b>Топ причин нарушений:</b>")
        for reason, count in stats["top_reasons"]:
            lines.append(f"• {reason}: {count}")
            
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message, settings: BotSettings, db: Database):
    is_adm = await is_admin(message, settings, db)
    
    if message.chat.type == "private" and is_adm:
        text = (
            "🤖 <b>Панель управления ботом-цензором и антиспамом</b>\n\n"
            "Этот бот защищает комментарии и личные сообщения любых ваших каналов, групп и бизнес-аккаунтов.\n\n"
            "<b>Основные разделы:</b>\n"
            "• <code>/settings</code> или <code>/chats</code> — Выбрать чат / канал для настройки\n"
            "• <code>/admins</code> — Список администраторов бота\n"
            "• <code>/addadmin [user_id]</code> — Добавить нового администратора\n"
            "• <code>/deladmin [user_id]</code> — Удалить администратора\n"
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
            [InlineKeyboardButton(text="👥 Управление администраторами", callback_data="list_admins")],
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
