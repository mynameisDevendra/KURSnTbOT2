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

# 1. SETUP & CLOUD CONFIGURATION
warnings.simplefilter(action='ignore', category=FutureWarning)

# Force Load .env (Only works on Local Machine, ignored on Cloud)
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(env_path)

# 2. LOAD SECRETS (From .env or Render Environment)
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RAW_CREDS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS")

# 3. GOOGLE SHEET CONFIGURATION
GOOGLE_SHEET_ID = "1JqPBe5aQJDIGPNRs3zVCMUnIU6NDpf8dUXs1oJImNTg"

# 4. SMART NOTEBOOK LIBRARY (Update these links!)
# The AI will decide which one to show based on the user's question.
NOTEBOOK_LIBRARY = {
    "DOUBT SOLVER": "https://notebooklm.google.com/notebook/7dddc77d-86e6-4e76-9dce-bf30b93688bf",
    "OEM": "https://notebooklm.google.com/notebook/822125b0-47f0-4703-8a1c-ec44abf5eb17",
    "ASSET_DATA": "https://notebooklm.google.com/notebook/e064cf10-8a99-4712-a4e7-ff809415ec8e",
    "RULES": "https://notebooklm.google.com/notebook/27c3dfab-5300-4ce1-8cd9-fe1fb9bbb259"
}

# --- FAKE WEB SERVER (FOR RENDER KEEP-ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 Railway Bot is Alive and Running!"

def run_http():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_http)
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
    """ Dummy function to trigger the AI tool use """
    return True 

tools = [extract_transaction_data]

# SMART SYSTEM INSTRUCTION
# This teaches the AI to handle Logs AND classify Notebook topics
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
      - # ... inside system_instruction ...

      [SOURCE: DOUBT SOLVER] -> Use this for FIELD DIAGNOSIS (Symptoms & Fixes):
         - **Track Circuits:** Solving "High Voltage/Low Current" or "Low Voltage/High Current" issues at Feed/Relay ends.
         - **Point Machines:** Fixing common failures like "Motor not starting," "Continuous rotation," or "Gap in tongue rail."
         - **Datalogger Analysis:** Interpreting specific relay (TPR, NWCPR, RWCPR) statuses to find the fault.
         - **Step-by-Step Flowcharts:** Logic trees for identifying open circuits, loose connections, or obstructions. -> [SOURCE: DOUBT SOLVER]
      - # ... inside system_instruction ...

      [SOURCE: OEM_MANUAL] -> Use this for SPECIFIC EQUIPMENT details:
         - **Electronic Interlocking (EI):** Troubleshooting & Cards for Medha (MEI633), Siemens (Westrace Mk2), and Kyosan (K5BMC).
         - **Axle Counters (DAC):** Error codes & Resetting for Frauscher (FAdC R2), CEL (HASSDAC), Medha (MSDAC), and GG Tronics.
         - **Block Systems (UFSBI):** Operation & Maintenance for Deltron, Webfil, and Automatic Block Signaling (ABS).
         - **Power & Safety:** IPS Manuals (HBL, Statcon), ELD (Anu Vidyut, AEW), and Fire/Smoke Detectors.
         - **Key Triggers:** "Error code", "LED status", "Card replacement", "Wiring diagram for [Brand]", "Maintenance Schedule". -> [SOURCE: OEM]
      - # ... inside the system_instruction block ...

      [SOURCE: ASSET_DATA] -> Use this for:
         - **Inventory & Quantities:** Counts and details of Point Machines, IPS, Batteries, Block Instruments (DLBI/TLBI), and LC Gates.
         - **Axle Counters:** Specifics of MSDAC, HASSDAC, and SSDAC (Makes like Frauscher, Medha, CEL, and Section locations).
         - **Station Details:** Station Class, Interlocking Standard (Std II/III), System Maps, and Distances (Km).
         - **Organization & Jurisdiction:** Who is the in-charge SSE/JE or ASTE for a specific section (Jurisdiction lists).
         - **Progress & Targets:** Monthly achievements (PCDO), ongoing works (Cable replacement), and Division highlights. -> [SOURCE: ASSET_DATA]
      - # ... inside the system_instruction block ...

      [SOURCE: SIGNALING_MANUAL] -> Use this for:
         - **Installation & Maintenance:** Standard practices for Relays, Points, EI, and Block Instruments (from IRSEM & Annexure I).
         - **Technical Policies:** RDSO Technical Advisory Notes (TANs), Earthing & Lightning protection, and recent Corrigendums.
         - **Drawings & Circuits:** Standard circuit diagrams, contact analysis, and power supply arrangements (from Annexure II).
         - **Inter-departmental Rules:** Interface rules with Track (P-Way) and Traction (OHE/ACTM) departments.
         - **Specifications:** Technical specs for items like IPIS, Cables, and Integrated Power Systems (IPS). -> [SOURCE: RULES]
      
    If ambiguous, you may append multiple tags.
    """
)

# --- MAIN CHAT HANDLER ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user_name = update.effective_user.first_name
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. SMART CONTEXT DETECTION (Handle Replies)
    if update.message.reply_to_message and update.message.reply_to_message.text:
        original_text = update.message.reply_to_message.text
        # Combine messages so AI understands "Issued" refers to the "Relays" above
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

        # SCENARIO A: AI WANTS TO LOG DATA (Tool Call)
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
                
                confirmation = (
                    f"✅ **Update Logged**\n"
                    f"Status: {status_text} | Item: {args.get('item')} | Qty: {args.get('quantity')}"
                )
                await context.bot.send_message(chat_id=update.effective_chat.id, text=confirmation, parse_mode='Markdown', reply_to_message_id=update.message.message_id)
        
        # SCENARIO B: AI ANSWERS A QUESTION (Smart Notebook Linking)
        else:
            final_text = response.text
            links_to_add = []

            # Check for Tags and swap them with real links
            if "[SOURCE: DOUBT SOLVER]" in final_text:
                links_to_add.append(f"🚦 [DOUBT SOLVER]({NOTEBOOK_LIBRARY['DOUBT SOLVER']})")
                final_text = final_text.replace("[SOURCE: DOUBT SOLVER]", "")
            
            if "[SOURCE: OEM]" in final_text:
                links_to_add.append(f"📡 [OEM]({NOTEBOOK_LIBRARY['OEM']})")
                final_text = final_text.replace("[SOURCE: OEM]", "")

            if "[SOURCE: ASSET_DATA]" in final_text:
                links_to_add.append(f"📊 [Asset Data]({NOTEBOOK_LIBRARY['ASSET_DATA']})")
                final_text = final_text.replace("[SOURCE: ASSET_DATA]", "")
            
            if "[SOURCE: RULES]" in final_text:
                links_to_add.append(f"📖 [General Rules]({NOTEBOOK_LIBRARY['RULES']})")
                final_text = final_text.replace("[SOURCE: RULES]", "")

            # Append links if any were found
            if links_to_add:
                final_text += "\n\n" + "\n".join(links_to_add)
                final_text += "\n⚠️ *Tip:* If asked to login, tap 'Open in Chrome'."

            await context.bot.send_message(chat_id=update.effective_chat.id, text=final_text, parse_mode='Markdown')

    except Exception as e:
        print(f"Error: {e}")
        # Optional: Send error to user (disable in production if noisy)
        # await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ System Busy. Try again.")

if __name__ == '__main__':
    keep_alive() # Starts the Fake Web Server for Render
    print("🤖 Bot is initializing...")
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 Bot is RUNNING!")
    app_bot.run_polling()