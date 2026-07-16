import requests
import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
from dotenv import load_dotenv
from pymongo import MongoClient

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'telegram_bot_db')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
if OWNER_ID not in ADMIN_IDS and OWNER_ID != 0:
    ADMIN_IDS.append(OWNER_ID)

API_URL = 'http://techspy.site.je/api/index.php'
API_ID = 'api_812154f4'

# Database connection
try:
    client = MongoClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    users_collection = db['users']
    search_history = db['search_history']
    banned_users = db['banned_users']
    logs = db['logs']
    
    # Create indexes
    users_collection.create_index('user_id', unique=True)
    banned_users.create_index('user_id', unique=True)
    search_history.create_index([('user_id', 1), ('timestamp', -1)])
    
    logger.info("MongoDB connected successfully")
except Exception as e:
    logger.error(f"MongoDB connection error: {e}")
    db = None

# Conversation states
SEARCH_QUERY = 1

# Database functions
def add_user(user_id, username=None, first_name=None, last_name=None):
    if db is None:
        return False
    try:
        user_data = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'joined_date': datetime.now(),
            'last_active': datetime.now(),
            'total_searches': 0,
            'is_banned': False
        }
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': user_data},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        return False

def is_user_banned(user_id):
    if db is None:
        return False
    return banned_users.find_one({'user_id': user_id}) is not None

def ban_user(user_id, reason=None, admin_id=None):
    if db is None:
        return False
    try:
        ban_data = {
            'user_id': user_id,
            'reason': reason or 'No reason provided',
            'banned_by': admin_id,
            'banned_at': datetime.now()
        }
        banned_users.update_one(
            {'user_id': user_id},
            {'$set': ban_data},
            upsert=True
        )
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'is_banned': True}}
        )
        return True
    except Exception as e:
        logger.error(f"Error banning user: {e}")
        return False

def unban_user(user_id):
    if db is None:
        return False
    try:
        banned_users.delete_one({'user_id': user_id})
        users_collection.update_one(
            {'user_id': user_id},
            {'$set': {'is_banned': False}}
        )
        return True
    except Exception as e:
        logger.error(f"Error unbanning user: {e}")
        return False

def get_banned_users(limit=100):
    if db is None:
        return []
    return list(banned_users.find().limit(limit))

def add_search(user_id, search_query, result_data=None):
    if db is None:
        return False
    try:
        search_data = {
            'user_id': user_id,
            'query': search_query,
            'result': result_data,
            'timestamp': datetime.now()
        }
        search_history.insert_one(search_data)
        users_collection.update_one(
            {'user_id': user_id},
            {'$inc': {'total_searches': 1}}
        )
        return True
    except Exception as e:
        logger.error(f"Error adding search: {e}")
        return False

def get_user_history(user_id, limit=10):
    if db is None:
        return []
    return list(search_history.find(
        {'user_id': user_id}
    ).sort('timestamp', -1).limit(limit))

def get_user(user_id):
    if db is None:
        return None
    return users_collection.find_one({'user_id': user_id})

