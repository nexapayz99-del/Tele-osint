import os
import logging
import aiohttp
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# 1. Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 2. Load Environment Variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE_NAME = os.getenv("DATABASE_NAME")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")

# 3. Initialize Database and Pyrogram Client
db_client = AsyncIOMotorClient(MONGODB_URI)
db = db_client[DATABASE_NAME]
search_logs = db["search_logs"]

app = Client(
    "search_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN
)

# Placeholder for your target API endpoint
API_ENDPOINT = "https://api.example.com/lookup?num={}"


# --- BOT HANDLERS ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Handles the /start command and sends the main menu buttons."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Search Number", callback_data="btn_search")],
        [
            InlineKeyboardButton("ℹ️ Help", callback_data="btn_help"),
            InlineKeyboardButton("👨‍💻 Owner", url=f"tg://user?id={OWNER_ID}")
        ]
    ])
    
    await message.reply_text(
        "👋 **Welcome to the OSINT Number Lookup Bot!**\n\n"
        "Use the buttons below to navigate, or simply send a mobile number to begin.",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def button_handler(client: Client, query: CallbackQuery):
    """Handles button clicks from the inline keyboard."""
    if query.data == "btn_search":
        await query.answer("Just type the mobile number directly in this chat!", show_alert=True)
    elif query.data == "btn_help":
        await query.edit_message_text(
            "🛠 **How to use:**\n\n"
            "1. Send a valid mobile number (digits only).\n"
            "2. The bot will query the database/API.\n"
            "3. Results will be sent directly to you.\n\n"
            "Press /start to return to the main menu."
        )

@app.on_message(filters.private & filters.text & ~filters.command(["start"]))
async def lookup_number(client: Client, message: Message):
    """Processes text messages as phone numbers, logs them to MongoDB, and fetches data."""
    phone_number = message.text.strip()
    user_id = message.from_user.id
    username = message.from_user.username or "Unknown"
    
    if not phone_number.isdigit():
        await message.reply_text("⚠️ Please enter a valid mobile number (numbers only).")
        return
        
    status_msg = await message.reply_text("🔍 *Searching records...*")
    
    # Log the search attempt to MongoDB
    try:
        await search_logs.insert_one({
            "user_id": user_id,
            "username": username,
            "phone_number": phone_number,
            "status": "pending"
        })
    except Exception as e:
        logger.error(f"Database logging error: {e}")

    # Fetch data from the external API
    async with aiohttp.ClientSession() as session:
        try:
            target_url = API_ENDPOINT.format(phone_number)
            async with session.get(target_url) as response:
                if response.status == 200:
                    raw_text = await response.text()
                    formatted_response = f"📋 **Search Results for {phone_number}:**\n\n{raw_text}"
                    await status_msg.edit_text(formatted_response)
                    
                    # Update DB log as successful
                    await search_logs.update_one(
                        {"user_id": user_id, "phone_number": phone_number, "status": "pending"},
                        {"$set": {"status": "success"}}
                    )
                else:
                    await status_msg.edit_text(f"❌ API connection failed. Status: {response.status}")
                    
        except Exception as e:
            logger.error(f"API request error: {e}")
            await status_msg.edit_text("❌ An error occurred while communicating with the server.")


if __name__ == "__main__":
    logger.info("Bot is starting...")
    app.run()
