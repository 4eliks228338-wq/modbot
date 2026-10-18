import asyncio
import logging
import os
import re
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

import config
from rules_checker import RulesChecker, RuleViolation

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("RuleGuard")

# Инициализация Gemini AI (если указан GEMINI_API_KEY)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        from google.genai import types
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Подключен модуль Gemini AI для глубокой проверки сообщений и изображений!")
    except Exception as e:
        logger.warning(f"Не удалось инициализировать Gemini AI: {e}")

# Доступные модели Gemini с автопереключением при исчерпании лимитов
AVAILABLE_AI_MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
    "gemini-flash-lite-latest",
)

# Инициализация проверки локальных правил
checker = RulesChecker(
    politics_channel=config.POLITICS_CHANNEL_KEYWORD,
    flood_channel=config.FLOOD_CHANNEL_KEYWORD
)

TARGET_GUILD_NAME = os.getenv("TARGET_GUILD_NAME", "all").lower()


async def check_with_ai(content: str, channel_name: str) -> tuple[str, str] | None:
    """Проверяет сообщение через Gemini AI при наличии API-ключа.
    Возвращает (rule_code, reason) или None, если нарушений нет."""
    # Короткие сообщения (<10 символов: мат, междометия, лол, хуй) не нагружают AI и не спамят ложными алертами
    if not gemini_client or not content or len(content.strip()) < 10:
        return None

    prompt = f"""Ты — строгий AI-модератор Discord-сервера. Оцени сообщение участника на предмет РЕАЛЬНЫХ нарушений правил:

Правила сервера:
п:3.1 Травля, целенаправленные жестокие оскорбления и унижение конкретного человека
п:4.0 Дискриминация, расизм, нацизм (н-ворды, п-ворды, шовинизм)
п:5.0 Доксинг, деанон, сливы личных данных (паспорта, номера телефонов, адреса, базы данных)
п:6.0 NSFW/NSFL контент (порно, хентай, расчлененка, кровь, шок-контент)
п:8.0 Политические срачи (разрешены только в специальном канале дискуссий)
п:9.0 Реклама сторонних серверов/каналов (ссылки discord.gg, t.me)
п:14.0 Реальные угрозы расправой (сваттинг, угрозы физического насилия)
п:15.0 Фишинг, скам, продажа аккаунтов, вредоносные ссылки
п:16.0 Злоупотребление упоминаниями (массовые пинги)
п:19.0 Шутки и мемы про трагедии/суициды/массшутинг (Ронни Макнатт, 1444 Кораблёв, Галявиев, Росляков, Крокус)

КРИТИЧЕСКИ ВАЖНЫЕ ИСКЛЮЧЕНИЯ (НЕ СЧИТАТЬ НАРУШЕНИЕМ):
1. Обычный мат, ругательства, эмоциональные восклицания («нахуй», «хуй», «бля», «пиздец», «ахуели», «какое нахуй», «дилдо») и геймерский сленг НЕ ЯВЛЯЮТСЯ нарушением п:3.1! Нарушением п:3.1 считается ТОЛЬКО целенаправленная травля и жестокое унижение собеседника.
2. Опечатки, случайный набор букв или текст в чужой раскладке (например «lhfcnt» = «здраст») НЕ ЯВЛЯЮТСЯ спамом (п:10.0)!
3. Самоирония («ну а я даун», «я тупой») НЕ ЯВЛЯЕТСЯ дискриминацией или оскорблением!
4. Вымышленные поп-культурные войны («Звездные войны», «Война бесконечности», клановые войны) НЕ ЯВЛЯЮТСЯ политикой (п:8.0).

Канал: #{channel_name}
Текст сообщения: "{content}"

Если сообщение РЕАЛЬНО грубо НАРУШАЕТ правила, ответь строго в формате:
ДА п:X.Y | Краткая причина нарушения

Если сообщение НЕ нарушает правила, ответь строго одним словом:
НЕТ"""

    for model_name in AVAILABLE_AI_MODELS:
        try:
            response = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=prompt
            )
            text = response.text.strip()
            if text.upper().startswith("ДА"):
                parts = text.split("|", 1)
                code_part = parts[0].replace("ДА", "").strip()
                reason = parts[1].strip() if len(parts) > 1 else "Нарушение правил"
                return (code_part, reason)
            return None
        except Exception as e:
            logger.warning(f"Ошибка Gemini ({model_name}): {e}")
    return None


