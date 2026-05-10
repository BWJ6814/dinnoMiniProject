"""
Smart HookUp 설계 요청 라우터

POST /api/v1/agent/hookup-design
- 자연어 요청을 받아 agent-service의 LangGraph 파이프라인을 실행합니다.
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from main_service.services.agent_client import run_hookup_agent
except ImportError:
    from services.agent_client import run_hookup_agent

logger = logging.getLogger(__name__)
router = APIRouter()


class HookupDesignRequest(BaseModel):
    """Smart HookUp 배관 설계 요청 스키마."""

    natural_language_request: str = Field(
        ...,
        description="자연어 배관 설계 요청",
        examples=["N2 가스 공급 장치에서 웨이퍼 챔버 A까지 최단 거리로 배관을 연결해줘. 기둥을 회피해야 해."],
    )
    source_tag: str = Field(
        ...,
        description="출발 장비 태그",
        examples=["GAS-N2-001"],
    )
    target_tag: str = Field(
        ...,
        description="목적지 장비 태그",
        examples=["CHAMBER-A"],
    )
    pipe_spec: str = Field(
        default="UHP_N2",
        description="배관 스펙 (UHP_N2, UHP_AR, CCSS_HF 등)",
    )


@router.post("/hookup-design", summary="Smart HookUp 배관 자동 설계")
async def hookup_design(request: HookupDesignRequest):
    """
    자연어 요청을 받아 LangGraph 5-노드 파이프라인으로 최적 배관 경로를 설계합니다.

    **처리 흐름:**
    1. main-service(8000) → agent-service(8001) HTTP 호출
    2. agent-service: LangGraph 5-노드 파이프라인 실행
       - Node 1 Retrieve: Neo4j에서 P&ID 위상 및 3D 좌표 로드
       - Node 2 Plan: LLM + GraphRAG로 라우팅 전략 수립
       - Node 3 Execute: A* 알고리즘 + OR-Tools 최적화
       - Node 4 Reflect: LLM 자가 검증 (UHP 표준 확인)
       - Node 5 Human Loop: 엔지니어 검토용 설계 포맷팅
    3. 설계 결과를 Neo4j에 AS_DESIGNED 상태로 저장
    4. 최종 설계 결과 반환
    """
    logger.info(
        f"hookup-design 요청: {request.source_tag} → {request.target_tag} "
        f"[{request.pipe_spec}]"
    )

    try:
        result = await run_hookup_agent(
            user_request=request.natural_language_request,
            source_tag=request.source_tag,
            target_tag=request.target_tag,
            pipe_spec=request.pipe_spec,
        )
        return {
            "request_summary": {
                "source": request.source_tag,
                "target": request.target_tag,
                "spec": request.pipe_spec,
            },
            "agent_result": result,
        }

    except RuntimeError as e:
        logger.error(f"hookup-design 오류: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"hookup-design 예상치 못한 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")
