"""
Main Service - DDWorks-Mini API Gateway (포트 8000)

[역할]
- 외부 클라이언트의 단일 진입점 (Single Entry Point)
- agent-service(8001)와의 통신 조율
- As-Built 정합성 검증 (Open3D ICP)

[엔드포인트 목록]
POST /api/v1/agent/hookup-design   → AI Agent 배관 자동 설계
POST /api/v1/verify/consistency    → As-Built vs As-Designed 정합성 검증
GET  /api/v1/graph/equipment       → 현재 배관망 상태 조회
POST /api/v1/graph/query           → GraphRAG 자연어 질의
POST /api/v1/graph/seed            → 샘플 데이터 삽입 (개발용)
"""

import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

# 라우터 임포트 (로컬 실행과 Docker 환경 모두 지원)
try:
    from main_service.routers.agent import router as agent_router
    from main_service.routers.verify import router as verify_router
    from main_service.routers.graph import router as graph_router
except ImportError:
    from routers.agent import router as agent_router
    from routers.verify import router as verify_router
    from routers.graph import router as graph_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DDWorks-Mini API Gateway",
    description=(
        "반도체 FAB 스마트 설계 플랫폼 DDWorks의 미니 버전.\n\n"
        "**주요 기능:**\n"
        "- Smart HookUp 배관 자동 설계 (LangGraph AI Agent)\n"
        "- As-Built vs As-Designed 3D 정합성 검증 (Open3D ICP)\n"
        "- GraphRAG 기반 배관망 지식 질의응답\n\n"
        "**서비스 구조:** main-service(8000) ↔ agent-service(8001) ↔ Neo4j"
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(agent_router, prefix="/api/v1/agent", tags=["Agent - Smart HookUp 설계"])
app.include_router(verify_router, prefix="/api/v1/verify", tags=["Verify - 정합성 검증"])
app.include_router(graph_router, prefix="/api/v1/graph", tags=["Graph - 배관망 조회/질의"])


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": "DDWorks-Mini API Gateway",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "hookup_design": "POST /api/v1/agent/hookup-design",
            "consistency_verify": "POST /api/v1/verify/consistency",
            "equipment_graph": "GET /api/v1/graph/equipment",
            "graph_query": "POST /api/v1/graph/query",
            "seed_data": "POST /api/v1/graph/seed",
        },
    }


@app.get("/health", tags=["Root"])
async def health():
    """서비스 헬스 체크. agent-service 연결 상태도 확인합니다."""
    try:
        from main_service.services.agent_client import check_agent_health
    except ImportError:
        from services.agent_client import check_agent_health

    agent_healthy = await check_agent_health()
    return {
        "status": "healthy",
        "service": "main-service",
        "port": 8000,
        "dependencies": {
            "agent_service": "healthy" if agent_healthy else "unreachable",
        },
    }


@app.on_event("startup")
async def startup_event():
    logger.info("Main Service 시작 (포트 8000)")
    logger.info("Swagger UI: http://localhost:8000/docs")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
