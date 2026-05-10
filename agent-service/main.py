"""
Agent Service - LangGraph AI 에이전트 서비스 (포트 8001)

[역할]
- Smart HookUp 배관 설계 LangGraph 파이프라인 실행
- Neo4j 그래프 DB 조회
- GraphRAG 하이브리드 검색

[서비스 분리 이유]
AI 추론(LLM 호출)과 알고리즘 연산은 CPU/메모리를 많이 사용합니다.
main-service(API Gateway, 포트 8000)와 분리하면:
1. AI 서비스를 독립적으로 스케일링할 수 있습니다.
2. AI 서비스 장애가 API Gateway에 영향을 주지 않습니다.
3. 향후 GPU 서버에 별도 배포가 가능합니다.
"""

import logging
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 프로젝트 루트를 sys.path에 추가 (core/ 임포트용)
sys.path.insert(0, str(Path(__file__).parent.parent))

from routers.agent import router as agent_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="DDWorks-Mini Agent Service",
    description=(
        "반도체 FAB Smart HookUp 설계 자동화 AI 에이전트 서비스. "
        "LangGraph 5-노드 파이프라인으로 배관 경로를 자율 설계합니다."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 설정 (main-service에서의 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://main-service:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(agent_router, prefix="/internal", tags=["Agent Internal API"])


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트. main-service가 이 서비스의 상태를 확인합니다."""
    return {"status": "healthy", "service": "agent-service", "port": 8001}


@app.on_event("startup")
async def startup_event():
    logger.info("Agent Service 시작 (포트 8001)")
    logger.info("Neo4j 연결 상태는 첫 요청 시 확인됩니다.")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info",
    )
