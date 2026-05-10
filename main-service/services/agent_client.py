"""
Agent Service HTTP 클라이언트 모듈

[마이크로서비스 간 통신]
main-service(포트 8000)가 agent-service(포트 8001)를 HTTP로 호출합니다.
httpx를 사용하는 이유:
- requests와 달리 비동기(async/await) 지원
- FastAPI의 비동기 환경과 자연스럽게 통합
- 타임아웃, 재시도 등 프로덕션 기능 내장
"""

import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.config import settings

logger = logging.getLogger(__name__)

# Agent Service 기본 URL (설정에서 읽어옴)
AGENT_BASE_URL = settings.AGENT_SERVICE_URL

# HTTP 클라이언트 타임아웃 설정
# AI 추론은 시간이 걸리므로 넉넉하게 설정 (120초)
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=5.0)


async def run_hookup_agent(
    user_request: str,
    source_tag: str,
    target_tag: str,
    pipe_spec: str = "UHP_N2",
) -> dict:
    """
    Agent Service의 LangGraph 파이프라인을 호출합니다.
    main-service가 이 함수를 통해 AI 설계를 요청합니다.
    """
    payload = {
        "user_request": user_request,
        "source_tag": source_tag,
        "target_tag": target_tag,
        "pipe_spec": pipe_spec,
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            logger.info(f"Agent Service 호출: {AGENT_BASE_URL}/internal/run-hookup-agent")
            response = await client.post(
                f"{AGENT_BASE_URL}/internal/run-hookup-agent",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError:
            logger.error("Agent Service 연결 실패. agent-service가 실행 중인지 확인하세요.")
            raise RuntimeError("Agent Service에 연결할 수 없습니다. (포트 8001 확인)")
        except httpx.TimeoutException:
            logger.error("Agent Service 응답 타임아웃 (120초 초과)")
            raise RuntimeError("Agent Service 타임아웃. AI 추론 시간이 초과되었습니다.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Agent Service 오류 응답: {e.response.status_code}")
            raise RuntimeError(f"Agent Service 오류: {e.response.text}")


async def get_equipment_graph() -> dict:
    """
    Agent Service에서 Neo4j 장비·배관망 데이터를 조회합니다.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            response = await client.get(f"{AGENT_BASE_URL}/internal/equipment")
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError:
            raise RuntimeError("Agent Service에 연결할 수 없습니다.")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"그래프 조회 실패: {e.response.text}")


async def graph_query(query: str) -> dict:
    """
    Agent Service의 GraphRAG로 자연어 배관망 질의를 실행합니다.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        try:
            response = await client.post(
                f"{AGENT_BASE_URL}/internal/graph-query",
                json={"query": query},
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError:
            raise RuntimeError("Agent Service에 연결할 수 없습니다.")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"GraphRAG 질의 실패: {e.response.text}")


async def seed_agent_database() -> dict:
    """Agent Service를 통해 Neo4j에 샘플 데이터를 삽입합니다."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            response = await client.post(f"{AGENT_BASE_URL}/internal/seed-database")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise RuntimeError(f"데이터베이스 시드 실패: {e}")


async def check_agent_health() -> bool:
    """Agent Service의 헬스 상태를 확인합니다."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        try:
            response = await client.get(f"{AGENT_BASE_URL}/health")
            return response.status_code == 200
        except Exception:
            return False
