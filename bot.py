cd ~/Tele-osint

# Backup existing bot.py if it exists
mv bot.py bot.py.backup 2>/dev/null

# Create the new bot.py
cat > bot.py << 'EOF'
#!/usr/bin/env python3
"""
Telegram OSINT Bot - Search user information via API
"""
import asyncio
import logging
import os
import sys
import json
import requests
from datetime import datetime
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
DATABASE_NAME = os.getenv("DATABASE_NAME", "telegram_bot_db")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

if OWNER_ID and OWNER_ID not in ADMIN_IDS:
    ADMIN_IDS.append(OWNER_ID)

API_URL = "http://techspy.site.je/api/index.php"
API_ID = "api_812154f4"

# Conversation states
SEARCH_QUERY = 1

# MongoDB Connection
try:
    client = MongoClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    users_collection = db["users"]
    searches_collection = db["searches"]
    banned_collection = db["banned"]
    logs_collection = db["logs"]
    
    # Create indexes
    users_collection.create_index("user_id", unique=True)
    banned_collection.create_index("user_id", unique=True)
    searches_collection.create_index([("user_id", 1), ("timestamp", -1)])
    
    logger.info("✅ MongoDB connected successfully")
except Exception as e:
    logger.error(f"❌ MongoDB connection failed: {e}")
    sys.exit(1)

# ==================== DATABASE FUNCTIONS ====================

def register_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    """Register a new user or update existing"""
    try:
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "last_active": datetime.now(),
                },
                "$setOnInsert": {
                    "joined_date": datetime.now(),
                    "total_searches": 0,
                    "is_banned": False,
                },
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"Error registering user: {e}")
        return False

def is_banned(user_id: int) -> bool:
    """Check if user is banned"""
    try:
        return banned_collection.find_one({"user_id": user_id}) is not None
    except Exception:
        return False

def ban_user(user_id: int, reason: str = None, admin_id: int = None):
    """Ban a user"""
    try:
        banned_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "reason": reason or "No reason provided",
                    "banned_by": admin_id,
                    "banned_at": datetime.now(),
                }
            },
            upsert=True,
        )
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"is_banned": True}}
        )
        return True
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return False

def unban_user(user_id: int):
    """Unban a user"""
    try:
        banned_collection.delete_one({"user_id": user_id})
        users_collection.update_one(
            {"user_id": user_id},
            {"$set": {"is_banned": False}}
        )
        return True
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        return False

def get_banned_list(limit: int = 100):
    """Get list of banned users"""
    try:
        return list(banned_collection.find().limit(limit))
    except Exception:
        return []

def save_search(user_id: int, query: str, result: Any):
    """Save search history"""
    try:
        searches_collection.insert_one({
            "user_id": user_id,
            "query": query,
            "result": result,
            "timestamp": datetime.now(),
        })
        users_collection.update_one(
            {"user_id": user_id},
            {"$inc": {"total_searches": 1}}
        )
        return True
    except Exception as e:
        logger.error(f"Error saving search: {e}")
        return False

def get_search_history(user_id: int, limit: int = 10):
    """Get user's search history"""
    try:
        return list(searches_collection.find(
            {"user_id": user_id}
        ).sort("timestamp", -1).limit(limit))
    except Exception:
        return []

def get_user_stats(user_id: int):
    """Get user statistics"""
    try:
        return users_collection.find_one({"user_id": user_id})
    except Exception:
        return None

