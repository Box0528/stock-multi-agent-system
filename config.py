from __future__ import annotations

import os
import logging
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic_settings import BaseSettings
from pydantic import Field

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """集中配置 — 所有魔法数字归拢于此，通过 .env 或环境变量覆盖。"""

    # ── LLM ──
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_temperature_default: float = 0.1
    llm_temperature_creative: float = 0.2
    llm_temperature_reasoning: float = 0.05
    llm_max_retries: int = 3
    llm_retry_backoff: float = 1.0

    # ── 搜索 ──
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    news_search_max_results: int = 5
    news_search_days: int = 7

    # ── 选股阈值 ──
    screener_min_turnover: float = 5.0
    screener_max_turnover: float = 15.0
    screener_min_amount_yi: float = 3.0
    screener_top_n_industries: int = 10

    # ── 认知参数 ──
    reasoning_max_tokens: int = 300
    self_eval_confidence_threshold: float = 0.5
    feedback_loop_max_rounds: int = 1

    # ── 成本预算 ──
    max_llm_calls_per_analysis: int = 30
    max_tokens_per_analysis: int = 100000

    # ── 服务 ──
    cors_origins_raw: str = Field(default="http://localhost:8000,http://127.0.0.1:8000", alias="CORS_ORIGINS")
    access_key: str = Field(default="", alias="ACCESS_KEY")
    data_dir: str = os.path.join(os.path.dirname(__file__), "local_stock_data")
    meta_file: str = os.path.join(os.path.dirname(__file__), "meta", "stock_meta.csv")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    if not settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY 未设置，LLM 调用将失败")
    return settings


def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    """签名不变，内部改读 Settings。"""
    s = get_settings()
    return ChatOpenAI(
        model=s.deepseek_model,
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url,
        temperature=temperature,
    )
