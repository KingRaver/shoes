import sqlite3
from datetime import datetime
import json
from typing import Dict, List, Optional, Union, Any
from dataclasses import asdict
import os
from utils.logger import logger

class CryptoDatabase:
    def __init__(self, db_path: str = "data/crypto_history.db"):
        """Initialize database connection and create tables if they don't exist"""
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self._initialize_database()

    def _get_connection(self):
        """Get database connection, creating it if necessary"""
        if not self.conn:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            self.cursor = self.conn.cursor()
        return self.conn, self.cursor

    def _initialize_database(self):
        """Create necessary tables if they don't exist"""
        conn, cursor = self._get_connection()
        
        try:
            # Market Data Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    chain TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume REAL NOT NULL,
                    price_change_24h REAL,
                    market_cap REAL,
                    ath REAL,
                    ath_change_percentage REAL
                )
            """)

            # Correlation Analysis Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS correlation_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    price_correlation REAL NOT NULL,
                    volume_correlation REAL NOT NULL,
                    market_cap_ratio REAL NOT NULL
                )
            """)

            # Posted Content Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS posted_content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    content TEXT NOT NULL,
                    sentiment JSON NOT NULL,
                    trigger_type TEXT NOT NULL,
                    price_data JSON NOT NULL,
                    meme_phrases JSON NOT NULL
                )
            """)

            # Chain Mood History
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mood_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    chain TEXT NOT NULL,
                    mood TEXT NOT NULL,
                    indicators JSON NOT NULL
                )
            """)

            # Create indices for better query performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_data_timestamp ON market_data(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_data_chain ON market_data(chain)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_correlation_timestamp ON correlation_analysis(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posted_content_timestamp ON posted_content(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mood_history_timestamp ON mood_history(timestamp)")

            conn.commit()
            logger.logger.info("Database initialized successfully")

        except Exception as e:
            logger.log_error("Database Initialization", str(e))
            raise

    def store_market_data(self, chain: str, data: Dict[str, Any]) -> None:
        """Store market data for a specific chain"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                INSERT INTO market_data (
                    timestamp, chain, price, volume, price_change_24h, 
                    market_cap, ath, ath_change_percentage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(),
                chain,
                data['current_price'],
                data['volume'],
                data['price_change_percentage_24h'],
                data['market_cap'],
                data['ath'],
                data['ath_change_percentage']
            ))
            conn.commit()
        except Exception as e:
            logger.log_error(f"Store Market Data - {chain}", str(e))
            conn.rollback()

    def store_correlation_analysis(self, analysis: Dict[str, float]) -> None:
        """Store correlation analysis results"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                INSERT INTO correlation_analysis (
                    timestamp, price_correlation, volume_correlation, market_cap_ratio
                ) VALUES (?, ?, ?, ?)
            """, (
                datetime.now(),
                analysis['price_correlation'],
                analysis['volume_correlation'],
                analysis['market_cap_ratio']
            ))
            conn.commit()
        except Exception as e:
            logger.log_error("Store Correlation Analysis", str(e))
            conn.rollback()

    def store_posted_content(self, content: str, sentiment: Dict, 
                           trigger_type: str, price_data: Dict, 
                           meme_phrases: Dict) -> None:
        """Store posted content with metadata"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                INSERT INTO posted_content (
                    timestamp, content, sentiment, trigger_type, 
                    price_data, meme_phrases
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(),
                content,
                json.dumps(sentiment),
                trigger_type,
                json.dumps(price_data),
                json.dumps(meme_phrases)
            ))
            conn.commit()
        except Exception as e:
            logger.log_error("Store Posted Content", str(e))
            conn.rollback()

    def store_mood(self, chain: str, mood: str, indicators: Dict) -> None:
        """Store mood data for a specific chain"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                INSERT INTO mood_history (
                    timestamp, chain, mood, indicators
                ) VALUES (?, ?, ?, ?)
            """, (
                datetime.now(),
                chain,
                mood,
                json.dumps(asdict(indicators))
            ))
            conn.commit()
        except Exception as e:
            logger.log_error(f"Store Mood - {chain}", str(e))
            conn.rollback()

    def get_recent_market_data(self, chain: str, hours: int = 24) -> List[Dict]:
        """Get recent market data for a specific chain"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                SELECT * FROM market_data 
                WHERE chain = ? 
                AND timestamp >= datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            """, (chain, hours))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.log_error(f"Get Recent Market Data - {chain}", str(e))
            return []

    def get_recent_correlations(self, hours: int = 24) -> List[Dict]:
        """Get recent correlation analysis"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                SELECT * FROM correlation_analysis 
                WHERE timestamp >= datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            """, (hours,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.log_error("Get Recent Correlations", str(e))
            return []

    def get_recent_posts(self, hours: int = 24) -> List[Dict]:
        """Get recent posted content"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                SELECT * FROM posted_content 
                WHERE timestamp >= datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            """, (hours,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.log_error("Get Recent Posts", str(e))
            return []

    def check_content_similarity(self, content: str) -> bool:
        """Check if similar content was recently posted"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                SELECT content FROM posted_content 
                WHERE timestamp >= datetime('now', '-1 hour')
            """)
            recent_posts = [row['content'] for row in cursor.fetchall()]
            
            # Simple similarity check - can be enhanced later
            return any(content.strip() == post.strip() for post in recent_posts)
        except Exception as e:
            logger.log_error("Check Content Similarity", str(e))
            return False

    def get_chain_stats(self, chain: str, hours: int = 24) -> Dict[str, Any]:
        """Get statistical summary for a chain"""
        conn, cursor = self._get_connection()
        try:
            cursor.execute("""
                SELECT 
                    AVG(price) as avg_price,
                    MAX(price) as max_price,
                    MIN(price) as min_price,
                    AVG(volume) as avg_volume,
                    MAX(volume) as max_volume,
                    AVG(price_change_24h) as avg_price_change
                FROM market_data 
                WHERE chain = ? 
                AND timestamp >= datetime('now', '-' || ? || ' hours')
            """, (chain, hours))
            return dict(cursor.fetchone())
        except Exception as e:
            logger.log_error(f"Get Chain Stats - {chain}", str(e))
            return {}

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None
