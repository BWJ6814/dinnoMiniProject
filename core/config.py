from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Neo4j Graph DB 연결 설정
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "ddworks1234"

    # LLM API Keys
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # 사용할 LLM 제공자 및 모델
    # "anthropic" 또는 "openai" 중 선택
    LLM_PROVIDER: str = "anthropic"
    LLM_MODEL: str = "claude-sonnet-4-6"

    # 마이크로서비스 간 통신 URL
    # main-service(8000)가 agent-service(8001)를 호출할 때 사용
    AGENT_SERVICE_URL: str = "http://localhost:8001"
    MAIN_SERVICE_URL: str = "http://localhost:8000"

    # As-Built vs As-Designed 정합성 검증 허용 오차 (단위: 미터)
    # 5cm 초과 시 경고 발생 (반도체 FAB 시공 정밀도 기준)
    CONSISTENCY_TOLERANCE_M: float = 0.05


settings = Settings()
