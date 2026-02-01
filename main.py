import os
import json
import gspread
import google.generativeai as genai
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from datetime import datetime
from dotenv import load_dotenv
import warnings
from flask import Flask
from threading import Thread
import traceback # Added to help see errors

# 1. SETUP & CONFIGURATION
warnings.simplefilter(action='ignore', category=FutureWarning)

script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

# 2. LOAD SECRETS
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RAW_CREDS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS")

# 3. GOOGLE SHEET CONFIGURATION
GOOGLE_SHEET_ID = "1JqPBe5aQJDIGPNRs3zVCMUnIU6NDpf8dUXs1oJImNTg"

# 4. SMART NOTEBOOK LIBRARY
# using .get() later prevents crashes if keys are missing
NOTEBOOK_LIBRARY = {
    "DOUBT SOLVER": "https://notebooklm.google.com/notebook/7dddc77d-86e6-4e76-9dce-bf30b93688bf",
    "OEM": "https://notebooklm.google.com/notebook/822125b0-47f0-4703-8a1c-ec44abf5eb17",
    "ASSET_DATA": "https://notebooklm.google.com/notebook/e064cf10-8a99-4712-a4e7-ff809415ec8e",
    "RULES": "https://notebooklm.google.com/notebook/27c3dfab-5300-4ce1-8cd9-fe1fb9bbb259"
}

# --- FAKE WEB SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 Railway Bot is Alive!"

def run_http():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_http)
    t.daemon = True
    t.start()

# --- SERVICE CONNECTION ---
if not GEMINI_KEY or not TELEGRAM_TOKEN:
    print("⚠️ Keys missing! Check .env or Render Variables.")

print("⏳ Connecting to Database...")
try:
    if RAW_CREDS_JSON:
        creds_dict = json.loads(RAW_CREDS_JSON)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        print("✅ Database Connected!")
    else:
        print("❌ Critical Error: GOOGLE_CREDENTIALS_JSON missing.")
except Exception as e:
    print(f"❌ Connection Error: {e}")

if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- DEFINE AI TOOLS & BRAIN ---

def extract_transaction_data(category: str, item: str, quantity: int, location: str, status: str, sentiment: str):
    return True 

tools = [extract_transaction_data]

model = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    tools=tools,
    system_instruction="""
    You are an intelligent Railway Log Assistant.
    
    MODE 1: MATERIAL LOGGING
    - IF user reports movement/status -> Call 'extract_transaction_data'.
    - IF REPLY: Extract Item from Context, Status from Reply.
    
    MODE 2: KNOWLEDGE (Notebooks)
    - IF user asks question, Answer it, then APPEND A SOURCE TAG:
      1. [SOURCE: DOUBT SOLVER] -> Troubleshooting, Track Circuits, Point Machines.
      2. [SOURCE: OEM] -> Equipment Manuals, EI, Axle Counters, IPS, Block Inst.
      3. [SOURCE: ASSET_DATA] -> Quantities, Locations, Jurisdiction, Targets.
      4. [SOURCE: RULES] -> G&SR, IRSEM, Signaling Specs, Drawings.
      
    If ambiguous, append multiple tags.
    """
)

# --- MAIN CHAT HANDLER (BULLETPROOF VERSION) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # GLOBAL TRY-CATCH to prevent "Stuck" bot
    try:
        user_text = update.message.text
        user_name = update.effective_user.first_name
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"📩 Message from {user_name}: {user_text}") # Debug Print

        # 1. SMART CONTEXT
        if update.message.reply_to_message and update.message.reply_to_message.text:
            original_text = update.message.reply_to_message.text
            prompt_input = (
                f"CONTEXT: '{original_text}'\n"
                f"REPLY: '{user_text}'\n"
                f"INSTRUCTION: Extract Item from Context, Status from Reply."
            )
        else:
            prompt_input = user_text

        # 2. GENERATE
        print("🤔 AI is thinking...")
        chat = model.start_chat(enable_automatic_function_calling=False)
        response = chat.send_message(prompt_input)
        part = response.parts[0]
        print("💡 AI generated response.")

        # SCENARIO A: LOGGING
        if part.function_call:
            fc = part.function_call
            if fc.name == 'extract_transaction_data':
                args = fc.args
                status_text = args.get('status', 'Info')
                row_data = [
                    user_name, args.get('category'), args.get('item'),
                    args.get('quantity'), args.get('location'), status_text,
                    args.get('sentiment'), user_text, current_time
                ]
                sh.append_row(row_data)
                print("📝 Row added to sheet.")
                
                msg = f"✅ **Logged:** {status_text} | {args.get('item')} | Qty: {args.get('quantity')}"
                await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.MARKDOWN)
        
        # SCENARIO B: KNOWLEDGE
        else:
            final_text = response.text
            links_to_add = []

            # Robust Link Swapping (Uses .get to prevent crashes)
            if "[SOURCE: DOUBT SOLVER]" in final_text:
                link = NOTEBOOK_LIBRARY.get("DOUBT SOLVER", "https://notebooklm.google.com")
                links_to_add.append(f"🚦 [Troubleshooting Guide]({link})")
                final_text = final_text.replace("[SOURCE: DOUBT SOLVER]", "")
            
            if "[SOURCE: OEM]" in final_text:
                link = NOTEBOOK_LIBRARY.get("OEM", "https://notebooklm.google.com")
                links_to_add.append(f"🔧 [OEM Manuals]({link})")
                final_text = final_text.replace("[SOURCE: OEM]", "")

            if "[SOURCE: ASSET_DATA]" in final_text:
                link = NOTEBOOK_LIBRARY.get("ASSET_DATA", "https://notebooklm.google.com")
                links_to_add.append(f"📊 [Asset Data]({link})")
                final_text = final_text.replace("[SOURCE: ASSET_DATA]", "")
            
            if "[SOURCE: RULES]" in final_text:
                link = NOTEBOOK_LIBRARY.get("RULES", "https://notebooklm.google.com")
                links_to_add.append(f"📖 [Rules & Specs]({link})")
                final_text = final_text.replace("[SOURCE: RULES]", "")
            
            # Catch-all for stray Signaling tags -> Map to RULES
            if "[SOURCE: SIGNALING]" in final_text:
                link = NOTEBOOK_LIBRARY.get("RULES", "https://notebooklm.google.com")
                links_to_add.append(f"📡 [Signaling Specs]({link})")
                final_text = final_text.replace("[SOURCE: SIGNALING]", "")

            if links_to_add:
                final_text += "\n\n" + "\n".join(links_to_add)
                final_text += "\n⚠️ *Tip:* Open in Chrome."

            # SAFE SEND BLOCK
            print("📤 Sending message...")
            try:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=final_text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                print(f"⚠️ Markdown Error: {e}. Sending Plain Text.")
                # Strip all brackets/markdown to ensure it sends
                clean_text = final_text.replace("[", "").replace("]", " ").replace("(", " Link: ").replace(")", "")
                await context.bot.send_message(chat_id=update.effective_chat.id, text=clean_text)

    except Exception as e:
        # This catches ANY other crash (Math error, Library error, etc)
        error_msg = f"❌ System Error: {str(e)}"
        print(error_msg)
        traceback.print_exc() # Prints full error to terminal
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ I encountered an error while processing that. Please try again.")

if __name__ == '__main__':
    if os.environ.get("PORT"):
        keep_alive()
        
    print("🤖 Bot is initializing...")
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 Bot is RUNNING!")
    app_bot.run_polling()