def get_bot_stats():
    """Get bot statistics"""
    try:
        return {
            "total_users": users_collection.count_documents({}),
            "total_searches": searches_collection.count_documents({}),
            "banned_users": banned_collection.count_documents({}),
            "active_today": users_collection.count_documents({
                "last_active": {
                    "$gte": datetime.now().replace(hour=0, minute=0, second=0)
                }
            }),
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {"total_users": 0, "total_searches": 0, "banned_users": 0, "active_today": 0}

def log_action(user_id: int, action: str, details: str = None):
    """Log user action"""
    try:
        logs_collection.insert_one({
            "user_id": user_id,
            "action": action,
            "details": details,
            "timestamp": datetime.now(),
        })
    except Exception as e:
        logger.error(f"Error logging action: {e}")

# ==================== BOT COMMANDS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    logger.info(f"Start command from user: {user.id} ({user.username})")
    
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    register_user(user.id, user.username, user.first_name, user.last_name)
    log_action(user.id, "start", "User started the bot")
    
    welcome_text = f"""
👋 **Welcome {user.first_name or 'User'}!**

I'm a user information lookup bot. I can find information about any user ID.

📌 **Commands:**
• `/search [user_id]` - Search for user information
• `/history` - View your search history  
• `/stats` - View your usage statistics
• `/help` - Show this help message

💡 **Example:** `/search 123456789`

Made with ❤️
"""
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    user = update.effective_user
    
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    help_text = """
📚 **Help Menu**

**Basic Commands:**
• `/start` - Start the bot
• `/help` - Show this help menu
• `/search [user_id]` - Search for user information
• `/history` - View your search history
• `/stats` - View your usage statistics

**How to Search:**
Type `/search 123456789` (replace with actual user ID)

**Admin Commands:**
• `/admin` - Open admin panel
• `/ban [user_id] [reason]` - Ban a user
• `/unban [user_id]` - Unban a user
• `/bannedlist` - View banned users
• `/broadcast [message]` - Send message to all users
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search command"""
    user = update.effective_user
    
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    if context.args:
        user_id = context.args[0]
        await perform_search(update, context, user_id)
    else:
        await update.message.reply_text(
            "🔍 Please enter the user ID you want to search:\n\n"
            "Example: `/search 123456789`",
            parse_mode="Markdown"
        )
        return SEARCH_QUERY

async def process_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process search input from conversation"""
    user_id = update.message.text.strip()
    await perform_search(update, context, user_id)
    return ConversationHandler.END

async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str):
    """Perform the actual search"""
    user = update.effective_user
    
    # Validate user ID
    if not user_id.isdigit():
        await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric ID.")
        return
    
    # Send searching message
    msg = await update.message.reply_text(f"🔍 Searching for user ID: `{user_id}`...", parse_mode="Markdown")
    
    try:
        # Call the API
        api_url = f"{API_URL}?api_id={API_ID}&num={user_id}"
        logger.info(f"Calling API: {api_url}")
        
        response = requests.get(api_url, timeout=30)
        
        if response.status_code == 200:
            try:
                data = response.json()
            except:
                data = {"response": response.text}
            
            # Format result
            result_text = f"""
🎯 **User Information**
━━━━━━━━━━━━━━━━━━━━━

📱 **User ID:** `{user_id}`

"""
            if isinstance(data, dict):
                for key, value in data.items():
                    if value:
                        key_name = key.replace("_", " ").title()
                        if isinstance(value, str) and len(value) > 100:
                            value = value[:100] + "..."
                        result_text += f"**{key_name}:** {value}\n"
            else:
                result_text += f"**Data:** {data}\n"
            
            result_text += f"""
━━━━━━━━━━━━━━━━━━━━━
📅 Searched: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            
            # Save to database
            save_search(user.id, user_id, data)
            log_action(user.id, "search", f"Searched user: {user_id}")
            
            await msg.edit_text(result_text, parse_mode="Markdown")
            
            # Add inline buttons
            keyboard = [
                [
                    InlineKeyboardButton("📋 Copy ID", callback_data=f"copy_{user_id}"),
                    InlineKeyboardButton("🔄 New Search", callback_data="new_search")
                ],
                [InlineKeyboardButton("📊 View History", callback_data="view_history")]
            ]
            await msg.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            
        elif response.status_code == 404:
            await msg.edit_text(f"❌ User ID `{user_id}` not found.", parse_mode="Markdown")
        else:
            await msg.edit_text(f"❌ API Error (Status: {response.status_code})")
            
    except requests.exceptions.Timeout:
        await msg.edit_text("⏰ Request timed out. Please try again.")
    except requests.exceptions.ConnectionError:
        await msg.edit_text("🔌 Connection error. Please try again.")
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("❌ An unexpected error occurred.")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history command"""
    user = update.effective_user
    
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    history = get_search_history(user.id, limit=20)
    
    if not history:
        await update.message.reply_text("📭 You haven't performed any searches yet.")
        return
    
    text = "📚 **Your Search History**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, entry in enumerate(history, 1):
        timestamp = entry["timestamp"].strftime("%Y-%m-%d %H:%M")
        text += f"**{i}.** User ID: `{entry['query']}`\n   📅 {timestamp}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command"""
    user = update.effective_user
    
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    user_data = get_user_stats(user.id)
    
    if not user_data:
        await update.message.reply_text("No data found.")
        return
    
    text = f"""
📊 **Your Statistics**
━━━━━━━━━━━━━━━━━━━━━

👤 **User:** {user_data.get('first_name', 'Unknown')}
🆔 **ID:** `{user.id}`
📅 **Joined:** {user_data.get('joined_date', datetime.now()).strftime('%Y-%m-%d')}
🔍 **Total Searches:** {user_data.get('total_searches', 0)}
⏰ **Last Active:** {user_data.get('last_active', datetime.now()).strftime('%Y-%m-%d %H:%M')}
"""
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== ADMIN COMMANDS ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    stats = get_bot_stats()
    
    text = f"""
🔐 **Admin Panel**
━━━━━━━━━━━━━━━━━━━━━

📊 **Bot Statistics:**
• **Total Users:** {stats['total_users']}
• **Total Searches:** {stats['total_searches']}
• **Banned Users:** {stats['banned_users']}
• **Active Today:** {stats['active_today']}

👑 **Owner ID:** `{OWNER_ID}`

**Admin Commands:**
• `/ban [user_id] [reason]` - Ban a user
• `/unban [user_id]` - Unban a user
• `/bannedlist` - View banned users
• `/broadcast [message]` - Send message to all users
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ban command"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/ban [user_id] [reason]`", parse_mode="Markdown")
        return
    
    try:
        user_id = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason"
        
        if is_banned(user_id):
            await update.message.reply_text(f"ℹ️ User `{user_id}` is already banned.", parse_mode="Markdown")
            return
        
        ban_user(user_id, reason, user.id)
        log_action(user.id, "ban", f"Banned: {user_id}, Reason: {reason}")
        
        await update.message.reply_text(f"✅ User `{user_id}` banned.\n**Reason:** {reason}", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unban command"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/unban [user_id]`", parse_mode="Markdown")
        return
    
    try:
        user_id = int(context.args[0])
        
        if not is_banned(user_id):
            await update.message.reply_text(f"ℹ️ User `{user_id}` is not banned.", parse_mode="Markdown")
            return
        
        unban_user(user_id)
        log_action(user.id, "unban", f"Unbanned: {user_id}")
        
        await update.message.reply_text(f"✅ User `{user_id}` unbanned.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def banned_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bannedlist command"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    banned = get_banned_list()
    
    if not banned:
        await update.message.reply_text("✅ No banned users.")
        return
    
    text = "🚫 **Banned Users**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, b in enumerate(banned, 1):
        text += f"**{i}.** User: `{b['user_id']}`\n   Reason: {b.get('reason', 'N/A')}\n   At: {b['banned_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast command"""
    user = update.effective_user
    
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast [message]`", parse_mode="Markdown")
        return
    
    message = " ".join(context.args)
    sent = 0
    failed = 0
    
    await update.message.reply_text("📢 Sending broadcast...")
    
    for user_data in users_collection.find({}):
        try:
            if not user_data.get("is_banned", False):
                await context.bot.send_message(
                    chat_id=user_data["user_id"],
                    text=f"📢 **Broadcast**\n\n{message}",
                    parse_mode="Markdown"
                )
                sent += 1
        except Exception as e:
            logger.error(f"Broadcast failed to {user_data['user_id']}: {e}")
            failed += 1
    
    await update.message.reply_text(f"✅ Broadcast sent!\n**Sent:** {sent}\n**Failed:** {failed}")

# ==================== MESSAGE HANDLERS ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-command messages"""
    user = update.effective_user
    
    if is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 5:
        await perform_search(update, context, text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("copy_"):
        user_id = data.split("_")[1]
        await query.message.reply_text(f"📋 User ID: `{user_id}`", parse_mode="Markdown")
    elif data == "new_search":
        await query.message.reply_text("🔍 Enter user ID:")
    elif data == "view_history":
        await history_command(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ==================== MAIN ====================

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set in .env")
        sys.exit(1)
    
    if not MONGODB_URI:
        logger.error("❌ MONGODB_URI not set in .env")
        sys.exit(1)
    
    logger.info("🚀 Starting Telegram OSINT Bot...")
    logger.info(f"👑 Owner ID: {OWNER_ID}")
    logger.info(f"👥 Admin IDs: {ADMIN_IDS}")
    logger.info(f"📡 API URL: {API_URL}")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("bannedlist", banned_list_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("search", search_command)],
        states={SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_search_input)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    
    # Start bot
    logger.info("✅ Bot is running! Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
EOF