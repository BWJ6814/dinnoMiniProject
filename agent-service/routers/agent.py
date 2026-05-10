"""
Agent Service 라우터 모듈

이 서비스(포트 8001)는 LangGraph AI 에이전트를 실행하고
그래프 DB 조회를 담당합니다.

main-service(포트 8000)에서 이 서비스를 HTTP로 호출합니다.
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# 상위 디렉토리(프로젝트 루트)를 sys.path에 추가
# core/, agent-service/ 등을 import할 수 있게 합니다
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_agent.pipeline import get_pipeline
from graph_agent.state import AgentState
from services.graphrag import GraphRAGService
from tools.neo4j_tool import Neo4jPipingTool

logger = logging.getLogger(__name__)
router = APIRouter()

# GraphRAG 서비스 싱글톤
_graphrag_service = None


def get_graphrag() -> GraphRAGService:
    global _graphrag_service
    if _graphrag_service is None:
        _graphrag_service = GraphRAGService()
        _graphrag_service.initialize()
    return _graphrag_service


# ─────────────────────────────────────────────────────────────
# Request / Response 스키마
# ─────────────────────────────────────────────────────────────

class HookupDesignRequest(BaseModel):
    user_request: str = Field(..., description="자연어 배관 설계 요청")
    source_tag: str = Field(..., description="출발 장비 태그 (예: GAS-N2-001)")
    target_tag: str = Field(..., description="목적지 장비 태그 (예: CHAMBER-A)")
    pipe_spec: str = Field(default="UHP_N2", description="배관 스펙")


class GraphQueryRequest(BaseModel):
    query: str = Field(..., description="자연어 배관망 질의")


# ─────────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────────

@router.post("/run-hookup-agent")
async def run_hookup_agent(request: HookupDesignRequest):
    """
    LangGraph 5-노드 파이프라인을 실행하여 Smart HookUp 배관 경로를 설계합니다.

    main-service의 POST /api/v1/agent/hookup-design 에서 이 엔드포인트를 호출합니다.
    """
    logger.info(f"Agent 실행 요청: {request.source_tag} → {request.target_tag}")

    # 초기 AgentState 구성
    initial_state: AgentState = {
        "user_request": request.user_request,
        "source_tag": request.source_tag,
        "target_tag": request.target_tag,
        "pipe_spec": request.pipe_spec,
        # 이후 노드에서 채워질 필드들
        "graph_context": "",
        "source_coords": {},
        "target_coords": {},
        "obstacles": [],
        "routing_strategy": "",
        "required_fittings": [],
        "computed_path": [],
        "path_waypoints": [],
        "path_cost": 0.0,
        "optimized_segments": [],
        "validation_errors": [],
        "is_valid": False,
        "reflection_count": 0,
        "final_design": {},
    }

    try:
        pipeline = get_pipeline()
        # LangGraph 파이프라인 실행
        final_state = pipeline.invoke(initial_state)

        return {
            "success": True,
            "final_design": final_state.get("final_design", {}),
            "reflection_rounds": final_state.get("reflection_count", 0),
            "is_valid": final_state.get("is_valid", False),
        }

    except Exception as e:
        logger.error(f"Agent 실행 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Agent 실행 실패: {str(e)}")


@router.get("/equipment")
async def get_all_equipment():
    """
    Neo4j에 저장된 모든 장비와 배관망 현황을 반환합니다.
    main-service의 GET /api/v1/graph/equipment 에서 이 엔드포인트를 호출합니다.
    """
    tool = Neo4jPipingTool()
    try:
        equipment = tool.get_all_equipment()
        piping = tool.get_all_piping()
        obstacles = tool.get_all_obstacles()

        return {
            "equipment": equipment,
            "piping": piping,
            "obstacles": obstacles,
            "stats": {
                "equipment_count": len(equipment),
                "pipe_count": len(piping),
                "obstacle_count": len(obstacles),
            },
        }
    except Exception as e:
        logger.error(f"그래프 조회 오류: {e}")
        raise HTTPException(status_code=503, detail=f"Neo4j 조회 실패: {str(e)}")
    finally:
        tool.close()


@router.post("/graph-query")
async def graph_query(request: GraphQueryRequest):
    """
    GraphRAG (Hybrid Search)로 자연어 배관망 질의에 답변합니다.

    [처리 흐름]
    Vector Search (스펙 문서) + GraphCypher (Neo4j 위상) → LLM 답변 생성
    """
    try:
        service = get_graphrag()
        answer = service.hybrid_query(request.query)
        return {"query": request.query, "answer": answer}
    except Exception as e:
        logger.error(f"GraphRAG 질의 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed-database")
async def seed_database():
    """Neo4j에 샘플 FAB 데이터를 삽입합니다. (개발/테스트용)"""
    try:
        from core.seed_data import seed_neo4j
        result = seed_neo4j()
        return {"success": True, "seeded": result}
    except Exception as e:
        logger.error(f"시드 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))