async def check_image_with_ai(image_bytes: bytes, mime_type: str, filename: str = "") -> tuple[str, str] | None:
    """Проверяет изображение через Gemini Vision на запрещенный контент (NSFW, NSFL/шок, нацизм, доксинг, шок-мемы)."""
    if not gemini_client or not image_bytes:
        return None

    prompt = """Ты — строгий AI-модератор Discord-сервера. Твоя задача — проверить данное изображение на запрещенный контент:

Запрещенный контент:
1. п:6.0 NSFW: Порнография, хентай, эротика, обнаженка, половые органы, сексуальные действия.
2. п:6.0 NSFL / Шок-контент: Расчлененка, кровь, трупы, тяжелые травмы, кадры жестоких расправ, насилие (Gore).
3. п:4.0 Нацизм и разжигание ненависти: Нацистская свастика, символика SS, нацистские флаги, пропаганда фашизма.
4. п:5.0 Доксинг / Личные данные: Фото паспортов, водительских прав, банковских карт с реквизитами, личных документов.
5. п:19.0 Трагедии и шок-мемы: Кадры стримов самоубийств (Ронни Макнатт / Ronnie McNutt, 1444 Глеб Кораблёв), кадры казней картелей (Funkytown, Голда, Коча, Сердцеед), фото и прославление стрелков (Галявиев, Росляков, Бекмансуров, Колумбайн).

РАЗРЕШЕНО (НЕ является нарушением):
- Обычные мемы, смешные картинки, котики, собаки, арт и аниме без обнаженки, скриншоты видеоигр.

Если изображение НАРУШАЕТ правила, ответь строго в формате:
ДА п:X.Y | Краткое описание запрещенного контента на изображении

Если изображение НЕ нарушает правила, ответь строго одним словом:
НЕТ"""

    try:
        from google.genai import types
        part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    except Exception as e:
        logger.warning(f"Ошибка подготовки изображения: {e}")
        return None

    for model_name in AVAILABLE_AI_MODELS:
        try:
            response = await gemini_client.aio.models.generate_content(
                model=model_name,
                contents=[part, prompt]
            )
            text = response.text.strip()
            if text.upper().startswith("ДА"):
                parts = text.split("|", 1)
                code_part = parts[0].replace("ДА", "").strip()
                reason = parts[1].strip() if len(parts) > 1 else "Запрещенный контент на изображении"
                return (code_part, reason)
            return None
        except Exception as e:
            logger.warning(f"Ошибка Gemini Vision ({model_name}): {e}")
    return None


async def fetch_image(url: str) -> tuple[bytes, str] | None:
    """Безопасно скачивает изображение по URL (до 10 МБ)."""
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    c_type = resp.headers.get("Content-Type", "")
                    if "image" in c_type:
                        data = await resp.read()
                        if len(data) <= 10 * 1024 * 1024:
                            return data, c_type.split(";")[0].strip()
    except Exception as e:
        logger.debug(f"Не удалось загрузить изображение по URL {url}: {e}")
    return None


