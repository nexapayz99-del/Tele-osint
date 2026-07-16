import requests
import logging
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
from config import Config
from database import db

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
SEARCH_QUERY = 1
BAN_USER = 2
UNBAN_USER = 3

class Bot:
    def __init__(self):
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        self.setup_handlers()

    def setup_handlers(self):
        """Setup all command handlers"""
        # User commands
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("search", self.search_command))
        self.application.add_handler(CommandHandler("history", self.history_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        
        # Owner/Admin commands
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        self.application.add_handler(CommandHandler("ban", self.ban_command))
        self.application.add_handler(CommandHandler("unban", self.unban_command))
        self.application.add_handler(CommandHandler("bannedlist", self.banned_list))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        
        # Message handler
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            self.handle_message
        ))
        
        # Conversation handlers
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('search', self.search_command)],
            states={
                SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.process_search)],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        self.application.add_handler(conv_handler)

    # ============ USER COMMANDS ============
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Check if user is banned
        if db.is_user_banned(user.id):
            await update.message.reply_text(
                "🚫 You are banned from using this bot.\n"
                "Contact the owner for more information."
            )
            return
        
        # Register user
        db.add_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )
        db.add_log(user.id, "start", "User started the bot")
        
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

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user = update.effective_user
        
        if db.is_user_banned(user.id):
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

**Need Help?**
Contact the bot owner for support.
"""
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /search command"""
        user = update.effective_user
        
        if db.is_user_banned(user.id):
            await update.message.reply_text("🚫 You are banned from using this bot.")
            return
        
        db.update_user_activity(user.id)
        
        # Check if user ID is provided in command
        if context.args:
            user_id = context.args[0]
            await self.perform_search(update, context, user_id)
        else:
            await update.message.reply_text(
                "🔍 Please enter the user ID you want to search for:\n\n"
                "Example: `/search 123456789`\n"
                "Or send the ID as a message.",
                parse_mode='Markdown'
            )
            return SEARCH_QUERY

    async def process_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process search query from message"""
        user_id = update.message.text.strip()
        await self.perform_search(update, context, user_id)
        return ConversationHandler.END

    async def perform_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
        """Perform the actual search"""
        user = update.effective_user
        
        # Validate user ID
        if not user_id.isdigit():
            await update.message.reply_text(
                "❌ Invalid user ID. Please enter a valid numeric ID."
            )
            return
        
        # Send searching message
        msg = await update.message.reply_text(
            f"🔍 Searching for user ID: `{user_id}`...",
            parse_mode='Markdown'
        )
        
        try:
            # Call the API
            api_url = f"{Config.API_URL}?api_id={Config.API_ID}&num={user_id}"
            response = requests.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # Format and display the result
                result_text = self.format_search_result(data, user_id)
                
                # Save search history
                db.add_search(user.id, user_id, data)
                db.add_log(user.id, "search", f"Searched user: {user_id}")
                
                # Edit the message with results
                await msg.edit_text(result_text, parse_mode='Markdown')
                
                # Add inline buttons
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
                await msg.edit_text(
                    f"❌ User ID `{user_id}` not found in the database.\n\n"
                    "Please verify the ID and try again.",
                    parse_mode='Markdown'
                )
            else:
                await msg.edit_text(
                    f"❌ API Error (Status: {response.status_code})\n"
                    "Please try again later or contact the owner."
                )
                
        except requests.exceptions.Timeout:
            await msg.edit_text("⏰ Request timed out. Please try again later.")
        except requests.exceptions.ConnectionError:
            await msg.edit_text("🔌 Connection error. Please check your internet and try again.")
        except json.JSONDecodeError:
            await msg.edit_text("❌ Invalid response from API. Please try again later.")
        except Exception as e:
            logger.error(f"Search error: {e}")
            await msg.edit_text("❌ An unexpected error occurred. Please try again.")

    def format_search_result(self, data, user_id):
        """Format the search result for display"""
        result_text = f"""
🎯 **User Information**
━━━━━━━━━━━━━━━━━━━━━

📱 **User ID:** `{user_id}`

"""
        
        if isinstance(data, dict):
            for key, value in data.items():
                if value:
                    # Format key name
                    key_name = key.replace('_', ' ').title()
                    # Truncate long values
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:100] + "..."
                    result_text += f"**{key_name}:** {value}\n"
        else:
            result_text += f"**Data:** {data}\n"
        
        result_text += """
