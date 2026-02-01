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

# 1. SETUP & CONFIGURATION
warnings.simplefilter(action='ignore', category=FutureWarning)

# Force Load .env
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

# 2. LOAD SECRETS
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RAW_CREDS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS")

# 3. GOOGLE SHEET CONFIGURATION
GOOGLE_SHEET_ID = "1JqPBe5aQJDIGPNRs3zVCMUnIU6NDpf8dUXs1oJImNTg"

# 4. SMART NOTEBOOK LIBRARY (Only 4 Notebooks)
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
    print("⚠️ Keys missing! If on Render, check your Environment Variables.")

# Connect to Google Sheets
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

# Connect to Gemini
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# --- DEFINE AI TOOLS & BRAIN ---

def extract_transaction_data(category: str, item: str, quantity: int, location: str, status: str, sentiment: str):
    return True 

tools = [extract_transaction_data]

# SMART SYSTEM INSTRUCTION
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash',
    tools=tools,
    system_instruction="""
    You are an intelligent Railway Log Assistant.
    
    MODE 1: MATERIAL LOGGING
    - IF the user reports a material movement or status update -> Call 'extract_transaction_data'.
    - IF it is a REPLY: Extract Item/Qty from the *Context*, but Status/Action from the *Reply*.
    
    MODE 2: KNOWLEDGE RETRIEVAL (Notebooks)
    - IF the user asks a question, Answer it, then APPEND A SOURCE TAG:

      1. [SOURCE: DOUBT SOLVER] -> Use this for FIELD DIAGNOSIS:
         - Track Circuits (High/Low Voltage). Point Machines (Motor faults).
         - Datalogger Analysis. Troubleshooting Flowcharts.

      2. [SOURCE: OEM] -> Use this for EQUIPMENT DETAILS:
         - EI (Medha, Siemens, Kyosan). Axle Counters (Frauscher, CEL).
         - Block Systems (UFSBI). Power Supply (IPS, ELD).
         - Error codes, card replacement, LED status.

      3. [SOURCE: ASSET_DATA] -> Use this for QUANTITIES & LOCATIONS:
         - Inventory Counts. Station Details. Jurisdiction.
         - Progress targets and Division highlights.

      4. [SOURCE: RULES] -> Use this for RULES & SIGNALING SPECS:
         - IRSEM (Signal Engineering Manual).
         - Circuit Diagrams & Drawings (Annexure II).
         - RDSO TANs & Policies.
         - G&SR (General Rules), Speed Limits, Shunting.
      
    If ambiguous, you may append multiple tags.
    """
)

# --- MAIN CHAT HANDLER ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_name = update.effective_user.first_name
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. SMART CONTEXT DETECTION
    if update.message.reply_to_message and update.message.reply_to_message.text:
        original_text = update.message.reply_to_message.text
        prompt_input = (
            f"CONTEXT [Original Msg]: '{original_text}'\n"
            f"ACTION [User Reply]: '{user_text}'\n"
            f"INSTRUCTION: User is updating a request. Extract Item from Context, Status from Action."
        )
    else:
        prompt_input = user_text

    # 2. START AI PROCESSING
    chat = model.start_chat(enable_automatic_function_calling=False)
    
    try:
        response = chat.send_message(prompt_input)
        part = response.parts[0]

        # SCENARIO A: LOGGING
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
                
                msg = f"✅ **Logged:** {status_text} | {args.get('item')} | Qty: {args.get('quantity')}"
                await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.MARKDOWN)
        
        # SCENARIO B: KNOWLEDGE ANSWER
        else:
            final_text = response.text
            links_to_add = []

            # Check for Tags (Only the 4 that exist)
            if "[SOURCE: DOUBT SOLVER]" in final_text:
                links_to_add.append(f"🚦 [Troubleshooting Guide]({NOTEBOOK_LIBRARY['DOUBT SOLVER']})")
                final_text = final_text.replace("[SOURCE: DOUBT SOLVER]", "")
            
            if "[SOURCE: OEM]" in final_text:
                links_to_add.append(f"🔧 [OEM Manuals]({NOTEBOOK_LIBRARY['OEM']})")
                final_text = final_text.replace("[SOURCE: OEM]", "")

            if "[SOURCE: ASSET_DATA]" in final_text:
                links_to_add.append(f"📊 [Asset Data]({NOTEBOOK_LIBRARY['ASSET_DATA']})")
                final_text = final_text.replace("[SOURCE: ASSET_DATA]", "")
            
            if "[SOURCE: RULES]" in final_text:
                links_to_add.append(f"📖 [Rules & Specs]({NOTEBOOK_LIBRARY['RULES']})")
                final_text = final_text.replace("[SOURCE: RULES]", "")

            # Append links
            if links_to_add:
                final_text += "\n\n" + "\n".join(links_to_add)
                final_text += "\n⚠️ *Tip:* If asked to login, tap 'Open in Chrome'."

            # --- SAFE SEND BLOCK ---
            try:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=final_text, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                print("⚠️ Markdown failed. Sending plain text.")
                clean_text = final_text.replace("[", "").replace("]", " ").replace("(", "Link: ").replace(")", "")
                await context.bot.send_message(chat_id=update.effective_chat.id, text=clean_text)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    if os.environ.get("PORT"):
        keep_alive()
        
    print("🤖 Bot is initializing...")
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 Bot is RUNNING!")
    app_bot.run_polling()