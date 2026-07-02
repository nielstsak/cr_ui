import os
import sqlite3
import logging
from pathlib import Path
from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("RunsRouter")

router = APIRouter(prefix="/api/runs", tags=["runs"])

class SessionResponse(BaseModel):
    timestamp: str
    timeframe: str
    sample_size: int
    period_start: str
    period_end: str
    kick_threshold: float

def init_database_and_runs():
    os.makedirs("data", exist_ok=True)
    db_path = "data/runs.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            timeframe TEXT,
            sample_size INTEGER,
            period_start TEXT,
            period_end TEXT,
            kick_threshold REAL,
            timestamp TEXT
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM runs")
    if cursor.fetchone()[0] == 0:
        default_runs = [
            ("BTCUSDT", "15m", 14500, "2026-03-01", "2026-06-22", 2.0, "2026-07-02 12:00:00"),
            ("BTCUSDT", "5m", 43500, "2026-03-01", "2026-06-22", 1.5, "2026-07-01 18:30:00"),
            ("BTCUSDC", "15m", 14500, "2026-03-01", "2026-06-22", 2.0, "2026-07-02 12:05:00")
        ]
        cursor.executemany("""
            INSERT INTO runs (symbol, timeframe, sample_size, period_start, period_end, kick_threshold, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, default_runs)
        conn.commit()
        logger.info("Database initialized with default runs.")
    conn.close()

def sync_database_with_disk():
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol, timeframe FROM runs")
    all_runs = cursor.fetchall()
    
    base_dir = Path("data/BINANCE")
    for run_id, symbol, timeframe in all_runs:
        symbol_dir = base_dir / symbol.upper()
        file_exists = False
        if symbol_dir.exists():
            for tf_dir in symbol_dir.iterdir():
                if tf_dir.is_dir() and (tf_dir / "ohlcv.h5").exists():
                    file_exists = True
                    break
        if not file_exists:
            cursor.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            logger.info(f"Deleted run {run_id} ({symbol} {timeframe}) as no matching HDF5 file was found.")
            
    conn.commit()
    conn.close()

@router.get("/symbols", response_model=List[str])
async def get_symbols():
    sync_database_with_disk()
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM runs")
    symbols = [r[0] for r in cursor.fetchall()]
    conn.close()
    if not symbols:
        symbols = ["BTCUSDT"]
    return symbols

@router.get("/sessions/{symbol}", response_model=List[SessionResponse])
async def get_sessions(symbol: str):
    sync_database_with_disk()
    conn = sqlite3.connect("data/runs.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, timeframe, sample_size, period_start, period_end, kick_threshold 
        FROM runs 
        WHERE symbol = ? 
        ORDER BY timestamp DESC
    """, (symbol.upper(),))
    rows = cursor.fetchall()
    conn.close()
    
    sessions = []
    for row in rows:
        sessions.append(SessionResponse(
            timestamp=row[0],
            timeframe=row[1],
            sample_size=row[2],
            period_start=row[3],
            period_end=row[4],
            kick_threshold=row[5]
        ))
    return sessions