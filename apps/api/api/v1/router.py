from fastapi import APIRouter

from api.v1.endpoints.account import router as account_router
from api.v1.endpoints.agent import router as agent_router
from api.v1.endpoints.ai import router as ai_router
from api.v1.endpoints.auth import router as auth_router
from api.v1.endpoints.chat import router as chat_router
from api.v1.endpoints.cli import router as cli_router
from api.v1.endpoints.conversations import router as conversations_router
from api.v1.endpoints.documents import router as documents_router
from api.v1.endpoints.embedding_profiles import router as embedding_profiles_router
from api.v1.endpoints.evals import promote_router as evals_promote_router
from api.v1.endpoints.evals import router as evals_router
from api.v1.endpoints.invitations import router as invitations_router
from api.v1.endpoints.production import router as production_router
from api.v1.endpoints.provider_configs import router as provider_configs_router
from api.v1.endpoints.retrieval import router as retrieval_router
from api.v1.endpoints.users import router as users_router
from api.v1.endpoints.workspaces import router as workspaces_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(workspaces_router)
router.include_router(invitations_router)
router.include_router(documents_router)
router.include_router(provider_configs_router)
router.include_router(cli_router)
router.include_router(retrieval_router)
router.include_router(chat_router)
router.include_router(conversations_router)
router.include_router(production_router)
router.include_router(account_router)
router.include_router(ai_router)
router.include_router(agent_router)
router.include_router(embedding_profiles_router)
router.include_router(evals_router)
router.include_router(evals_promote_router)


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}
