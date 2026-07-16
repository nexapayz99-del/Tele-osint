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
            self.search_history = self.db['search_history']
            self.banned_users = self.db['banned_users']
            self.logs = self.db['logs']
            
            # Create indexes
            self.users.create_index('user_id', unique=True)
            self.banned_users.create_index('user_id', unique=True)
            self.search_history.create_index([('user_id', 1), ('timestamp', -1)])
            
            logger.info("MongoDB connected successfully")
        except Exception as e:
            logger.error(f"MongoDB connection error: {e}")
            raise

    # User Management
    def add_user(self, user_id, username=None, first_name=None, last_name=None):
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
            self.users.update_one(
                {'user_id': user_id},
                {'$set': user_data},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error adding user: {e}")
            return False

    def get_user(self, user_id):
        return self.users.find_one({'user_id': user_id})

    def update_user_activity(self, user_id):
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'last_active': datetime.now()}}
        )

    # Ban Management
    def ban_user(self, user_id, reason=None, admin_id=None):
        try:
            ban_data = {
                'user_id': user_id,
                'reason': reason or 'No reason provided',
                'banned_by': admin_id,
                'banned_at': datetime.now()
            }
            self.banned_users.update_one(
                {'user_id': user_id},
                {'$set': ban_data},
                upsert=True
            )
            self.users.update_one(
                {'user_id': user_id},
                {'$set': {'is_banned': True}}
            )
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False

    def unban_user(self, user_id):
        try:
            self.banned_users.delete_one({'user_id': user_id})
            self.users.update_one(
                {'user_id': user_id},
                {'$set': {'is_banned': False}}
            )
            return True
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False

    def is_user_banned(self, user_id):
        return self.banned_users.find_one({'user_id': user_id}) is not None

    def get_banned_users(self, limit=100):
        return list(self.banned_users.find().limit(limit))

    # Search History
    def add_search(self, user_id, search_query, result_data=None):
        try:
            search_data = {
                'user_id': user_id,
                'query': search_query,
                'result': result_data,
                'timestamp': datetime.now()
            }
            self.search_history.insert_one(search_data)
            
            # Increment search count
            self.users.update_one(
                {'user_id': user_id},
                {'$inc': {'total_searches': 1}}
            )
            return True
        except Exception as e:
            logger.error(f"Error adding search: {e}")
            return False

    def get_user_history(self, user_id, limit=10):
        return list(self.search_history.find(
            {'user_id': user_id}
        ).sort('timestamp', -1).limit(limit))

    # Logs
    def add_log(self, user_id, action, details=None):
        try:
            log_data = {
                'user_id': user_id,
                'action': action,
                'details': details,
                'timestamp': datetime.now()
            }
            self.logs.insert_one(log_data)
            return True
        except Exception as e:
            logger.error(f"Error adding log: {e}")
            return False

    # Stats
    def get_stats(self):
        try:
            total_users = self.users.count_documents({})
            total_searches = self.search_history.count_documents({})
            banned_count = self.banned_users.count_documents({})
            active_today = self.users.count_documents({
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
            return None

# Singleton instance
db = Database()
