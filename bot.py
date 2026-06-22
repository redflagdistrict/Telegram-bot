import logging
import os
import csv
import json
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    ChatJoinRequestHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HIER ANPASSEN
# ---------------------------------------------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]

RULES_URL = "https://tinyurl.com/REDFLAGDISTRICT"  # Link zum Gutschein

CSV_FILE = "codes.csv"          # Wird auf dem Server gespeichert
PENDING_FILE = "pending.json"   # Warteliste wird hier gespeichert
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Warteliste: laden & speichern
# ---------------------------------------------------------------------------
def load_pending() -> dict:
    """Lädt die Warteliste aus der JSON-Datei."""
    if os.path.isfile(PENDING_FILE):
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                return {int(k): v for k, v in json.load(f).items()}
        except Exception as e:
            logger.warning(f"Warteliste konnte nicht geladen werden: {e}")
    return {}


def save_pending(pending: dict):
    """Speichert die Warteliste in die JSON-Datei."""
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Warteliste konnte nicht gespeichert werden: {e}")


# Beim Start laden
pending = load_pending()


# ---------------------------------------------------------------------------
# CSV-Hilfsfunktion
# ---------------------------------------------------------------------------
def save_to_csv(telegram_username, submitted_code, group_title):
    """Speichert einen neuen Eintrag in die CSV-Datei."""
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Telegram Username", "Eingegebener Code", "Gruppe", "Datum & Uhrzeit"])
        writer.writerow([
            telegram_username,
            submitted_code,
            group_title,
            datetime.now().strftime("%d.%m.%Y %H:%M"),
        ])


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wird ausgelöst, sobald jemand eine Beitrittsanfrage stellt."""
    req = update.chat_join_request
    user = req.from_user
    if user.is_bot:
        return

    pending[user.id] = {
        "group_chat_id": req.chat.id,
        "group_title": req.chat.title,
    }
    save_pending(pending)

    try:
        with open("logo.png", "rb") as photo:
            await context.bot.send_photo(
                chat_id=req.user_chat_id,
                photo=photo,
                caption=(
                    "Herzlich Willkommen bei **REDFLAG DISTRICT** 🚩\n\n"
                    "Schön, dass du dabei sein möchtest! Im District geht es gerade ganz schön heiß her 🔥 Der Albtraum jeder REDFLAG 😈!\n\n"
                    "Nur noch ein kleiner Schritt, dann bist du drin 👇"
                ),
            )

        await context.bot.send_message(
            chat_id=req.user_chat_id,
            text=(
                "📜 **Schritt 1:**\n"
                "Klick auf den Link und hol dir deinen Gutschein-Code:\n\n"
                f"{RULES_URL}"
            ),
        )

        await context.bot.send_message(
            chat_id=req.user_chat_id,
            text=(
                "✍️ **Schritt 2:**\n"
                "Kopiere den Code, den du nach dem Kauf erhalten hast, "
                "und füge ihn als normale Nachricht unten im Chat ein – "
                "also genau so, wie du gerade mit mir schreiben würdest. "
                "Einfach einfügen und abschicken! 📩 "
                "(Der Code besteht aus 32 Ziffern)\n\n"
                "Du wirst danach schnellstmöglich freigeschaltet.\n\n"
                "🩷 Sollten Fragen oder Probleme auftreten, melde dich gerne beim Admin: @redflagdistrict_de\n\n"
                "Wir freuen uns auf dich! 🎉"
            ),
        )

        try:
            with open("code example.png", "rb") as photo:
                await context.bot.send_photo(
                    chat_id=req.user_chat_id,
                    photo=photo,
                    caption="👆 So wird es aussehen, wenn du den Gutschein gekauft hast und den Code bekommst. Wo der Pfeil hin zeigt, kannst du ihn kopieren und einfach hier im Telegram Chat unten als Nachricht abschicken ✅",
                )
        except Exception as e:
            logger.warning(f"Code-Beispielbild konnte nicht gesendet werden: {e}")
    except Exception as e:
        logger.warning(f"Konnte Anfragenden nicht anschreiben: {e}")


async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reagiert auf den eingetippten Code."""
    user = update.effective_user
    if user.id not in pending:
        return

    data = pending.pop(user.id)
    save_pending(pending)

    submitted_code = update.message.text.strip()

    # Bestätigung an den User
    await update.message.reply_text(
        "✅ Perfekt! Dein Code wurde übermittelt und wird überprüft.\n\n"
        "Aufgrund des hohen Andrangs kann es bis zu 60 Minuten dauern, "
        "bis du hinzugefügt wirst.\n\n"
        "Wir freuen uns auf dich! 🎉\n\n"
        "🩷 Fragen oder Probleme? Melde dich gerne beim Admin @redflagdistrict_de"
    )

    # Telegram-Username für Benachrichtigung
    tg_username = f"@{user.username}" if user.username else f"{user.full_name} (kein @Username)"

    # CSV speichern
    try:
        save_to_csv(tg_username, submitted_code, data["group_title"])
    except Exception as e:
        logger.warning(f"CSV-Speicherung fehlgeschlagen: {e}")

    # Benachrichtigung an Admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🆕 Neue Beitrittsanfrage für \"{data['group_title']}\"\n"
                f"👤 Telegram: {tg_username}\n"
                f"📝 Eingegebener Code: {submitted_code}\n"
                f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"➡️ Genehmige manuell in Telegram (Gruppe → Mitgliederanfragen)."
            ),
        )
    except Exception as e:
        logger.warning(f"Admin-Benachrichtigung fehlgeschlagen: {e}")


async def send_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sendet dir die aktuelle Code-Liste als CSV, wenn du /liste schreibst."""
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        return
    if not os.path.isfile(CSV_FILE):
        await update.message.reply_text("Noch keine Einträge vorhanden.")
        return
    with open(CSV_FILE, "rb") as f:
        await context.bot.send_document(
            chat_id=ADMIN_CHAT_ID,
            document=f,
            filename="redflag_district_codes.csv",
        )


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, check_answer
    ))
    app.add_handler(MessageHandler(
        filters.Command("liste") & filters.ChatType.PRIVATE, send_csv
    ))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
