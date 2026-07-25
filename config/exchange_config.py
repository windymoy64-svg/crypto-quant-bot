from pydantic import BaseModel

class ExchangeConfig(BaseModel):
    """Configuration for exchange API"""
    api_key: str
    secret_key: str
    enable_rate_limit: bool = True
    sandbox_mode: bool = False
    
    @classmethod
    def from_env(cls):
        """Load config from environment variables"""
        import os
        return cls(
            api_key=os.getenv('EXCHANGE_API_KEY', ''),
            secret_key=os.getenv('EXCHANGE_SECRET_KEY', ''),
            enable_rate_limit=os.getenv('ENABLE_RATE_LIMIT', 'True').lower() in ('true', '1', 't')
        )