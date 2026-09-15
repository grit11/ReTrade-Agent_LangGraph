"""Live models retain the original provider endpoint/model/key variables."""
import json
import httpx
from langchain_openai import ChatOpenAI
from retrade_agent.agents.offline import OfflineChatModel

class ModelFactory:
    def __init__(self,settings):
        self.settings=settings
        self.http_client=httpx.Client(timeout=settings.llm_timeout) if settings.app_mode=='live' else None
        self.http_async_client=httpx.AsyncClient(timeout=settings.llm_timeout) if settings.app_mode=='live' else None
        self.chat=(OfflineChatModel() if settings.app_mode=='offline' else ChatOpenAI(
            model=settings.llm_model,api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,max_retries=2,http_client=self.http_client,http_async_client=self.http_async_client,extra_body=json.loads(settings.llm_extra_body)))
    async def structured(self,schema,prompt,message):
        from langchain.messages import HumanMessage, SystemMessage
        runnable=self.chat.with_structured_output(schema,method=self.settings.structured_method)
        system=prompt+'\n输出 JSON，严格遵守此结构：'+json.dumps(schema.model_json_schema(),ensure_ascii=False)
        result=await runnable.ainvoke([SystemMessage(content=system),HumanMessage(content=message)])
        return result if isinstance(result,schema) else schema.model_validate(result)

    async def close(self):
        if self.http_async_client:
            await self.http_async_client.aclose()
        if self.http_client:
            self.http_client.close()
