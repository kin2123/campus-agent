"""全局配置。所有可调项集中在这里，通过 .env 覆盖。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
KB_DIR = BACKEND_DIR / "kb"

DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 服务端口 ----------
    # 刻意避开 8000/8080：容易与已有服务冲突，且某些沙箱会注入 SERVER_PORT。
    host: str = "127.0.0.1"
    backend_port: int = 18000
    mcp_port: int = 18001

    # ---------- 鉴权 ----------
    jwt_secret: str = "campus-assistant-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    # 前端登录后拿到的正式票据有效期
    access_token_minutes: int = 720
    # 后端签给 MCP 的「短票据」有效期，仅够一次 Agent 会话使用
    mcp_ticket_seconds: int = 300

    # ---------- 模型接入 ----------
    # fake   = 内置脚本假模型，无需 API Key，用于验证链路是否贯通
    # deepseek / zhipu / openai_compatible = 真实模型
    llm_provider: str = "fake"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_temperature: float = 0.0

    # ---------- RAG ----------
    # local  = 内置轻量哈希向量（零依赖、零 Key，开箱可用）
    # 真实模型接入后可切到模型厂商的 embedding
    embedding_backend: str = "local"
    embedding_model: str = ""
    chroma_collection: str = "campus_knowledge"
    rag_top_k: int = 4

    # ---------- 业务规则 ----------
    max_credits_per_semester: int = 30

    @property
    def sqlite_path(self) -> Path:
        return DATA_DIR / "campus.db"

    @property
    def chroma_path(self) -> Path:
        return DATA_DIR / "chroma"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.sqlite_path.as_posix()}"

    @property
    def mcp_server_url(self) -> str:
        return f"http://{self.host}:{self.mcp_port}/mcp"

    @property
    def business_base_url(self) -> str:
        """MCP 工具服务回调业务接口用的地址。"""
        return f"http://{self.host}:{self.backend_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
