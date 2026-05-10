"""
LangGraph StateGraph 파이프라인 컴파일 모듈

[StateGraph 구조]
retrieve → plan → execute → reflect → (조건부) → plan (재계획)
                                                 → human_loop → END

[그래프 컴파일 원리]
compile()을 호출하면 LangGraph가 그래프를 정적으로 분석하여:
1. 도달 불가능한 노드 탐지
2. 무한 루프 가능성 경고
3. 체크포인터(Checkpointer) 연결 (실행 상태 저장 가능)

compile()의 결과물인 CompiledGraph는
invoke() / stream() / astream() 메서드로 실행합니다.
"""

import logging

from langgraph.graph import StateGraph, END

from graph_agent.state import AgentState
from graph_agent.nodes import (
    execute_node,
    human_in_loop_node,
    plan_node,
    reflect_validate_node,
    retrieve_node,
    should_replan,
)

logger = logging.getLogger(__name__)


def build_hookup_pipeline():
    """
    Smart HookUp 설계 자동화 LangGraph 파이프라인을 빌드합니다.

    Returns:
        CompiledGraph: invoke()로 실행 가능한 컴파일된 그래프
    """

    # ── 1. StateGraph 초기화 ────────────────────────────────────────────
    # AgentState TypedDict를 상태 스키마로 사용
    workflow = StateGraph(AgentState)

    # ── 2. 노드 등록 ────────────────────────────────────────────────────
    # 각 노드는 (state: AgentState) → dict 형태의 함수입니다.
    # 반환된 dict의 키만 state에 병합됩니다.
    workflow.add_node("retrieve", retrieve_node)    # Node 1: P&ID 위상 로드
    workflow.add_node("plan", plan_node)            # Node 2: LLM 전략 수립
    workflow.add_node("execute", execute_node)      # Node 3: A* + OR-Tools 실행
    workflow.add_node("reflect", reflect_validate_node)  # Node 4: LLM 자가 검증
    workflow.add_node("human_loop", human_in_loop_node)  # Node 5: 엔지니어 검토

    # ── 3. 진입점 설정 ──────────────────────────────────────────────────
    workflow.set_entry_point("retrieve")

    # ── 4. 고정 엣지 (항상 실행) ────────────────────────────────────────
    workflow.add_edge("retrieve", "plan")     # retrieve 완료 → plan 시작
    workflow.add_edge("plan", "execute")      # plan 완료 → execute 시작
    workflow.add_edge("execute", "reflect")   # execute 완료 → reflect 시작
    workflow.add_edge("human_loop", END)      # human_loop 완료 → 종료

    # ── 5. 조건부 엣지 (Reflect 결과에 따른 분기) ───────────────────────
    # should_replan() 함수의 반환값에 따라 다음 노드가 결정됩니다.
    # "replan" → plan 노드로 회귀 (최대 3회)
    # "approve" → human_loop 노드로 진행
    workflow.add_conditional_edges(
        "reflect",          # 이 노드의 출력을 기준으로 분기
        should_replan,      # 분기 결정 함수
        {
            "replan": "plan",          # 재계획: plan 노드로 돌아감
            "approve": "human_loop",   # 승인: human_loop 노드로 진행
        },
    )

    # ── 6. 컴파일 ────────────────────────────────────────────────────────
    # interrupt_before=["human_loop"] 옵션으로 human-in-the-loop 구현 가능
    # 실제 DDWorks에서는 엔지니어가 UI에서 승인 버튼을 누를 때까지 대기합니다.
    app = workflow.compile()

    logger.info("LangGraph 파이프라인 컴파일 완료 (5-노드)")
    return app


# 전역 파이프라인 인스턴스 (싱글톤으로 관리)
_pipeline = None


def get_pipeline():
    """파이프라인 싱글톤 인스턴스를 반환합니다."""
    global _pipeline
    if _pipeline is None:
        _pipeline = build_hookup_pipeline()
    return _pipeline
