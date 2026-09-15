"""Configuration is injected once; credentials are never placed in Graph state."""
import json
from pathlib import Path
from typing import Literal
from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8-sig',
                                      extra='ignore', populate_by_name=True, hide_input_in_errors=True)
    app_env: Literal['dev', 'test', 'prod'] = 'dev'
    app_mode: Literal['offline', 'live'] = 'offline'
    app_host: str = '127.0.0.1'
    app_port: int = 8000
    data_dir: Path = PROJECT_ROOT / 'runtime'
    storage_backend: Literal['sqlite', 'postgres'] = 'sqlite'
    checkpoint_backend: Literal['sqlite', 'postgres'] = 'sqlite'
    auth_secret: SecretStr = SecretStr('dev-only-retrade-signing-secret-change-me')
    admin_api_key: SecretStr = SecretStr('dev-admin-change-me')
    llm_base_url: str = Field(default='https://api.deepseek.com/v1',
                             validation_alias=AliasChoices('AIROBOT_LLM_BASE_URL', 'LLM_BASE_URL'))
    llm_model: str = Field(default='qwen-plus', validation_alias=AliasChoices('AIROBOT_LLM_MODEL','LLM_MODEL'))
    llm_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('AIROBOT_LLM_API_KEY','LLM_API_KEY'))
    llm_temperature: float = Field(default=0.1, validation_alias='AIROBOT_LLM_TEMPERATURE')
    llm_timeout: float = Field(default=45, gt=0, validation_alias='AIROBOT_LLM_TIMEOUT')
    structured_method: Literal['function_calling','json_schema','json_mode'] = Field(
        default='function_calling', validation_alias='AIROBOT_STRUCTURED_OUTPUT_METHOD')
    llm_extra_body: str = Field(default='{}', validation_alias='AIROBOT_LLM_EXTRA_BODY')
    embedding_base_url: str = Field(default='https://api.siliconflow.cn/v1',
        validation_alias=AliasChoices('AIROBOT_EMBEDDING_BASE_URL','EMBEDDING_BASE_URL'))
    embedding_model: str = Field(default='Pro/BAAI/bge-m3',
        validation_alias=AliasChoices('AIROBOT_EMBEDDING_MODEL','EMBEDDING_MODEL'))
    embedding_api_key: SecretStr = Field(default=SecretStr(''),
        validation_alias=AliasChoices('AIROBOT_EMBEDDING_API_KEY','EMBEDDING_API_KEY'))
    rerank_enabled: bool = Field(default=True, validation_alias='AIROBOT_RERANK_ENABLED')
    rerank_provider: Literal['siliconflow'] = Field(default='siliconflow',validation_alias='AIROBOT_RERANK_PROVIDER')
    rerank_base_url: str = Field(default='https://api.siliconflow.cn/v1',validation_alias='AIROBOT_RERANK_BASE_URL')
    rerank_model: str = Field(default='BAAI/bge-reranker-v2-m3',validation_alias='AIROBOT_RERANK_MODEL')
    rerank_api_key: SecretStr = Field(default=SecretStr(''),
        validation_alias='AIROBOT_RERANK_API_KEY')
    siliconflow_api_key: SecretStr = Field(default=SecretStr(''),validation_alias='SILICONFLOW_API_KEY')
    rerank_timeout: float = Field(default=15,gt=0,validation_alias='AIROBOT_RERANK_TIMEOUT')
    vector_store: Literal['local','inmemory','milvus'] = Field(default='local',validation_alias='AIROBOT_VECTOR_STORE')
    milvus_uri: str = Field(default='http://localhost:19530',validation_alias='AIROBOT_MILVUS_URI')
    milvus_token: SecretStr = Field(default=SecretStr(''),validation_alias='AIROBOT_MILVUS_TOKEN')
    milvus_collection: str = Field(default='retrade_langgraph_kb',validation_alias='AIROBOT_MILVUS_COLLECTION')
    milvus_reset: bool = Field(default=False,validation_alias='AIROBOT_MILVUS_RESET_ON_START')
    top_k: int = Field(default=5,ge=1,le=20,validation_alias='AIROBOT_TOP_K')
    chunk_size: int = Field(default=500,ge=100,le=2000,validation_alias='AIROBOT_CHUNK_SIZE')
    chunk_overlap: int = Field(default=80,ge=0,validation_alias='AIROBOT_CHUNK_OVERLAP')
    vector_k: int = Field(default=15,ge=1,le=100,validation_alias='AIROBOT_HYBRID_VECTOR_TOP_K')
    bm25_k: int = Field(default=15,ge=1,le=100,validation_alias='AIROBOT_HYBRID_BM25_TOP_K')
    fusion_k: int = Field(default=10,ge=1,le=100,validation_alias='AIROBOT_HYBRID_FUSION_TOP_K')
    redis_url: SecretStr = SecretStr('')
    cache_enabled: bool = Field(default=True,validation_alias='AIROBOT_CACHE_ENABLED')
    cache_ttl_seconds: int = Field(default=300,ge=1,le=86400)
    rate_limit_per_minute: int = Field(default=60,ge=1,validation_alias='AIROBOT_RATELIMIT_PER_MINUTE')
    max_handoffs: int = Field(default=3,ge=1,le=10)
    max_agent_steps: int = Field(default=12,ge=4,le=50)
    max_request_seconds: int = Field(default=180,ge=10,le=600)
    max_upload_mb: int = Field(default=10,ge=1,le=30)
    async_database_url: SecretStr = SecretStr('')
    langgraph_database_url: SecretStr = SecretStr('')

    @model_validator(mode='after')
    def validate_settings(self):
        if not self.rerank_api_key.get_secret_value() and self.siliconflow_api_key.get_secret_value():
            self.rerank_api_key = self.siliconflow_api_key
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('CHUNK_OVERLAP must be smaller than CHUNK_SIZE')
        if self.milvus_reset:
            raise ValueError('Startup collection deletion is forbidden. Use a new collection name.')
        if not isinstance(json.loads(self.llm_extra_body), dict):
            raise ValueError('AIROBOT_LLM_EXTRA_BODY must be a JSON object')
        if self.app_env == 'prod':
            if self.app_mode == 'offline':
                raise ValueError('Offline scripted model cannot run in prod')
            if 'dev-' in self.auth_secret.get_secret_value() or len(self.auth_secret.get_secret_value()) < 32:
                raise ValueError('Set a random AUTH_SECRET (at least 32 chars)')
            if 'dev-' in self.admin_api_key.get_secret_value() or len(self.admin_api_key.get_secret_value()) < 24:
                raise ValueError('Set a random ADMIN_API_KEY')
        if self.app_mode == 'live':
            if not self.llm_api_key.get_secret_value():
                raise ValueError('Live mode requires AIROBOT_LLM_API_KEY')
            if not self.embedding_api_key.get_secret_value():
                raise ValueError('Live mode requires AIROBOT_EMBEDDING_API_KEY')
        return self

    def public_info(self):
        return {'app_env': self.app_env, 'mode': self.app_mode, 'app_mode': self.app_mode, 'llm_model': self.llm_model,
                'embedding_model': self.embedding_model, 'vector_store': self.vector_store,
                'checkpoint_backend': self.checkpoint_backend, 'storage_backend': self.storage_backend,
                'rerank_provider': 'siliconflow', 'rerank_model': self.rerank_model,
                'redis_configured': bool(self.redis_url.get_secret_value()),
                'orders': 'simulated', 'refunds': 'simulated', 'version': '0.1.0'}
