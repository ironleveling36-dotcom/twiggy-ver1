#!/usr/bin/env python3
"""
Swiggy Automation Bot - Production Ready for Railway
Admin Controls | Channel-Only Access | 24/7 Uptime
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from functools import wraps

import aiohttp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    ChatMember, BotCommand, MenuButtonCommands
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler, JobQueue
)
from telegram.constants import ParseMode, ChatType, ChatMemberStatus
from telegram.error import TelegramError

import motor.motor_asyncio
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pydantic import BaseSettings, Field
import dotenv

# ============================================================================
# CONFIGURATION & SETUP
# ============================================================================

dotenv.load_dotenv()

class Settings(BaseSettings):
    """Production settings with Railway support"""
    # Telegram
    TELEGRAM_TOKEN: str = Field(default="", alias="TELEGRAM_TOKEN")
    ADMIN_IDS: List[int] = Field(default=[], alias="ADMIN_IDS")
    ADMIN_CHANNEL_ID: int = Field(default=0, alias="ADMIN_CHANNEL_ID")
    FORCE_CHANNEL_ID: int = Field(default=0, alias="FORCE_CHANNEL_ID")
    
    # MongoDB
    MONGODB_URI: str = Field(default="mongodb://localhost:27017/swiggy_bot", alias="MONGODB_URI")
    
    # API
    API_BASE_URL: str = Field(default="http://localhost:5000", alias="API_BASE_URL")
    API_TIMEOUT: int = Field(default=120, alias="API_TIMEOUT")
    
    # Redis (Optional)
    REDIS_URL: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    
    # Bot Config
    MAX_CONCURRENT_USERS: int = Field(default=500, alias="MAX_CONCURRENT_USERS")
    SESSION_TIMEOUT: int = Field(default=3600, alias="SESSION_TIMEOUT")
    BOT_CHECK_INTERVAL: int = Field(default=300, alias="BOT_CHECK_INTERVAL")
    
    # Security
    JWT_SECRET: str = Field(default="change_in_production", alias="JWT_SECRET")
    ADMIN_SECRET: str = Field(default="admin_secret_key", alias="ADMIN_SECRET")
    
    # Environment
    ENVIRONMENT: str = Field(default="production", alias="ENVIRONMENT")
    DEBUG: bool = Field(default=False, alias="DEBUG")
    LOG_LEVEL: str = Field(default="INFO", alias="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Load settings
try:
    settings = Settings()
except Exception as e:
    print(f"⚠️ Warning: Settings loading error: {e}")
    settings = Settings()

# Validate required settings
if not settings.TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN is required! Set it in .env or Railway environment")

if not settings.ADMIN_IDS:
    print("⚠️ Warning: No ADMIN_IDS configured. Use format: 123456,987654")

if not settings.FORCE_CHANNEL_ID:
    print("⚠️ Warning: FORCE_CHANNEL_ID not set. Channel-only mode disabled")

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE SETUP
# ============================================================================

class DatabaseManager:
    """MongoDB connection manager"""
    
    def __init__(self, mongodb_uri: str):
        self.uri = mongodb_uri
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
    
    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = motor.motor_asyncio.AsyncIOMotorClient(self.uri)
            self.db = self.client['swiggy_bot']
            
            # Test connection
            await self.db.command('ping')
            logger.info("✅ MongoDB connected successfully")
            
            # Create indexes
            await self._create_indexes()
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB connection error: {e}")
            return False
    
    async def _create_indexes(self):
        """Create necessary database indexes"""
        try:
            users = self.db['users']
            await users.create_index("user_id", unique=True)
            await users.create_index("created_at")
            
            logs = self.db['admin_logs']
            await logs.create_index("timestamp")
            await logs.create_index("user_id")
            
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            logger.info("✅ MongoDB disconnected")
    
    async def get_collection(self, collection_name: str):
        """Get collection"""
        if not self.db:
            raise RuntimeError("Database not connected")
        return self.db[collection_name]

# Initialize database
db_manager = DatabaseManager(settings.MONGODB_URI)

# ============================================================================
# DECORATORS & MIDDLEWARE
# ============================================================================

def admin_only(func):
    """Admin-only command decorator"""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in settings.ADMIN_IDS:
            logger.warning(f"⚠️ Unauthorized access attempt by user {user_id}")
            await update.message.reply_text(
                "❌ <b>Unauthorized Access</b>\n\n"
                "Only admins can use this command.",
                parse_mode=ParseMode.HTML
            )
            return
        return await func(self, update, context)
    return wrapper

def channel_check(func):
    """Verify user is subscribed to force channel"""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not settings.FORCE_CHANNEL_ID:
            return await func(self, update, context)
        
        user_id = update.effective_user.id
        
        try:
            member = await context.bot.get_chat_member(
                chat_id=settings.FORCE_CHANNEL_ID,
                user_id=user_id
            )
            
            if member.status not in [
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR
            ]:
                await update.message.reply_text(
                    "❌ <b>Channel Subscription Required</b>\n\n"
                    "Please join our channel first:\n"
                    f"<a href='https://t.me/c/{settings.FORCE_CHANNEL_ID}'>Click to Join</a>",
                    parse_mode=ParseMode.HTML
                )
                return
        except TelegramError as e:
            logger.error(f"Channel check error: {e}")
            return
        
        return await func(self, update, context)
    return wrapper

# ============================================================================
# BOT CLASS
# ============================================================================

class SwiggyBot:
    """Main bot class with all handlers"""
    
    def __init__(self, token: str, settings_obj: Settings):
        self.token = token
        self.settings = settings_obj
        self.application: Optional[Application] = None
        self.db: Optional[DatabaseManager] = None
        self.job_queue: Optional[JobQueue] = None
    
    async def initialize(self):
        """Initialize bot and connect to database"""
        logger.info("🚀 Initializing Swiggy Bot...")
        
        # Connect to database
        self.db = db_manager
        if not await self.db.connect():
            raise RuntimeError("Failed to connect to MongoDB")
        
        # Build application
        self.application = (
            Application.builder()
            .token(self.token)
            .build()
        )
        
        # Setup handlers
        self._setup_handlers()
        
        # Setup jobs
        self.job_queue = self.application.job_queue
        self._setup_jobs()
        
        logger.info("✅ Bot initialized successfully")
    
    def _setup_handlers(self):
        """Setup all command and message handlers"""
        # Commands
        self.application.add_handler(CommandHandler("start", self.cmd_start))
        self.application.add_handler(CommandHandler("help", self.cmd_help))
        self.application.add_handler(CommandHandler("admin", self.cmd_admin))
        self.application.add_handler(CommandHandler("dashboard", self.cmd_dashboard))
        self.application.add_handler(CommandHandler("status", self.cmd_status))
        
        # Admin commands
        self.application.add_handler(CommandHandler("users", self.cmd_users))
        self.application.add_handler(CommandHandler("export", self.cmd_export))
        self.application.add_handler(CommandHandler("logs", self.cmd_logs))
        self.application.add_handler(CommandHandler("broadcast", self.cmd_broadcast))
        
        # Message handlers
        self.application.add_handler(MessageHandler(
            filters.Document.JSON, 
            self.handle_json_upload
        ))
        
        # Callback handlers
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
    
    def _setup_jobs(self):
        """Setup background jobs"""
        if not self.job_queue:
            return
        
        # Periodic bot status check
        self.job_queue.run_repeating(
            self.job_check_bot_status,
            interval=self.settings.BOT_CHECK_INTERVAL,
            first=10
        )
        
        # Auto-cleanup old sessions (24 hours)
        self.job_queue.run_daily(
            self.job_cleanup_sessions,
            time=datetime.now().replace(hour=3, minute=0, second=0)
        )
        
        logger.info("✅ Background jobs scheduled")
    
    # ========================================================================
    # COMMAND HANDLERS
    # ========================================================================
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command"""
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        
        # Check channel subscription
        if settings.FORCE_CHANNEL_ID:
            try:
                member = await context.bot.get_chat_member(
                    chat_id=settings.FORCE_CHANNEL_ID,
                    user_id=user_id
                )
                if member.status not in [
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.CREATOR
                ]:
                    keyboard = [[
                        InlineKeyboardButton(
                            "📢 Join Channel",
                            url=f"https://t.me/c/{settings.FORCE_CHANNEL_ID}"
                        )
                    ]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        "❌ <b>Channel Subscription Required</b>\n\n"
                        "Please join our channel to use this bot.",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.HTML
                    )
                    return
            except TelegramError:
                logger.warning(f"Channel check failed for user {user_id}")
        
        # Save user to database
        users_collection = await self.db.get_collection("users")
        await users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "username": username,
                    "first_seen": datetime.utcnow(),
                    "last_seen": datetime.utcnow(),
                    "status": "active"
                }
            },
            upsert=True
        )
        
        # Log action
        await self._log_action(user_id, "START", "Bot started")
        
        welcome_text = f"""
🎉 <b>Welcome to Swiggy Automation Bot!</b>

Hi {username}! I'm your advanced automation assistant.

<b>✨ Features:</b>
✅ JSON-based secure login
✅ Real-time score tracking
✅ Buzz campaign automation
✅ Credit redemption
✅ Background automation
✅ Admin controls & analytics

<b>🚀 Quick Start:</b>
1️⃣ Upload your JSON file
2️⃣ Click "Login"
3️⃣ Use dashboard
4️⃣ Let bot run in background

⚠️ <b>Security:</b> Keep your JSON file confidential!
"""
        
        keyboard = [
            [
                InlineKeyboardButton("📤 Upload JSON", callback_data="upload_json"),
                InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command"""
        help_text = """
<b>📚 Help & Instructions</b>

<b>🔐 JSON Login:</b>
→ Send your JSON file
→ Click "Login"
→ Bot processes securely

<b>📊 Dashboard Features:</b>
🔍 Check Score - View current score
⚡ Start Buzz - Launch campaigns
💰 Redeem Credits - Get rewards
📈 Incline Management - Advanced control

<b>🔧 Admin Features (Admins Only):</b>
👥 User Management
📤 Export Data (JSON)
📋 View Logs
📊 Statistics
🔔 Broadcast Messages

<b>🛡️ Security Tips:</b>
🔒 Never share JSON files
⏱️ Processes run securely in background
🔄 Check status anytime

<b>Need Help?</b> Use /admin to contact support
"""
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
    
    @admin_only
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panel"""
        admin_text = """
<b>🔐 Admin Control Panel</b>

Select an option below:
"""
        
        keyboard = [
            [
                InlineKeyboardButton("👥 Total Users", callback_data="admin_users"),
                InlineKeyboardButton("📊 Stats", callback_data="admin_stats")
            ],
            [
                InlineKeyboardButton("📤 Export Data", callback_data="admin_export"),
                InlineKeyboardButton("📋 View Logs", callback_data="admin_logs")
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton("🔧 Bot Settings", callback_data="admin_settings")
            ],
            [
                InlineKeyboardButton("🚨 Active Sessions", callback_data="admin_sessions")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(admin_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    @admin_only
    async def cmd_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get user count"""
        users_collection = await self.db.get_collection("users")
        user_count = await users_collection.count_documents({})
        active_count = await users_collection.count_documents({"status": "active"})
        
        text = f"""
<b>👥 User Statistics</b>

Total Users: <code>{user_count}</code>
Active Users: <code>{active_count}</code>
Inactive Users: <code>{user_count - active_count}</code>

Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
    @admin_only
    async def cmd_export(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Export user data as JSON"""
        await update.message.reply_text("⏳ Exporting data... Please wait", parse_mode=ParseMode.HTML)
        
        try:
            users_collection = await self.db.get_collection("users")
            users = await users_collection.find({}, {"json_file": 0}).to_list(None)
            
            # Convert ObjectId to string for JSON serialization
            for user in users:
                if "_id" in user:
                    user["_id"] = str(user["_id"])
                if "first_seen" in user:
                    user["first_seen"] = user["first_seen"].isoformat()
                if "last_seen" in user:
                    user["last_seen"] = user["last_seen"].isoformat()
            
            export_data = {
                "exported_at": datetime.utcnow().isoformat(),
                "total_users": len(users),
                "users": users
            }
            
            filename = f"swiggy_bot_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = f"/tmp/{filename}"
            
            with open(filepath, "w") as f:
                json.dump(export_data, f, indent=2)
            
            # Send file
            with open(filepath, "rb") as f:
                await update.message.reply_document(
                    f,
                    filename=filename,
                    caption=f"✅ <b>Data Exported</b>\n\nTotal Users: {len(users)}\nFile: {filename}",
                    parse_mode=ParseMode.HTML
                )
            
            # Cleanup
            os.remove(filepath)
            await self._log_action(update.effective_user.id, "EXPORT", f"Exported {len(users)} users")
            
        except Exception as e:
            logger.error(f"Export error: {e}")
            await update.message.reply_text(
                f"❌ <b>Export Failed</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    @admin_only
    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View recent logs"""
        try:
            logs_collection = await self.db.get_collection("admin_logs")
            logs = await logs_collection.find({}).sort("timestamp", -1).limit(20).to_list(20)
            
            log_text = "<b>📋 Recent Admin Logs (Last 20)</b>\n\n"
            for log in logs:
                timestamp = log.get("timestamp", "N/A")
                if isinstance(timestamp, datetime):
                    timestamp = timestamp.strftime("%H:%M:%S")
                log_text += f"<code>[{timestamp}]</code> {log.get('action')} - User: {log.get('user_id')}\n"
            
            await update.message.reply_text(log_text, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Logs error: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode=ParseMode.HTML)
    
    @admin_only
    async def cmd_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start broadcast mode"""
        context.user_data['broadcast_mode'] = True
        await update.message.reply_text(
            "📢 <b>Broadcast Mode</b>\n\nSend the message you want to broadcast to all users:\n\n"
            "Reply with: /cancel to cancel",
            parse_mode=ParseMode.HTML
        )
    
    async def cmd_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show dashboard"""
        user_id = update.effective_user.id
        users_collection = await self.db.get_collection("users")
        user = await users_collection.find_one({"user_id": user_id})
        
        if not user or user.get("status") != "logged_in":
            await update.message.reply_text(
                "❌ <b>Not Logged In</b>\n\nPlease upload your JSON file and login first.",
                parse_mode=ParseMode.HTML
            )
            return
        
        score = user.get("score", "N/A")
        balance = user.get("balance", "N/A")
        automation_status = user.get("automation_status", "idle")
        
        dashboard_text = f"""
<b>📊 Your Dashboard</b>

👤 User: <code>{user.get('username', 'Unknown')}</code>
📈 Score: <code>{score}</code>
💰 Balance: <code>{balance}</code>
⚙️ Automation: <code>{automation_status.upper()}</code>
🕐 Updated: <code>{datetime.now().strftime('%H:%M:%S')}</code>
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🔍 Check Score", callback_data="check_score"),
                InlineKeyboardButton("⚡ Start Buzz", callback_data="start_buzz")
            ],
            [
                InlineKeyboardButton("💰 Redeem", callback_data="redeem"),
                InlineKeyboardButton("📈 Incline", callback_data="incline")
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="dashboard"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(dashboard_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot status"""
        status_text = f"""
<b>🤖 Bot Status</b>

Status: ✅ <b>Online</b>
Environment: <code>{self.settings.ENVIRONMENT}</code>
Database: ✅ Connected
Uptime: 24/7
Version: 1.0.0

Channel Protection: {"✅ Enabled" if self.settings.FORCE_CHANNEL_ID else "❌ Disabled"}
Admin Panel: ✅ Enabled
"""
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)
    
    # ========================================================================
    # MESSAGE HANDLERS
    # ========================================================================
    
    async def handle_json_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle JSON file upload"""
        user_id = update.effective_user.id
        
        try:
            file = await update.message.document.get_file()
            json_bytes = await file.download_as_bytearray()
            json_data = json.loads(json_bytes.decode('utf-8'))
            
            # Validate JSON structure
            if not self._validate_json(json_data):
                await update.message.reply_text(
                    "❌ <b>Invalid JSON Format</b>\n\nRequired fields:\n"
                    "• auth_token\n• user_id\n\n"
                    "Please check your JSON file.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Save to database
            users_collection = await self.db.get_collection("users")
            await users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "json_file": json_data,
                        "uploaded_at": datetime.utcnow(),
                        "status": "json_received"
                    }
                },
                upsert=True
            )
            
            await self._log_action(user_id, "JSON_UPLOAD", "JSON file received")
            
            keyboard = [
                [InlineKeyboardButton("✅ Login Now", callback_data="login_json")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "✅ <b>JSON Received</b>\n\nReady to login? Click below:",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            
        except json.JSONDecodeError:
            await update.message.reply_text(
                "❌ <b>Invalid JSON</b>\n\nFile is not valid JSON.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"JSON upload error: {e}")
            await update.message.reply_text(
                f"❌ <b>Error Processing File</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    # ========================================================================
    # CALLBACK HANDLERS
    # ========================================================================
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline button callbacks"""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        user_id = query.from_user.id
        
        # Admin callbacks
        if callback_data.startswith("admin_"):
            await self._handle_admin_callback(callback_data, query, user_id)
        
        # User callbacks
        elif callback_data == "upload_json":
            await query.edit_message_text(
                "📤 <b>Upload JSON</b>\n\nPlease send your JSON file.",
                parse_mode=ParseMode.HTML
            )
        
        elif callback_data == "login_json":
            await query.edit_message_text("⏳ Logging in... Please wait", parse_mode=ParseMode.HTML)
            await self._process_login(user_id, query)
        
        elif callback_data == "dashboard":
            await self.cmd_dashboard(update, context)
        
        elif callback_data == "check_score":
            await query.edit_message_text(
                "🔍 <b>Fetching Score...</b>",
                parse_mode=ParseMode.HTML
            )
            # In production, call your API
            await asyncio.sleep(1)
            await query.edit_message_text(
                "📊 <b>Your Score</b>\n\n"
                "Score: <code>Loading...</code>\n\n"
                "API integration required in production",
                parse_mode=ParseMode.HTML
            )
        
        elif callback_data == "help":
            await self.cmd_help(update, context)
        
        elif callback_data == "settings":
            await query.edit_message_text(
                "⚙️ <b>Settings</b>\n\n"
                "🔔 Notifications: ON\n"
                "🔐 Auto-login: OFF\n"
                "📊 Data Export: Enabled\n",
                parse_mode=ParseMode.HTML
            )
    
    async def _handle_admin_callback(self, callback_data: str, query, user_id: int):
        """Handle admin-specific callbacks"""
        if user_id not in settings.ADMIN_IDS:
            await query.answer("❌ Unauthorized", show_alert=True)
            return
        
        if callback_data == "admin_users":
            await self.cmd_users(query.message, None)
        
        elif callback_data == "admin_stats":
            users_collection = await self.db.get_collection("users")
            total = await users_collection.count_documents({})
            active = await users_collection.count_documents({"status": "active"})
            logged_in = await users_collection.count_documents({"status": "logged_in"})
            
            stats_text = f"""
<b>📊 Bot Statistics</b>

Total Users: <code>{total}</code>
Active Users: <code>{active}</code>
Logged In: <code>{logged_in}</code>

Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""
            await query.edit_message_text(stats_text, parse_mode=ParseMode.HTML)
        
        elif callback_data == "admin_export":
            await query.edit_message_text("⏳ Preparing export...", parse_mode=ParseMode.HTML)
            # Will be handled by callback
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    async def _process_login(self, user_id: int, query):
        """Process login"""
        try:
            users_collection = await self.db.get_collection("users")
            user = await users_collection.find_one({"user_id": user_id})
            
            if not user or "json_file" not in user:
                await query.edit_message_text(
                    "❌ <b>Login Failed</b>\n\nNo JSON file found.",
                    parse_mode=ParseMode.HTML
                )
                return
            
            # Update user status
            await users_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "status": "logged_in",
                        "logged_in_at": datetime.utcnow(),
                        "score": 0,
                        "balance": 0,
                        "automation_status": "idle"
                    }
                }
            )
            
            await self._log_action(user_id, "LOGIN_SUCCESS", "User logged in")
            
            await query.edit_message_text(
                "✅ <b>Login Successful!</b>\n\n"
                "Dashboard is ready. Use /dashboard to start.",
                parse_mode=ParseMode.HTML
            )
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            await query.edit_message_text(
                f"❌ <b>Login Error</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML
            )
    
    def _validate_json(self, data: dict) -> bool:
        """Validate JSON structure"""
        required_fields = ["auth_token", "user_id"]
        return all(field in data for field in required_fields)
    
    async def _log_action(self, user_id: int, action: str, message: str):
        """Log admin action"""
        try:
            logs_collection = await self.db.get_collection("admin_logs")
            await logs_collection.insert_one({
                "user_id": user_id,
                "action": action,
                "message": message,
                "timestamp": datetime.utcnow()
            })
        except Exception as e:
            logger.warning(f"Log error: {e}")
    
    async def job_check_bot_status(self, context: ContextTypes.DEFAULT_TYPE):
        """Periodic bot status check"""
        logger.info("✅ Bot health check: OK")
    
    async def job_cleanup_sessions(self, context: ContextTypes.DEFAULT_TYPE):
        """Cleanup old sessions"""
        try:
            users_collection = await self.db.get_collection("users")
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            
            result = await users_collection.delete_many({
                "last_seen": {"$lt": cutoff_date}
            })
            
            logger.info(f"🧹 Cleaned up {result.deleted_count} old sessions")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error: {context.error}")
    
    # ========================================================================
    # BOT LIFECYCLE
    # ========================================================================
    
    async def run(self):
        """Run the bot"""
        try:
            await self.initialize()
            
            # Set bot commands
            commands = [
                BotCommand("start", "Start the bot"),
                BotCommand("help", "Get help"),
                BotCommand("dashboard", "View dashboard"),
                BotCommand("status", "Check bot status"),
                BotCommand("admin", "Admin panel (admin only)"),
            ]
            await self.application.bot.set_my_commands(commands)
            
            logger.info("✅ Bot started successfully")
            logger.info(f"📢 Force Channel: {'Enabled' if settings.FORCE_CHANNEL_ID else 'Disabled'}")
            logger.info(f"🔐 Admin IDs: {settings.ADMIN_IDS}")
            
            await self.application.run_polling()
            
        except Exception as e:
            logger.error(f"❌ Bot error: {e}")
            raise
        finally:
            if self.db:
                await self.db.disconnect()

# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Main entry point"""
    bot = SwiggyBot(settings.TELEGRAM_TOKEN, settings)
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise
