import logging
import os
import time

from telegram import Update, LabeledPrice
from telegram.ext import (
    Application,
    ChatJoinRequestHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HIER ANPASSEN
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]          # von @BotFather
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]  # deine eigene Chat-ID (siehe README)

ACCESS_PRICE_STARS = 1300          # Preis für 1 Monat Zugang, in Telegram Stars
ACCESS_PRICE_EUR_HINT = "14,74€"
LOGO_PATH = "logo.png"             # Bild-Datei, muss im selben Ordner wie bot.py liegen
SUBSCRIPTION_PERIOD = 30 * 24 * 60 * 60  # 30 Tage Gültigkeit pro Zahlung

CHECK_INTERVAL = 60 * 60       # wie oft geprüft wird (in Sekunden) – hier: stündlich
GRACE_PERIOD = 24 * 60 * 60    # Kulanzzeit nach Ablauf, bevor gekickt wird – hier: 24 Stunden
REMINDER_BEFORE = 3 * 24 * 60 * 60  # Erinnerung X Sekunden vor Ablauf senden – hier: 3 Tage

REMINDER_TEXT = (
    "⏰ Dein Zugang läuft in Kürze ab!\n\n"
    "Bezahl die folgende Rechnung, um weitere 30 Tage Zugang zu bekommen – "
    "sonst wirst du nach Ablauf aus der Gruppe entfernt."
)

# Deine Anleitung:
WELCOME_TEXT = (
    "Herzlich willkommen bei REDFLAG DISTRICT 🚩 Schön das du dabei sein möchtest 🤞🏻\n\n"
    "Nur noch ein letzter Schritt, dann bist du drin:\n\n"
    f"1. Du bekommst gleich eine Rechnung über {ACCESS_PRICE_STARS} Telegram Stars "
    f"({ACCESS_PRICE_EUR_HINT}) für 1 Monat Zugang\n"
    "2. Einfach bezahlen – und du wirst sofort automatisch in die Gruppe aufgenommen\n\n"
    "Wir freuen uns auf dich! 🎉"
)
# ---------------------------------------------------------------------------

# user_id -> {"group_chat_id": ..., "group_title": ...}
pending = {}

# user_id -> {"chat_id": ..., "expires_at": unix_timestamp}
active_subscriptions = {}


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wird ausgelöst, sobald jemand eine Beitrittsanfrage stellt."""
    req = update.chat_join_request
    user = req.from_user

    pending[user.id] = {
        "group_chat_id": req.chat.id,
        "group_title": req.chat.title,
    }

    try:
        # user_chat_id erlaubt dem Bot, die Person direkt anzuschreiben,
        # auch wenn sie den Bot vorher nie gestartet hat.
        with open(LOGO_PATH, "rb") as photo:
            await context.bot.send_photo(
                chat_id=req.user_chat_id,
                photo=photo,
                caption=WELCOME_TEXT,
            )
        await context.bot.send_invoice(
            chat_id=req.user_chat_id,
            title="Gruppenzugang – 1 Monat",
            description=f"Zugang zu \"{req.chat.title}\" für 1 Monat ({ACCESS_PRICE_EUR_HINT})",
            payload=f"access_{req.chat.id}_{user.id}",
            currency="XTR",
            prices=[LabeledPrice("1 Monat Zugang", ACCESS_PRICE_STARS)],
        )
    except Exception as e:
        logger.warning(f"Konnte Anfragenden nicht anschreiben: {e}")


async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muss bestätigt werden, bevor Telegram die Zahlung final abbucht."""
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wird bei jeder Stars-Zahlung ausgelöst (Erstzahlung oder erneute Zahlung für Verlängerung)."""
    user = update.effective_user
    expires_at = int(time.time()) + SUBSCRIPTION_PERIOD  # 30 Tage ab jetzt selbst berechnet
    username = f"@{user.username}" if user.username else f"{user.full_name} (kein Username)"

    if user.id in pending:
        # Erste Zahlung -> Beitritt jetzt freigeben
        data = pending.pop(user.id)
        chat_id = data["group_chat_id"]
        group_title = data["group_title"]

        try:
            await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user.id)
        except Exception as e:
            logger.warning(f"Konnte Beitritt nicht automatisch freigeben: {e}")

        await update.message.reply_text(
            "✅ Zahlung erhalten! Du wurdest zur Gruppe hinzugefügt."
        )
        admin_text = (
            f"💰 Neue Zahlung für \"{group_title}\"\n"
            f"👤 {username}\n"
            f"⭐ {ACCESS_PRICE_STARS} Stars erhalten – automatisch freigeschaltet."
        )

    elif user.id in active_subscriptions:
        # Monatliche Verlängerung eines bestehenden Mitglieds
        chat_id = active_subscriptions[user.id]["chat_id"]
        admin_text = (
            f"🔄 Abo verlängert\n"
            f"👤 {username}\n"
            f"⭐ {ACCESS_PRICE_STARS} Stars erhalten."
        )

    else:
        # Unbekannte Zahlung, sollte normalerweise nicht vorkommen
        return

    active_subscriptions[user.id] = {
        "chat_id": chat_id,
        "expires_at": expires_at,
        "reminder_sent": False,
    }

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text)
    except Exception as e:
        logger.warning(f"Benachrichtigung an Admin fehlgeschlagen: {e}")


async def check_subscriptions(context: ContextTypes.DEFAULT_TYPE):
    """Läuft regelmäßig im Hintergrund: erinnert vor Ablauf und entfernt bei Nicht-Verlängerung."""
    now = int(time.time())

    # 1. Erinnerungen verschicken (inkl. neuer Rechnung zum Verlängern)
    for uid, info in active_subscriptions.items():
        if not info["reminder_sent"] and now >= info["expires_at"] - REMINDER_BEFORE:
            try:
                await context.bot.send_message(chat_id=uid, text=REMINDER_TEXT)
                await context.bot.send_invoice(
                    chat_id=uid,
                    title="Gruppenzugang – Verlängerung",
                    description=f"Weitere 30 Tage Zugang ({ACCESS_PRICE_EUR_HINT})",
                    payload=f"renew_{info['chat_id']}_{uid}",
                    currency="XTR",
                    prices=[LabeledPrice("30 Tage Verlängerung", ACCESS_PRICE_STARS)],
                )
                info["reminder_sent"] = True
            except Exception as e:
                logger.warning(f"Konnte Erinnerung an {uid} nicht senden: {e}")

    # 2. Abgelaufene Mitgliedschaften entfernen
    expired_user_ids = [
        uid for uid, info in active_subscriptions.items()
        if now > info["expires_at"] + GRACE_PERIOD
    ]

    for uid in expired_user_ids:
        info = active_subscriptions.pop(uid)
        try:
            await context.bot.ban_chat_member(info["chat_id"], uid)
            await context.bot.unban_chat_member(info["chat_id"], uid)  # kicken, nicht dauerhaft sperren
            logger.info(f"User {uid} wegen abgelaufenem Abo entfernt.")
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🚫 Mitglied {uid} entfernt (Abo nicht verlängert).",
            )
        except Exception as e:
            logger.warning(f"Konnte {uid} nicht entfernen: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    app.job_queue.run_repeating(check_subscriptions, interval=CHECK_INTERVAL, first=CHECK_INTERVAL)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
