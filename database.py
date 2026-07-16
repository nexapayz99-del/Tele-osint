from pymongo import MongoClient
from datetime import datetime
import logging
from config import Config

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        try:
            self.client = MongoClient(Config.MONGODB_URI)
            self.db = self.client[Config.DATABASE_NAME]
            
            # Collections
            self.users = self.db['users']
            self.searches = self.db['searches']
            self.banned = self.db['banned']
            self.logs = self.db['logs']
            
            # Indexes
            self.users.create_index('user_id', unique=True)
            self.banned.create_index('user_id', unique=True)
            self.searches.create_index([('user_id', 1), ('timestamp', -1)])
            
            logger.info("✅ MongoDB connected")
        except Exception as e:
            logger.error(f"❌ MongoDB error: {e}")
            raise

    def register_user(self, user_id, username=None, first_name=None):
        """Register or update user"""
        self.users.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'username': username,
                    'first_name': first_name,
                    'last_active': datetime.now()
                },
                '$setOnInsert': {
                    'joined': datetime.now(),
                    'searches': 0,
                    'banned': False
                }
            },
            upsert=True
        )

    def is_banned(self, user_id):
        """Check if user is banned"""
        return self.banned.find_one({'user_id': user_id}) is not None

    def ban_user(self, user_id, reason='No reason', admin_id=None):
        """Ban a user"""
        self.banned.update_one(
            {'user_id': user_id},
            {
                '$set': {
                    'reason': reason,
                    'banned_by': admin_id,
                    'banned_at': datetime.now()
                }
            },
            upsert=True
        )
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'banned': True}}
        )

    def unban_user(self, user_id):
        """Unban a user"""
        self.banned.delete_one({'user_id': user_id})
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'banned': False}}
        )

    def get_banned(self):
        """Get all banned users"""
        return list(self.banned.find())

    def save_search(self, user_id, number, result):
        """Save search history"""
        self.searches.insert_one({
            'user_id': user_id,
            'number': number,
            'result': result,
            'timestamp': datetime.now()
        })
        self.users.update_one(
            {'user_id': user_id},
            {'$inc': {'searches': 1}}
        )

    def get_history(self, user_id, limit=10):
        """Get user search history"""
        return list(self.searches.find(
            {'user_id': user_id}
        ).sort('timestamp', -1).limit(limit))

    def get_stats(self):
        """Get bot statistics"""
        return {
            'users': self.users.count_documents({}),
            'searches': self.searches.count_documents({}),
            'banned': self.banned.count_documents({}),
            'today': self.users.count_documents({
                'last_active': {
                    '$gte': datetime.now().replace(hour=0, minute=0, second=0)
                }
            })
        }

    def log_action(self, user_id, action, details=None):
        """Log user action"""
        self.logs.insert_one({
            'user_id': user_id,
            'action': action,
            'details': details,
            'timestamp': datetime.now()
        })