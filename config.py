"""
Configuration module for Swiggy Bot
Production-ready with Railway support
"""

import os
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# TELEGRAM CONFIGURATION
# ============================================================================

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN environment variable is required!")

# Parse admin IDs from comma-separated string
ADMIN_IDS_STR = os.getenv('ADMIN_IDS', '').strip()
ADMIN_IDS: List[int] = []
if ADMIN_IDS_STR:
    try:
        ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(',') if id.strip()]
    except ValueError:
        print("⚠️ Warning: Invalid ADMIN_IDS format. Expected comma-separated numbers.")

# Force channel configuration
ADMIN_CHANNEL_ID = int(os.getenv('ADMIN_CHANNEL_ID', '0') or '0')
FORCE_CHANNEL_ID = int(os.getenv('FORCE_CHANNEL_ID', '0') or '0')

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

# MongoDB URI - Railway will provide this via environment variable
MONGODB_URI = os.getenv(
    'MONGODB_URI',
    'mongodb://localhost:27017/swiggy_bot'
)

# Validate MongoDB URI in production
if 'mongodb://' not in MONGODB_URI and 'mongodb+srv://' not in MONGODB_URI:
    print("⚠️ Warning: Invalid MongoDB URI format")

# ============================================================================
# API CONFIGURATION
# ============================================================================

API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5000').strip()
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '120'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))

# ============================================================================
# REDIS CONFIGURATION (Optional)
# ============================================================================

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379').strip()
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost').strip()
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '').strip()

if REDIS_PASSWORD:
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}"
else:
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"

# ============================================================================
# BOT CONFIGURATION
# ============================================================================

# Bot behavior settings
MAX_CONCURRENT_USERS = int(os.getenv('MAX_CONCURRENT_USERS', '500'))
SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', '3600'))
BOT_CHECK_INTERVAL = int(os.getenv('BOT_CHECK_INTERVAL', '300'))

# Background task intervals (seconds)
BUZZ_INTERVAL = int(os.getenv('BUZZ_INTERVAL', '3600'))  # 1 hour
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '600'))  # 10 minutes
AUTOMATION_CHECK_INTERVAL = int(os.getenv('AUTOMATION_CHECK_INTERVAL', '300'))  # 5 minutes

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

JWT_SECRET = os.getenv('JWT_SECRET', 'change_in_production').strip()
ADMIN_SECRET = os.getenv('ADMIN_SECRET', 'admin_secret_key').strip()

# Rate limiting
RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', '100'))
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '60'))

# Webhook configuration
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'webhook_secret_key').strip()
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '').strip()

# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

ENVIRONMENT = os.getenv('ENVIRONMENT', 'production').lower()
DEBUG = ENVIRONMENT == 'development'
NODE_ENV = os.getenv('NODE_ENV', 'production')

# Railway specific
RAILWAY_ENVIRONMENT_NAME = os.getenv('RAILWAY_ENVIRONMENT_NAME', 'production')
RAILWAY_DEPLOYMENT_ID = os.getenv('RAILWAY_DEPLOYMENT_ID', 'unknown')

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_FILE = os.getenv('LOG_FILE', '/tmp/swiggy_bot.log')

# Ensure log file directory exists
LOG_DIR = os.path.dirname(LOG_FILE)
if LOG_DIR and not os.path.exists(LOG_DIR):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception as e:
        print(f"⚠️ Warning: Could not create log directory: {e}")

# ============================================================================
# EMAIL CONFIGURATION (Optional, for notifications)
# ============================================================================

SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com').strip()
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '').strip()
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL', '').strip()

# ============================================================================
# FEATURE FLAGS
# ============================================================================

