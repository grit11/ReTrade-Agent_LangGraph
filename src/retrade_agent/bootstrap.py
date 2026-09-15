"""Composition root: the only layer that knows all concrete adapters."""
import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from retrade_agent.config import Settings, PROJECT_ROOT
from retrade_agent.storage.sqlite import SqliteRepository
from retrade_agent.storage.cache import LocalCache, RedisCache
from retrade_agent.rag.embeddings import EmbeddingClient
from retrade_agent.rag.vector_local import LocalVectors
from retrade_agent.rag.vector_milvus import MilvusVectors
from retrade_agent.rag.reranker import SiliconFlowReranker
from retrade_agent.rag.retriever import HybridRetriever
from retrade_agent.services.knowledge import KnowledgeService
from retrade_agent.services.orders import OrderService
from retrade_agent.services.after_sales import AfterSalesService
from retrade_agent.services.human import HumanService
from retrade_agent.services.permission import PermissionService


@dataclass
class Container:
    """运行时依赖容器，保存应用启动后共享的服务和适配器实例。"""

    settings: Settings
    repo: object
    permission: object
    cache: object
    knowledge: object
    orders: object
    after_sales: object
    human: object
    workflow: object = None
    startup_warnings: list | None = None


@asynccontextmanager
async def build_container(settings: Settings):
    """build_container 函数，封装该模块中的一段独立处理逻辑。"""
    async with AsyncExitStack() as stack:
        if settings.storage_backend == "postgres":
            from retrade_agent.storage.postgres import create_postgres_repository

            repo = create_postgres_repository(settings)
        else:
            repo = SqliteRepository(settings.data_dir / "business.sqlite")
        await repo.setup(
            json.loads((PROJECT_ROOT / "resources/fixtures/orders.json").read_text(encoding="utf-8"))
        )
        permission = PermissionService()
        cache = (
            RedisCache(settings.redis_url.get_secret_value())
            if settings.redis_url.get_secret_value()
            else LocalCache()
        )
        stack.push_async_callback(cache.close)
        embeddings = EmbeddingClient(settings)
        stack.push_async_callback(embeddings.close)
        vectors = MilvusVectors(settings) if settings.vector_store == "milvus" else LocalVectors()
        stack.push_async_callback(vectors.close)
        reranker = SiliconFlowReranker(settings)
        stack.push_async_callback(reranker.close)
        retriever = HybridRetriever(settings, embeddings, vectors, reranker)
        knowledge = KnowledgeService(settings, repo, retriever, embeddings)
        warnings = []
        try:
            await knowledge.initialize(PROJECT_ROOT / "resources/knowledge")
        except Exception as exc:
            knowledge.last_error = type(exc).__name__
            warnings.append("知识索引未就绪，请在知识中心重新建立索引。")
        orders = OrderService(repo, permission)
        after_sales_service = AfterSalesService(repo, orders)
        human = HumanService(repo, permission)
        # Set serializer policy before importing graph runtime-dependent factories.
        from retrade_agent.storage.checkpoint import open_checkpointer

        saver = await stack.enter_async_context(open_checkpointer(settings))
        from retrade_agent.llm import ModelFactory
        from retrade_agent.agents.knowledge_tools import build_knowledge_tool
        from retrade_agent.agents.order_tools import build_order_tools
        from retrade_agent.agents.handoff_tools import build_handoff_tools
        from retrade_agent.agents.customer import build_agent as build_customer
        from retrade_agent.agents.order import build_agent as build_order
        from retrade_agent.agents.runner import AgentRunner
        from retrade_agent.graph.after_sales import build_after_sales
        from retrade_agent.graph.support import build_parent
        from retrade_agent.workflow import WorkflowService

        models = ModelFactory(settings)
        stack.push_async_callback(models.close)
        agents = {
            "customer": build_customer(
                models.chat, [build_knowledge_tool(knowledge), *build_handoff_tools("customer")]
            ),
            "order": build_order(models.chat, [*build_order_tools(orders), *build_handoff_tools("order")]),
        }
        runner = AgentRunner(settings, agents, cache, knowledge)
        subgraph = build_after_sales(models, orders, after_sales_service, human)
        graph = build_parent(settings, models, runner, subgraph, human, saver)
        c = Container(
            settings,
            repo,
            permission,
            cache,
            knowledge,
            orders,
            after_sales_service,
            human,
            startup_warnings=warnings,
        )
        c.workflow = WorkflowService(c, graph)
        yield c
