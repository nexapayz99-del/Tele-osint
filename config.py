import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot
    BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
    
    # MongoDB
    MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    DATABASE_NAME = os.getenv('DATABASE_NAME', 'telegram_bot_db')
    
    # API
    API_URL = 'http://techspy.site.je/api/index.php'
    API_ID = 'api_812154f4'
    
    # Owner
    OWNER_ID = int(os.getenv('OWNER_ID', '123456789'))  # Replace with your Telegram ID
    
    # Admin IDs (can be multiple)
    ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id]
    ADMIN_IDS.append(OWNER_ID)  # Owner is always admin
