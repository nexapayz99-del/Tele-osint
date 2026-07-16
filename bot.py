#!/usr/bin/env python3
"""
Telegram OSINT Bot - Search mobile number information
"""
import logging
import sys
import requests
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)

from config import Config
from database import Database

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Initialize database
try:
    db = Database()
except Exception as e:
    logger.error(f"Failed to connect to database: {e}")
    sys.exit(1)

# Conversation states
SEARCH = 1

# ============ Helper Functions ============

def format_result(number, data):
    """Format API response for display"""
    text = f"""
📱 **Mobile Number OSINT Report**
━━━━━━━━━━━━━━━━━━━━━

🔢 **Number:** `{number}`

"""
    if isinstance(data, dict):
        for key, value in data.items():
            if value:
                key_name = key.replace('_', ' ').title()
                if isinstance(value, str) and len(value) > 100:
                    value = value[:100] + '...'
                text += f"**{key_name}:** {value}\n"
    else:
        text += f"**Data:** {data}\n"
    
    text += f"""
━━━━━━━━━━━━━━━━━━━━━
📅 Searched: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return text

def validate_number(number):
    """Validate mobile number"""
    # Remove any non-digit characters
    number = re.sub(r'\D', '', number)
    # Check if it's a valid number (at least 5 digits)
    if len(number) >= 5 and number.isdigit():
        return number
    return None

# ============ User Commands ============

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return
    
    db.register_user(user.id, user.username, user.first_name)
    db.log_action(user.id, 'start')
    
    welcome = f"""
👋 **Welcome {user.first_name or 'User'}!**

I'm a mobile number OSINT bot. Send me a number and I'll fetch information.

📌 **Commands:**
• Send any number - Get OSINT info
• `/search [number]` - Search a number
• `/history` - View your search history
• `/stats` - Your usage statistics
• `/help` - Show this help

💡 **Example:** `/search 8490889926` or just send `8490889926`

Made with ❤️
"""
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    help_text = """
📚 **Help Menu**

**How to use:**
1. Send any mobile number (e.g., 8490889926)
2. Or use `/search 8490889926`

**Commands:**
• `/start` - Start the bot
• `/help` - Show this menu
• `/search [number]` - Search a number
• `/history` - View history
• `/stats` - Your stats

**Admin Commands:**
• `/admin` - Admin panel
• `/ban [user_id] [reason]` - Ban user
• `/unban [user_id]` - Unban user
• `/banned` - List banned users
• `/broadcast [message]` - Send to all

**Support:** Contact @owner
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    if context.args:
        number = context.args[0]
        await perform_search(update, context, number)
    else:
        await update.message.reply_text(
            "🔍 Please enter the mobile number:\n\n"
            "Example: `/search 8490889926`",
            parse_mode='Markdown'
        )
        return SEARCH

async def process_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process number from conversation"""
    number = update.message.text.strip()
    await perform_search(update, context, number)
    return ConversationHandler.END

async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE, number):
    """Perform the search"""
    user = update.effective_user
    
    # Validate number
    number = validate_number(number)
    if not number:
        await update.message.reply_text(
            "❌ Invalid number. Please enter a valid mobile number."
        )
        return
    
    # Send searching message
    msg = await update.message.reply_text(
        f"🔍 Searching for `{number}`...",
        parse_mode='Markdown'
    )
    
    try:
        # Call API
        api_url = f"{Config.API_URL}?api_id={Config.API_ID}&num={number}"
        logger.info(f"API Request: {api_url}")
        
        response = requests.get(api_url, timeout=30)
        
        if response.status_code == 200:
            try:
                data = response.json()
            except:
                data = {'response': response.text}
            
            # Format and display result
            result_text = format_result(number, data)
            await msg.edit_text(result_text, parse_mode='Markdown')
            
            # Save to database
            db.save_search(user.id, number, data)
            db.log_action(user.id, 'search', f'Number: {number}')
            
            # Add inline buttons
            keyboard = [
                [
                    InlineKeyboardButton("📋 Copy", callback_data=f"copy_{number}"),
                    InlineKeyboardButton("🔄 New", callback_data="new_search")
                ],
                [InlineKeyboardButton("📊 History", callback_data="view_history")]
            ]
            await msg.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif response.status_code == 404:
            await msg.edit_text(f"❌ Number `{number}` not found.", parse_mode='Markdown')
        else:
            await msg.edit_text(f"❌ API Error: {response.status_code}")
            
    except requests.exceptions.Timeout:
        await msg.edit_text("⏰ Request timed out. Please try again.")
    except requests.exceptions.ConnectionError:
        await msg.edit_text("🔌 Connection error. Please try again.")
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("❌ An error occurred. Please try again.")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /history"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    history = db.get_history(user.id, 20)
    
    if not history:
        await update.message.reply_text("📭 No search history found.")
        return
    
    text = "📚 **Your Search History**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, item in enumerate(history, 1):
        timestamp = item['timestamp'].strftime('%Y-%m-%d %H:%M')
        text += f"**{i}.** `{item['number']}`\n   📅 {timestamp}\n\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    user_data = db.users.find_one({'user_id': user.id})
    
    if not user_data:
        await update.message.reply_text("No data found.")
        return
    
    text = f"""
📊 **Your Statistics**
━━━━━━━━━━━━━━━━━━━━━

