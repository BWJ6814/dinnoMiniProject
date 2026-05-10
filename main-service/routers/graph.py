"""
그래프 DB 조회 및 GraphRAG 질의 라우터

GET  /api/v1/graph/equipment    - 현재 장비·배관망 상태 조회
POST /api/v1/graph/query        - 자연어 배관망 질의 (GraphRAG)
POST /api/v1/graph/seed         - 샘플 데이터 삽입 (개발용)
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from main_service.services.agent_client import (
        get_equipment_graph,
        graph_query,
        seed_agent_database,
    )
except ImportError:
    from services.agent_client import (
        get_equipment_graph,
        graph_query,
        seed_agent_database,
    )

logger = logging.getLogger(__name__)
router = APIRouter()


class GraphQueryRequest(BaseModel):
    """GraphRAG 자연어 질의 요청 스키마."""

    query: str = Field(
        ...,
        description="자연어 배관망 질의",
        examples=[
            "N2 가스 라인을 E-201 장비에 연결하기 위한 규정과 현재 여유 포트를 찾아줘.",
            "GAS-N2-001에서 CHAMBER-A까지의 배관 경로를 설명해줘.",
            "UHP 배관 재질 표준은 무엇인가요?",
        ],
    )


@router.get("/equipment", summary="현재 배관망 그래프 조회")
async def get_equipment():
    """
    Neo4j에 저장된 현재 장비 및 배관망 상태를 조회합니다.

    agent-service(8001)를 통해 Neo4j에서 데이터를 가져옵니다.
    """
    try:
        data = await get_equipment_graph()
        return data
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/query", summary="GraphRAG 자연어 배관망 질의")
async def query_graph(request: GraphQueryRequest):
    """
    자연어로 배관망에 대한 질의를 합니다.

    **DINNO 맞춤형 GraphRAG 처리 흐름:**
    1. Vector Search: 배관 스펙·규정 문서에서 관련 내용 검색
    2. Graph Search: Neo4j Cypher로 배관 위상·연결성 검색
    3. LLM 답변 생성: 두 컨텍스트를 합쳐 환각 없는 정확한 답변 생성

    **예시 질의:**
    - "GAS-N2-001에서 CHAMBER-A까지 영향받는 밸브 목록을 알려줘"
    - "UHP N2 배관에 적합한 재질은 무엇인가요?"
    - "현재 AS_DESIGNED 상태인 배관 목록을 보여줘"
    """
    try:
        result = await graph_query(request.query)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/seed", summary="샘플 FAB 데이터 삽입 (개발용)")
async def seed_database():
    """
    Neo4j에 반도체 FAB 샘플 데이터를 삽입합니다.
    개발 및 테스트 목적으로 사용합니다.

    **삽입 데이터:**
    - 장비 10개 (가스 공급 장치, 챔버, 밸브, 펌프 등)
    - 배관 연결 9개 (AS_DESIGNED 상태)
    - 장애물 4개 (기둥, 보)
    """
    try:
        result = await seed_agent_database()
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