def get_stats():
    if db is None:
        return {'total_users': 0, 'total_searches': 0, 'banned_users': 0, 'active_today': 0}
    try:
        total_users = users_collection.count_documents({})
        total_searches = search_history.count_documents({})
        banned_count = banned_users.count_documents({})
        active_today = users_collection.count_documents({
            'last_active': {'$gte': datetime.now().replace(hour=0, minute=0, second=0)}
        })
        return {
            'total_users': total_users,
            'total_searches': total_searches,
            'banned_users': banned_count,
            'active_today': active_today
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {'total_users': 0, 'total_searches': 0, 'banned_users': 0, 'active_today': 0}

def add_log(user_id, action, details=None):
    if db is None:
        return False
    try:
        log_data = {
            'user_id': user_id,
            'action': action,
            'details': details,
            'timestamp': datetime.now()
        }
        logs.insert_one(log_data)
        return True
    except Exception as e:
        logger.error(f"Error adding log: {e}")
        return False

# Bot functions
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    add_user(user.id, user.username, user.first_name, user.last_name)
    add_log(user.id, "start", "User started the bot")
    
    welcome_text = f"""
👋 **Welcome {user.first_name}!**

I'm a user information lookup bot. Use me to find information about users.

**Commands:**
/search [user_id] - Search user information
/history - View your search history
/stats - View your usage statistics
/help - Show this help message

**How to use:**
Just type /search followed by the user ID you want to look up.

Example: `/search 123456789`

Made with ❤️
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
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
1. Type `/search 123456789` (replace with actual user ID)
2. Or type `/search` and then enter the user ID

**Admin Commands:**
• `/admin` - Open admin panel
• `/ban [user_id] [reason]` - Ban a user
• `/unban [user_id]` - Unban a user
• `/bannedlist` - View banned users
• `/broadcast [message]` - Send message to all users
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    if context.args:
        user_id = context.args[0]
        await perform_search(update, context, user_id)
    else:
        await update.message.reply_text(
            "🔍 Please enter the user ID you want to search for:\n\n"
            "Example: `/search 123456789`\n"
            "Or send the ID as a message.",
            parse_mode='Markdown'
        )
        return SEARCH_QUERY

async def process_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text.strip()
    await perform_search(update, context, user_id)
    return ConversationHandler.END

async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    user = update.effective_user
    
    if not user_id.isdigit():
        await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric ID.")
        return
    
    msg = await update.message.reply_text(f"🔍 Searching for user ID: `{user_id}`...", parse_mode='Markdown')
    
    try:
        api_url = f"{API_URL}?api_id={API_ID}&num={user_id}"
        response = requests.get(api_url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            result_text = f"""
🎯 **User Information**
━━━━━━━━━━━━━━━━━━━━━

📱 **User ID:** `{user_id}`

"""
            if isinstance(data, dict):
                for key, value in data.items():
                    if value:
                        key_name = key.replace('_', ' ').title()
                        if isinstance(value, str) and len(value) > 100:
                            value = value[:100] + "..."
                        result_text += f"**{key_name}:** {value}\n"
            else:
                result_text += f"**Data:** {data}\n"
            
            result_text += """
━━━━━━━━━━━━━━━━━━━━━
📅 Searched at: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            add_search(user.id, user_id, data)
            add_log(user.id, "search", f"Searched user: {user_id}")
            
            await msg.edit_text(result_text, parse_mode='Markdown')
            
            keyboard = [
                [
                    InlineKeyboardButton("📋 Copy ID", callback_data=f"copy_{user_id}"),
                    InlineKeyboardButton("🔄 New Search", callback_data="new_search")
                ],
                [InlineKeyboardButton("📊 View History", callback_data="view_history")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await msg.edit_reply_markup(reply_markup=reply_markup)
            
        elif response.status_code == 404:
            await msg.edit_text(f"❌ User ID `{user_id}` not found in the database.", parse_mode='Markdown')
        else:
            await msg.edit_text(f"❌ API Error (Status: {response.status_code})\nPlease try again later.")
            
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("❌ An unexpected error occurred. Please try again.")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    history = get_user_history(user.id, limit=20)
    
    if not history:
        await update.message.reply_text("📭 You haven't performed any searches yet.")
        return
    
    history_text = "📚 **Your Search History**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, entry in enumerate(history, 1):
        timestamp = entry['timestamp'].strftime("%Y-%m-%d %H:%M")
        history_text += f"**{i}.** User ID: `{entry['query']}`\n   📅 {timestamp}\n\n"
    
    await update.message.reply_text(history_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    user_data = get_user(user.id)
    if not user_data:
        await update.message.reply_text("No data found.")
        return
    
    stats_text = f"""
📊 **Your Statistics**
━━━━━━━━━━━━━━━━━━━━━

👤 **User:** {user_data.get('first_name', 'Unknown')}
🆔 **ID:** `{user.id}`
📅 **Joined:** {user_data.get('joined_date', datetime.now()).strftime('%Y-%m-%d')}
🔍 **Total Searches:** {user_data.get('total_searches', 0)}
⏰ **Last Active:** {user_data.get('last_active', datetime.now()).strftime('%Y-%m-%d %H:%M')}
"""
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS and user.id != OWNER_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    stats = get_stats()
    
    panel_text = f"""
🔐 **Admin Panel**
━━━━━━━━━━━━━━━━━━━━━

📊 **Bot Statistics:**
• **Total Users:** {stats['total_users']}
• **Total Searches:** {stats['total_searches']}
• **Banned Users:** {stats['banned_users']}
• **Active Today:** {stats['active_today']}

👑 **Owner ID:** `{OWNER_ID}`

**Available Admin Commands:**
• `/ban [user_id] [reason]` - Ban a user
• `/unban [user_id]` - Unban a user
• `/bannedlist` - View banned users
• `/broadcast [message]` - Send message to all users
"""
    await update.message.reply_text(panel_text, parse_mode='Markdown')

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS and user.id != OWNER_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/ban [user_id] [reason]`", parse_mode='Markdown')
        return
    
    try:
        user_id = int(context.args[0])
        reason = ' '.join(context.args[1:]) if len(context.args) > 1 else 'No reason provided'
        
        if is_user_banned(user_id):
            await update.message.reply_text(f"ℹ️ User `{user_id}` is already banned.", parse_mode='Markdown')
            return
        
        ban_user(user_id, reason, user.id)
        add_log(user.id, "ban", f"Banned user: {user_id}, Reason: {reason}")
        
        await update.message.reply_text(f"✅ User `{user_id}` has been banned.\n**Reason:** {reason}", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric ID.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS and user.id != OWNER_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/unban [user_id]`", parse_mode='Markdown')
        return
    
    try:
        user_id = int(context.args[0])
        
        if not is_user_banned(user_id):
            await update.message.reply_text(f"ℹ️ User `{user_id}` is not banned.", parse_mode='Markdown')
            return
        
        unban_user(user_id)
        add_log(user.id, "unban", f"Unbanned user: {user_id}")
        
        await update.message.reply_text(f"✅ User `{user_id}` has been unbanned.", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric ID.")

async def banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS and user.id != OWNER_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    banned_users_list = get_banned_users()
    
    if not banned_users_list:
        await update.message.reply_text("✅ No banned users.")
        return
    
    text = "🚫 **Banned Users List**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, banned in enumerate(banned_users_list, 1):
        text += f"**{i}.** User ID: `{banned['user_id']}`\n   **Reason:** {banned.get('reason', 'N/A')}\n   **Banned at:** {banned['banned_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id not in ADMIN_IDS and user.id != OWNER_ID:
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast [message]`", parse_mode='Markdown')
        return
    
    message = ' '.join(context.args)
    sent_count = 0
    failed_count = 0
    
    await update.message.reply_text("📢 Sending broadcast message...")
    
    all_users = users_collection.find({})
    
    for user_data in all_users:
        try:
            if not user_data.get('is_banned', False):
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=f"📢 **Broadcast Message**\n\n{message}",
                    parse_mode='Markdown'
                )
                sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_data['user_id']}: {e}")
            failed_count += 1
    
    await update.message.reply_text(
        f"✅ Broadcast completed!\n**Sent:** {sent_count}\n**Failed:** {failed_count}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    text = update.message.text.strip()
    if text.isdigit() and len(text) >= 5:
        await perform_search(update, context, text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("copy_"):
        user_id = data.split("_")[1]
        await query.message.reply_text(f"📋 User ID: `{user_id}`", parse_mode='Markdown')
    
    elif data == "new_search":
        await query.message.reply_text("🔍 Please enter the user ID you want to search:")
    
    elif data == "view_history":
        await history_command(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set in .env file")
        return
    
    if db is None:
        logger.error("Database connection failed. Please check MongoDB.")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # User commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Admin commands
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("bannedlist", banned_list))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('search', search_command)],
        states={
            SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_search)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(conv_handler)
    
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == '__main__':
    main()
EOF