👤 **User:** {user_data.get('first_name', 'Unknown')}
🆔 **ID:** `{user.id}`
📅 **Joined:** {user_data.get('joined', datetime.now()).strftime('%Y-%m-%d')}
🔍 **Searches:** {user_data.get('searches', 0)}
⏰ **Last Active:** {user_data.get('last_active', datetime.now()).strftime('%Y-%m-%d %H:%M')}
"""
    await update.message.reply_text(text, parse_mode='Markdown')

# ============ Admin Commands ============

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin"""
    user = update.effective_user
    
    if user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    stats = db.get_stats()
    
    text = f"""
🔐 **Admin Panel**
━━━━━━━━━━━━━━━━━━━━━

📊 **Bot Statistics:**
• **Users:** {stats['users']}
• **Searches:** {stats['searches']}
• **Banned:** {stats['banned']}
• **Today:** {stats['today']}

👑 **Owner:** `{Config.OWNER_ID}`

**Commands:**
• `/ban [user_id] [reason]` - Ban
• `/unban [user_id]` - Unban
• `/banned` - List banned
• `/broadcast [msg]` - Broadcast
"""
    await update.message.reply_text(text, parse_mode='Markdown')

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ban"""
    user = update.effective_user
    
    if user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/ban [user_id] [reason]`", parse_mode='Markdown')
        return
    
    try:
        user_id = int(context.args[0])
        reason = ' '.join(context.args[1:]) or 'No reason'
        
        if db.is_banned(user_id):
            await update.message.reply_text(f"ℹ️ User `{user_id}` already banned.", parse_mode='Markdown')
            return
        
        db.ban_user(user_id, reason, user.id)
        db.log_action(user.id, 'ban', f'User: {user_id}, Reason: {reason}')
        
        await update.message.reply_text(
            f"✅ User `{user_id}` banned.\n**Reason:** {reason}",
            parse_mode='Markdown'
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unban"""
    user = update.effective_user
    
    if user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/unban [user_id]`", parse_mode='Markdown')
        return
    
    try:
        user_id = int(context.args[0])
        
        if not db.is_banned(user_id):
            await update.message.reply_text(f"ℹ️ User `{user_id}` not banned.", parse_mode='Markdown')
            return
        
        db.unban_user(user_id)
        db.log_action(user.id, 'unban', f'User: {user_id}')
        
        await update.message.reply_text(f"✅ User `{user_id}` unbanned.", parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def banned_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /banned"""
    user = update.effective_user
    
    if user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    banned = db.get_banned()
    
    if not banned:
        await update.message.reply_text("✅ No banned users.")
        return
    
    text = "🚫 **Banned Users**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, b in enumerate(banned, 1):
        text += f"**{i}.** User: `{b['user_id']}`\n"
        text += f"   Reason: {b.get('reason', 'N/A')}\n"
        text += f"   At: {b['banned_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /broadcast"""
    user = update.effective_user
    
    if user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast [message]`", parse_mode='Markdown')
        return
    
    message = ' '.join(context.args)
    sent = 0
    failed = 0
    
    await update.message.reply_text("📢 Sending broadcast...")
    
    for user_data in db.users.find({}):
        try:
            if not user_data.get('banned', False):
                await context.bot.send_message(
                    chat_id=user_data['user_id'],
                    text=f"📢 **Broadcast**\n\n{message}",
                    parse_mode='Markdown'
                )
                sent += 1
        except Exception as e:
            logger.error(f"Broadcast failed to {user_data['user_id']}: {e}")
            failed += 1
    
    await update.message.reply_text(
        f"✅ Broadcast sent!\n**Sent:** {sent}\n**Failed:** {failed}"
    )

# ============ Message Handlers ============

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle normal messages"""
    user = update.effective_user
    
    if db.is_banned(user.id):
        await update.message.reply_text("🚫 You are banned.")
        return
    
    text = update.message.text.strip()
    
    # If message is a number, search it
    if text.isdigit() and len(text) >= 5:
        await perform_search(update, context, text)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline buttons"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('copy_'):
        number = data.split('_')[1]
        await query.message.reply_text(f"📋 Number: `{number}`", parse_mode='Markdown')
    elif data == 'new_search':
        await query.message.reply_text("🔍 Send me a mobile number:")
    elif data == 'view_history':
        await history_command(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ============ Main ============

def main():
    """Start the bot"""
    if not Config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set in .env")
        sys.exit(1)
    
    logger.info("🚀 Starting OSINT Bot...")
    logger.info(f"👑 Owner: {Config.OWNER_ID}")
    logger.info(f"📡 API: {Config.API_URL}")
    
    # Create application
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('search', search_command))
    app.add_handler(CommandHandler('history', history_command))
    app.add_handler(CommandHandler('stats', stats_command))
    
    # Admin handlers
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(CommandHandler('ban', ban_command))
    app.add_handler(CommandHandler('unban', unban_command))
    app.add_handler(CommandHandler('banned', banned_list))
    app.add_handler(CommandHandler('broadcast', broadcast_command))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Conversation handler
    conv = ConversationHandler(
        entry_points=[CommandHandler('search', search_command)],
        states={SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_number)]},
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(conv)
    
    # Start
    logger.info("✅ Bot is running!")
    app.run_polling()

if __name__ == '__main__':
    main()