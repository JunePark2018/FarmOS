from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    IOT_API_KEY: str = "farmos-iot-default-key"
    SOIL_MOISTURE_LOW: float = 55.0
    SOIL_MOISTURE_HIGH: float = 70.0

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