━━━━━━━━━━━━━━━━━━━━━
📅 Searched at: """ + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return result_text

    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /history command"""
        user = update.effective_user
        
        if db.is_user_banned(user.id):
            await update.message.reply_text("🚫 You are banned from using this bot.")
            return
        
        history = db.get_user_history(user.id, limit=20)
        
        if not history:
            await update.message.reply_text(
                "📭 You haven't performed any searches yet.\n"
                "Start searching with `/search [user_id]`",
                parse_mode='Markdown'
            )
            return
        
        history_text = "📚 **Your Search History**\n"
        history_text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for i, entry in enumerate(history, 1):
            timestamp = entry['timestamp'].strftime("%Y-%m-%d %H:%M")
            history_text += f"**{i}.** User ID: `{entry['query']}`\n"
            history_text += f"   📅 {timestamp}\n\n"
        
        await update.message.reply_text(history_text, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user = update.effective_user
        
        if db.is_user_banned(user.id):
            await update.message.reply_text("🚫 You are banned from using this bot.")
            return
        
        user_data = db.get_user(user.id)
        
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

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel conversation"""
        await update.message.reply_text("Operation cancelled.")
        return ConversationHandler.END

    # ============ ADMIN/OWNER COMMANDS ============
    
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Open admin panel"""
        user = update.effective_user
        
        if user.id not in Config.ADMIN_IDS:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        
        stats = db.get_stats()
        
        panel_text = f"""
🔐 **Admin Panel**
━━━━━━━━━━━━━━━━━━━━━

📊 **Bot Statistics:**
• **Total Users:** {stats['total_users']}
• **Total Searches:** {stats['total_searches']}
• **Banned Users:** {stats['banned_users']}
• **Active Today:** {stats['active_today']}

👑 **Owner ID:** `{Config.OWNER_ID}`

**Available Admin Commands:**
• `/ban [user_id] [reason]` - Ban a user
• `/unban [user_id]` - Unban a user
• `/bannedlist` - View banned users
• `/broadcast [message]` - Send message to all users
• `/admin` - Show this panel
"""
        keyboard = [
            [
                InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
                InlineKeyboardButton("📋 Banned List", callback_data="admin_banned")
            ],
            [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(panel_text, parse_mode='Markdown', reply_markup=reply_markup)

    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Ban a user"""
        user = update.effective_user
        
        if user.id not in Config.ADMIN_IDS:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage: `/ban [user_id] [reason]`\n"
                "Example: `/ban 123456789 Spamming`",
                parse_mode='Markdown'
            )
            return
        
        try:
            user_id = int(context.args[0])
            reason = ' '.join(context.args[1:]) if len(context.args) > 1 else 'No reason provided'
            
            if db.is_user_banned(user_id):
                await update.message.reply_text(f"ℹ️ User `{user_id}` is already banned.", parse_mode='Markdown')
                return
            
            db.ban_user(user_id, reason, user.id)
            db.add_log(user.id, "ban", f"Banned user: {user_id}, Reason: {reason}")
            
            await update.message.reply_text(
                f"✅ User `{user_id}` has been banned.\n"
                f"**Reason:** {reason}",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric ID.")

    async def unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unban a user"""
        user = update.effective_user
        
        if user.id not in Config.ADMIN_IDS:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage: `/unban [user_id]`\n"
                "Example: `/unban 123456789`",
                parse_mode='Markdown'
            )
            return
        
        try:
            user_id = int(context.args[0])
            
            if not db.is_user_banned(user_id):
                await update.message.reply_text(f"ℹ️ User `{user_id}` is not banned.", parse_mode='Markdown')
                return
            
            db.unban_user(user_id)
            db.add_log(user.id, "unban", f"Unbanned user: {user_id}")
            
            await update.message.reply_text(
                f"✅ User `{user_id}` has been unbanned.",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric ID.")

    async def banned_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View banned users"""
        user = update.effective_user
        
        if user.id not in Config.ADMIN_IDS:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        
        banned_users = db.get_banned_users()
        
        if not banned_users:
            await update.message.reply_text("✅ No banned users.")
            return
        
        text = "🚫 **Banned Users List**\n"
        text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for i, banned in enumerate(banned_users, 1):
            text += f"**{i}.** User ID: `{banned['user_id']}`\n"
            text += f"   **Reason:** {banned.get('reason', 'N/A')}\n"
            text += f"   **Banned at:** {banned['banned_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send broadcast message to all users"""
        user = update.effective_user
        
        if user.id not in Config.ADMIN_IDS:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage: `/broadcast [message]`\n"
                "Example: `/broadcast Hello everyone!`",
                parse_mode='Markdown'
            )
            return
        
        message = ' '.join(context.args)
        sent_count = 0
        failed_count = 0
        
        await update.message.reply_text("📢 Sending broadcast message...")
        
        # Get all users
        users = db.users.find({})
        
        for user_data in users:
            try:
                if not user_data.get('is_banned', False):
                    await self.application.bot.send_message(
                        chat_id=user_data['user_id'],
                        text=f"📢 **Broadcast Message**\n\n{message}",
                        parse_mode='Markdown'
                    )
                    sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send broadcast to {user_data['user_id']}: {e}")
                failed_count += 1
        
        await update.message.reply_text(
            f"✅ Broadcast completed!\n"
            f"**Sent:** {sent_count}\n"
            f"**Failed:** {failed_count}"
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle non-command messages"""
        user = update.effective_user
        
        if db.is_user_banned(user.id):
            await update.message.reply_text("🚫 You are banned from using this bot.")
            return
        
        # Check if message is a user ID (numeric)
        text = update.message.text.strip()
        if text.isdigit() and len(text) >= 5:
            await self.perform_search(update, context, text)

    # ============ BUTTON CALLBACKS ============
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("copy_"):
            user_id = data.split("_")[1]
            await query.message.reply_text(f"📋 User ID: `{user_id}`", parse_mode='Markdown')
        
        elif data == "new_search":
            await query.message.reply_text(
                "🔍 Please enter the user ID you want to search:"
            )
        
        elif data == "view_history":
            await self.history_command(update, context)
        
        elif data == "admin_stats":
            stats = db.get_stats()
            text = f"""
📊 **Bot Statistics**
━━━━━━━━━━━━━━━━━━━━━

👥 **Total Users:** {stats['total_users']}
🔍 **Total Searches:** {stats['total_searches']}
🚫 **Banned Users:** {stats['banned_users']}
✅ **Active Today:** {stats['active_today']}
"""
            await query.message.reply_text(text, parse_mode='Markdown')
        
        elif data == "admin_banned":
            await self.banned_list(update, context)
        
        elif data == "admin_broadcast":
            await query.message.reply_text(
                "📢 Please send the broadcast message using:\n"
                "`/broadcast [your message]`",
                parse_mode='Markdown'
            )

    # ============ RUN BOT ============
    
    def run(self):
        """Run the bot"""
        logger.info("Starting bot...")
        self.application.run_polling()

if __name__ == '__main__':
    bot = Bot()
    bot.run()