ENABLE_NOTIFICATIONS = os.getenv('ENABLE_NOTIFICATIONS', 'true').lower() == 'true'
ENABLE_EXPORT = os.getenv('ENABLE_EXPORT', 'true').lower() == 'true'
ENABLE_ADMIN_PANEL = os.getenv('ENABLE_ADMIN_PANEL', 'true').lower() == 'true'
ENABLE_CHANNEL_CHECK = os.getenv('ENABLE_CHANNEL_CHECK', 'true').lower() == 'true'

# ============================================================================
# SWIGGY SPECIFIC CONFIGURATION
# ============================================================================

SWIGGY_LOGIN_URL = "https://lookupinfo.in/swiggy"
SWIGGY_DASHBOARD_URL = "https://lookupinfo.in/swiggy/dashboard"

# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_config():
    """Validate critical configuration"""
    errors = []
    warnings = []
    
    # Critical checks
    if not TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN is required")
    
    if not MONGODB_URI:
        errors.append("MONGODB_URI is required")
    
    # Warning checks
    if not ADMIN_IDS:
        warnings.append("No ADMIN_IDS configured")
    
    if not FORCE_CHANNEL_ID and ENABLE_CHANNEL_CHECK:
        warnings.append("FORCE_CHANNEL_ID not set, channel check disabled")
    
    if ENVIRONMENT not in ['development', 'production', 'staging']:
        warnings.append(f"Unknown ENVIRONMENT: {ENVIRONMENT}")
    
    if DEBUG and ENVIRONMENT == 'production':
        errors.append("DEBUG mode cannot be enabled in production")
    
    # JWT secret should be changed
    if JWT_SECRET == 'change_in_production':
        warnings.append("JWT_SECRET is using default value, change in production")
    
    # Print results
    if errors:
        print("❌ Configuration Errors:")
        for error in errors:
            print(f"  - {error}")
        raise ValueError("Invalid configuration")
    
    if warnings:
        print("⚠️ Configuration Warnings:")
        for warning in warnings:
            print(f"  - {warning}")
    
    return True

# ============================================================================
# CONFIGURATION SUMMARY
# ============================================================================

def print_config_summary():
    """Print configuration summary for debugging"""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║         Swiggy Bot Configuration Summary                      ║
╚═══════════════════════════════════════════════════════════════╝

🔐 TELEGRAM CONFIGURATION
  Token: {'*' * (len(TELEGRAM_TOKEN) - 4) + TELEGRAM_TOKEN[-4:] if TELEGRAM_TOKEN else 'NOT SET'}
  Admin IDs: {ADMIN_IDS if ADMIN_IDS else 'None'}
  Admin Channel: {ADMIN_CHANNEL_ID if ADMIN_CHANNEL_ID else 'Not configured'}
  Force Channel: {FORCE_CHANNEL_ID if FORCE_CHANNEL_ID else 'Not configured'}

🗄️ DATABASE CONFIGURATION
  MongoDB URI: {MONGODB_URI[:50]}...
  Connection Pool: {MAX_CONCURRENT_USERS} users

🌐 API CONFIGURATION
  Base URL: {API_BASE_URL}
  Timeout: {API_TIMEOUT}s
  Redis URL: {REDIS_URL}

⚙️ BOT CONFIGURATION
  Environment: {ENVIRONMENT.upper()}
  Debug Mode: {DEBUG}
  Log Level: {LOG_LEVEL}
  Log File: {LOG_FILE}

🛡️ SECURITY
  Rate Limit: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s
  Channel Check: {'✅ Enabled' if ENABLE_CHANNEL_CHECK else '❌ Disabled'}
  Admin Panel: {'✅ Enabled' if ENABLE_ADMIN_PANEL else '❌ Disabled'}
  Data Export: {'✅ Enabled' if ENABLE_EXPORT else '❌ Disabled'}

🚀 DEPLOYMENT
  Railway Environment: {RAILWAY_ENVIRONMENT_NAME}
  Deployment ID: {RAILWAY_DEPLOYMENT_ID}

""")

# Run validation on import
if __name__ != '__main__':
    try:
        validate_config()
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        import sys
        sys.exit(1)
