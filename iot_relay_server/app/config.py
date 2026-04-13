from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    IOT_API_KEY: str = "farmos-iot-default-key"
    SOIL_MOISTURE_LOW: float = 55.0
    SOIL_MOISTURE_HIGH: float = 70.0

    # AI Agent
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_URL: str = "https://openrouter.ai/api/v1"
    AI_AGENT_MODEL: str = "openai/gpt-5-nano"
    AI_AGENT_LLM_INTERVAL: int = 300  # LLM 호출 최소 간격 (초)

    # 기상청 API
    KMA_DECODING_KEY: str = ""
    FARM_NX: int = 84
    FARM_NY: int = 106

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