async def send_violation_alert(message: discord.Message, verdict: str, details: str, trigger: str = "", is_ai: bool = False):
    author = message.author
    guild = message.guild
    channel = message.channel

    embed = discord.Embed(
        title=f"Нарушение: {verdict}",
        color=0x2B2D31,
        timestamp=message.created_at
    )

    guild_name = guild.name if guild else "cult of browny"
    ch_name = getattr(channel, "name", "чат")
    embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
    embed.add_field(
        name="Автор",
        value=f"{author.mention}\nЮз: @{author.name}\nНик: {author.display_name}\nID: {author.id}",
        inline=True
    )
    if trigger:
        embed.add_field(name="Триггер", value=f"`{trigger}`", inline=True)
    if details:
        embed.add_field(name="Почему", value=details, inline=False)

    clean_content = message.content or "[без текста / вложение]"
    if len(clean_content) > 1000:
        clean_content = clean_content[:997] + "..."
    embed.add_field(name="Сообщение", value=f"```{clean_content}```", inline=False)

    if message.attachments:
        att_links = [f"[{att.filename}]({att.url})" for att in message.attachments]
        embed.add_field(name="Вложения", value=", ".join(att_links), inline=False)

    view = discord.ui.View()
    if message.jump_url:
        view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))

    for uid in config.MODERATOR_USER_IDS:
        user = bot.get_user(uid)
        if not user:
            try:
                user = await bot.fetch_user(uid)
            except Exception:
                pass
        if user:
            try:
                await user.send(embed=embed, view=view)
                logger.info(f"Алерт отправлен в ЛС: {user.name} ({user.id})")
            except Exception as e:
                logger.error(f"Ошибка отправки алерта {user.name}: {e}")


