from pydantic import BaseModel

class DatabaseConfig(BaseModel):
    """Configuration for database"""
    db_path: str = "crypto_bot.db"
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    retention_days: int = 30