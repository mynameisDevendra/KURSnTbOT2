import os
import json
import gspread
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from datetime import datetime
from dotenv import load_dotenv
import warnings
from flask import Flask
from threading import Thread

# 1. Hide Warnings & Setup Flask for Render
warnings.simplefilter(action='ignore', category=FutureWarning)
app = Flask('')

@app.route('/')
def home():
    return "🤖 Bot is Alive!"

def run_http():
    # Render assigns a random port in the 'PORT' env var, defaulting to 8080
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# 2. Force Load .env (Only matters for local, ignored on Render)
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

# 3. Load Keys
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RAW_CREDS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS")

# 4. Configuration
GOOGLE_SHEET_ID = "1JqPBe5aQJDIGPNRs3zVCMUnIU6NDpf8dUXs1oJImNTg"
NOTEBOOK_LINK = "https://notebooklm.google.com/notebook/7dddc77d-86e6-4e76-9dce-bf30b93688bf"

# --- SERVICE SETUP (Safe for Cloud) ---
if not GEMINI_KEY or not TELEGRAM_TOKEN or not RAW_CREDS_JSON:
    print("⚠️ Notice: Keys missing from .env (This is expected if running on Cloud). Checking Environment Variables...")

try:
    if RAW_CREDS_JSON:
        creds_dict = json.loads(RAW_CREDS_JSON)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        print("✅ Connected to Google Sheet!")
    else:
        print("❌ Critical Error: No Google Credentials found.")
except Exception as e:
    print(f"❌ Connection Error: {e}")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- DEFINE TOOLS ---
def extract_transaction_data(category: str, item: str, quantity: int, location: str, status: str, sentiment: str):
    return True 

tools = [extract_transaction_data]

model = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    tools=tools,
    system_instruction="""
    You are an intelligent Railway Log Assistant.
    RULES:
    1. NORMAL MESSAGE: Extract Item, Qty, Location, infer Status.
    2. REPLY: Extract Item/Qty from PREVIOUS MESSAGE. Extract Status (Issued/Collected) from USER REPLY.
    3. TECH QUERY: Refer to Manual Notebook.
    """
)

# --- CHAT HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_name = update.effective_user.first_name
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Reply Logic
    if update.message.reply_to_message and update.message.reply_to_message.text:
        original_text = update.message.reply_to_message.text
        prompt_input = (
            f"CONTEXT [Original]: '{original_text}'\n"
            f"ACTION [Reply]: '{user_text}'\n"
            f"INSTRUCTION: Combine context. Extract Status strictly from Reply."
        )
    else:
        prompt_input = user_text

    chat = model.start_chat(enable_automatic_function_calling=False)
    
    try:
        response = chat.send_message(prompt_input)
        part = response.parts[0]

        if part.function_call:
            fc = part.function_call
            if fc.name == 'extract_transaction_data':
                args = fc.args
                status_text = args.get('status', 'Info')
                
                row_data = [
                    user_name,
                    args.get('category', 'N/A'),
                    args.get('item', 'Unknown'),
                    args.get('quantity', 0),
                    args.get('location', 'N/A'),
                    status_text,
                    args.get('sentiment', 'Neutral'),
                    user_text,
                    current_time
                ]
                sh.append_row(row_data)
                
                confirmation = f"✅ **Logged:** {status_text} | {args.get('item')} | Qty: {args.get('quantity')}"
                await context.bot.send_message(chat_id=update.effective_chat.id, text=confirmation, parse_mode='Markdown', reply_to_message_id=update.message.message_id)
        
        else:
            final_text = response.text
            if "Notebook" in final_text or "Manual" in final_text:
                final_text += f"\n\n🔗 [Open Signaling Manual]({NOTEBOOK_LINK})\n⚠️ *Tip:* Open in Chrome."
            await context.bot.send_message(chat_id=update.effective_chat.id, text=final_text, parse_mode='Markdown')

    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    keep_alive()  # Start the fake web server
    print("🤖 Bot is initializing...")
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 Bot is RUNNING!")
    app_bot.run_polling()