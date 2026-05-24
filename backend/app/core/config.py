from pydantic import BaseSettings


class Settings(BaseSettings):
    binance_api_key: str
    binance_secret: str

    bybit_api_key: str
    bybit_secret: str

    class Config:
        env_file = ".env"


settings = Settings()