def create_bot(with_message_content: bool = True) -> commands.Bot:
    intents = discord.Intents.default()
    if with_message_content:
        intents.message_content = True

    b = commands.Bot(command_prefix=":", intents=intents)

    @b.event
    async def on_ready():
        try:
            synced = await b.tree.sync()
            logger.info(f"Синхронизировано команд и контекстных меню: {len(synced)}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации команд: {e}")

        logger.info(f"Бот успешно запущен как {b.user} (ID: {b.user.id})")
        logger.info(f"Мониторинг сервера: '{TARGET_GUILD_NAME}' активен.")
        for g in b.guilds:
            logger.info(f"Подключен к серверу: '{g.name}' (ID: {g.id})")

    @b.event
    async def on_message(message: discord.Message):
        # Игнорируем ботов и сообщения вне серверов
        if message.author.bot or not message.guild:
            return

        # Если это скрытая команда с префиксом ':', выполняем её и не проверяем на нарушения
        if message.content.startswith(":"):
            await b.process_commands(message)
            return

        # Фильтруем сервер (если в .env указано 'all' или пусто — проверяем все серверы)
        if TARGET_GUILD_NAME and TARGET_GUILD_NAME not in ("all", "*"):
            allowed_guilds = [g.strip() for g in TARGET_GUILD_NAME.split(",") if g.strip()]
            if not any(g in message.guild.name.lower() for g in allowed_guilds):
                return

        # Логируем входящее сообщение
        if not message.content:
            logger.warning(f"[{message.guild.name}][#{message.channel.name}] Сообщение от {message.author} пришло с ПУСТЫМ текстом! Причина: тумблер 'Message Content Intent' выключен в Discord Developer Portal.")
        else:
            logger.info(f"[{message.guild.name}][#{message.channel.name}] Получено сообщение от {message.author}: '{message.content}'")

        # 1. Быстрая жесткая проверка по правилам (банворды, леетспик, регулярки)
        violations = checker.check_message(
            content=message.content,
            channel_name=getattr(message.channel, "name", "чат"),
            author_id=message.author.id,
            mentions_count=len(message.mentions),
            has_everyone=getattr(message, "mention_everyone", False)
        )

        if violations:
            top_v = violations[0]
            verdict = f"ДА {top_v.rule_code} ({top_v.rule_name})"
            logger.info(f"[{message.guild.name}][#{message.channel.name}] Нарушение от {message.author}: {verdict}")
            await send_violation_alert(message, verdict=verdict, details=top_v.details, trigger=top_v.matched_word, is_ai=False)
            return

        # 2. Проверка вложений-изображений через Gemini Vision
        if gemini_client and message.attachments:
            for att in message.attachments[:3]:
                ext = os.path.splitext(att.filename)[1].lower()
                is_img = (att.content_type and att.content_type.startswith("image/")) or ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif')
                if is_img and att.size <= 10 * 1024 * 1024:
                    try:
                        img_bytes = await att.read()
                        mime = att.content_type or (f"image/{ext.replace('.', '')}" if ext else "image/png")
                        img_res = await check_image_with_ai(img_bytes, mime, att.filename)
                        if img_res:
                            code, reason = img_res
                            verdict = f"ДА {code} (ИИ)"
                            logger.info(f"[{message.guild.name}][#{message.channel.name}] AI Vision обнаружил нарушение во вложении {att.filename}: {verdict}")
                            await send_violation_alert(message, verdict=verdict, details=reason, trigger=att.filename, is_ai=True)
                            return
                    except Exception as e:
                        logger.warning(f"Ошибка проверки вложения {att.filename}: {e}")

        # 3. Проверка прямых ссылок на изображения через Gemini Vision
        if gemini_client and message.content:
            urls = re.findall(r'https?://\S+', message.content)
            for url in urls[:2]:
                url_clean = url.split("?")[0].lower()
                if any(url_clean.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif')) or "cdn.discordapp.com/attachments/" in url.lower():
                    img_data = await fetch_image(url)
                    if img_data:
                        img_bytes, mime = img_data
                        fname = url.split("/")[-1].split("?")[0]
                        img_res = await check_image_with_ai(img_bytes, mime, fname)
                        if img_res:
                            code, reason = img_res
                            verdict = f"ДА {code} (ИИ)"
                            logger.info(f"[{message.guild.name}][#{message.channel.name}] AI Vision обнаружил нарушение по ссылке {url}: {verdict}")
                            await send_violation_alert(message, verdict=verdict, details=reason, trigger=fname, is_ai=True)
                            return

        # 4. Если локальные регулярки не сработали, но подключен Gemini AI - проверяем контекст текста через AI
        if gemini_client and message.content:
            ai_res = await check_with_ai(message.content, getattr(message.channel, "name", "чат"))
            if ai_res:
                code, reason = ai_res
                verdict = f"ДА {code} (ИИ)"
                logger.info(f"[{message.guild.name}][#{message.channel.name}] AI обнаружил нарушение от {message.author}: {verdict}")
                await send_violation_alert(message, verdict=verdict, details=reason, trigger="", is_ai=True)
                return

        await b.process_commands(message)

    # Контекстное меню сообщения
    @b.tree.context_menu(name="Проверить сообщение")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def check_message_context(interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)

        guild_name = message.guild.name if message.guild else "cult of browny"
        ch_name = getattr(message.channel, "name", "чат")

        violations = checker.check_message(
            content=message.content,
            channel_name=ch_name,
            author_id=message.author.id,
            mentions_count=len(message.mentions),
            has_everyone=getattr(message, "mention_everyone", False)
        )

        if violations:
            top_v = violations[0]
            verdict = f"ДА {top_v.rule_code} ({top_v.rule_name})"
            embed = discord.Embed(
                title=f"Нарушение: {verdict}",
                color=0x2B2D31
            )
            embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
            embed.add_field(
                name="Автор",
                value=f"{message.author.mention}\nЮз: @{message.author.name}\nНик: {message.author.display_name}\nID: {message.author.id}",
                inline=True
            )
            if top_v.matched_word:
                embed.add_field(name="Триггер", value=f"`{top_v.matched_word}`", inline=True)
            embed.add_field(name="Почему", value=top_v.details, inline=False)
            clean = message.content or "[без текста / вложение]"
            embed.add_field(name="Сообщение", value=f"```{clean[:800]}```", inline=False)
            view = discord.ui.View()
            if message.jump_url:
                view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        if gemini_client and message.attachments:
            for att in message.attachments[:3]:
                ext = os.path.splitext(att.filename)[1].lower()
                is_img = (att.content_type and att.content_type.startswith("image/")) or ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif')
                if is_img and att.size <= 10 * 1024 * 1024:
                    try:
                        img_bytes = await att.read()
                        mime = att.content_type or (f"image/{ext.replace('.', '')}" if ext else "image/png")
                        img_res = await check_image_with_ai(img_bytes, mime, att.filename)
                        if img_res:
                            code, reason = img_res
                            verdict = f"ДА {code} (ИИ)"
                            embed = discord.Embed(title=f"Нарушение: {verdict}", color=0x2B2D31)
                            embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
                            embed.add_field(name="Автор", value=f"{message.author.mention}\nЮз: @{message.author.name}\nНик: {message.author.display_name}\nID: {message.author.id}", inline=True)
                            embed.add_field(name="Триггер", value=f"`{att.filename}`", inline=True)
                            embed.add_field(name="Почему", value=reason, inline=False)
                            clean = message.content or "[без текста / вложение]"
                            embed.add_field(name="Сообщение", value=f"```{clean[:800]}```", inline=False)
                            view = discord.ui.View()
                            if message.jump_url:
                                view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))
                            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                            return
                    except Exception as e:
                        logger.warning(f"Ошибка проверки вложения в контекстном меню: {e}")

        if gemini_client and message.content:
            ai_res = await check_with_ai(message.content, ch_name)
            if ai_res:
                code, reason = ai_res
                verdict = f"ДА {code} (ИИ)"
                embed = discord.Embed(
                    title=f"Нарушение: {verdict}",
                    color=0x2B2D31
                )
                embed.add_field(name="Откуда:", value=f"{guild_name} • #{ch_name}", inline=False)
                embed.add_field(
                    name="Автор",
                    value=f"{message.author.mention}\nЮз: @{message.author.name}\nНик: {message.author.display_name}\nID: {message.author.id}",
                    inline=True
                )
                embed.add_field(name="Почему", value=reason, inline=False)
                clean = message.content or "[без текста / вложение]"
                embed.add_field(name="Сообщение", value=f"```{clean[:800]}```", inline=False)
                view = discord.ui.View()
                if message.jump_url:
                    view.add_item(discord.ui.Button(label="Перейти к сообщению", url=message.jump_url, style=discord.ButtonStyle.link))
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                return

        await interaction.followup.send(f"Нарушений не обнаружено: {message.author.mention}.", ephemeral=True)

    # Скрытая префикс-команда
    @b.command(name="test_rules", aliases=["test"])
    async def cmd_test_rules(ctx: commands.Context, *, text: str = ""):
        if not text:
            await ctx.reply("Использование: `:test <текст>`", delete_after=5)
            return

        violations = checker.check_message(
            content=text,
            channel_name=getattr(ctx.channel, "name", "общий"),
            author_id=ctx.author.id,
            mentions_count=0,
            has_everyone=False
        )
        if violations:
            top_v = violations[0]
            await ctx.reply(f"Вердикт: ДА {top_v.rule_code} ({top_v.rule_name}) | `{top_v.matched_word}` — {top_v.details}")
            return

        if gemini_client:
            ai_res = await check_with_ai(text, getattr(ctx.channel, "name", "общий"))
            if ai_res:
                code, reason = ai_res
                await ctx.reply(f"Вердикт: ДА {code} (ИИ) | {reason}")
                return
            await ctx.reply("Вердикт: НЕТ")
            return

        await ctx.reply("Вердикт: НЕТ")

    return b


bot = create_bot(with_message_content=True)


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        logger.error("ОШИБКА: Токен бота не указан в config.py или файле .env!")
    else:
        try:
            bot.run(config.DISCORD_TOKEN)
        except discord.errors.PrivilegedIntentsRequired:
            logger.warning(
                "\n" + "=" * 65 + "\n"
                "⚠️ Внимание: Message Content Intent выключен на портале Discord!\n"
                "Чтобы бот автоматически сканировал чаты сервера 'cult of browny',\n"
                "включите тумблер 'Message Content Intent' в Developer Portal:\n"
                "https://discord.com/developers/applications/1560610957103730830/bot\n\n"
                "Запускаем бота без привилегированных интентов (режим Context Menu)...\n"
                + "=" * 65 + "\n"
            )
            bot = create_bot(with_message_content=False)
            bot.run(config.DISCORD_TOKEN)
