import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LiteArchivist:
    """
    Local SQLite-based Deep Archive for long-term memory persistence.
    Bridges the gap between short-term context and heavy vector storage.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Default to project root for easy inspection
            db_path = Path.cwd() / "palace_archive.db"
        
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """Initialize the archive schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table: palace_archive (Generic schema for entity/memory tracking)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS palace_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp TEXT,
                change_summary TEXT,
                source TEXT,
                tags TEXT,          -- JSON string array
                topic TEXT,
                mode TEXT,
                concepts TEXT,      -- JSON string array
                importance INTEGER, -- 1=low, 2=notable, 3=critical
                audit_score REAL,
                raw_data TEXT       -- Full JSON blob for future-proofing
            )
        ''')
        
        conn.commit()
        conn.close()

    def add_memory(self, entry: Dict[str, Any]):
        """
        Adds a memory entry to the archive.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO palace_archive (
                session_id, timestamp, change_summary, source, tags, 
                topic, mode, concepts, importance, audit_score, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            entry.get('session_id'),
            entry.get('timestamp', datetime.now().isoformat()),
            entry.get('change_summary'),
            entry.get('source', 'inference'),
            json.dumps(entry.get('tags', [])),
            entry.get('topic'),
            entry.get('mode'),
            json.dumps(entry.get('concepts', [])),
            entry.get('importance', 2),
            entry.get('audit_score', 0.0),
            json.dumps(entry)
        ))
        
        conn.commit()
        conn.close()

    def search_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Searches archived memories based on keywords, tags, or topics.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        search_pattern = f"%{query}%"
        cursor.execute('''
            SELECT * FROM palace_archive 
            WHERE change_summary LIKE ? 
               OR topic LIKE ? 
               OR tags LIKE ?
            ORDER BY importance DESC, timestamp DESC 
            LIMIT ?
        ''', (search_pattern, search_pattern, search_pattern, limit))
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Post-process JSON fields
        for res in results:
            res['tags'] = json.loads(res['tags'])
            res['concepts'] = json.loads(res['concepts'])
            
        return results

    def get_density_report(self) -> Dict[str, Any]:
        """
        Generates a summary of the archive's density.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM palace_archive")
        total_count = cursor.fetchone()[0]
        conn.close()
        
        return {
            "total_archived_records": total_count,
            "status": "Active" if total_count > 0 else "Ready"
        }

