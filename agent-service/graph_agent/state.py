"""
LangGraph 에이전트의 상태(State) 정의 모듈

[LangGraph State 관리 원리]
LangGraph는 에이전트를 '상태 기계(State Machine)'로 모델링합니다.
- State: 모든 노드가 읽고 쓸 수 있는 공유 메모리(딕셔너리)입니다.
- 각 노드는 state를 입력받아, 변경할 필드만 담은 딕셔너리를 반환합니다.
- LangGraph가 반환된 딕셔너리를 이전 state와 병합(merge)합니다.

이 패턴 덕분에:
1. 각 노드는 독립적으로 테스트 가능합니다.
2. 노드 간 명시적인 데이터 흐름이 보장됩니다.
3. 조건부 분기(Conditional Edge)를 state 값으로 결정할 수 있습니다.
"""

from typing import TypedDict


class AgentState(TypedDict):
    """
    Smart HookUp 설계 에이전트의 전체 상태.

    Node 1 (Retrieve)    → graph_context, obstacles 채움
    Node 2 (Plan)        → routing_strategy, required_fittings 채움
    Node 3 (Execute)     → computed_path, path_cost 채움
    Node 4 (Reflect)     → validation_errors, is_valid 채움
    Node 5 (Human Loop)  → final_design 채움
    """

    # ── 입력 (사용자 요청) ──────────────────────────
    user_request: str          # 자연어 요청 원문
    source_tag: str            # 출발 장비 tag (예: "GAS-N2-001")
    target_tag: str            # 목적지 장비 tag (예: "CHAMBER-A")
    pipe_spec: str             # 배관 스펙 (예: "UHP_N2", "CCSS_HF")

    # ── Node 1: Retrieve 결과 ──────────────────────
    graph_context: str         # Neo4j에서 조회한 P&ID 위상 정보 (텍스트)
    source_coords: dict        # 출발 장비 3D 좌표 {"x": float, "y": float, "z": float}
    target_coords: dict        # 목적지 장비 3D 좌표
    obstacles: list[dict]      # 장애물 목록 [{"obs_id": str, "x": float, ...}]

    # ── Node 2: Plan 결과 ──────────────────────────
    routing_strategy: str      # LLM이 제안한 라우팅 전략 (텍스트)
    required_fittings: list[str]  # 필요한 배관 부품 목록 (엘보, 티 등)

    # ── Node 3: Execute 결과 ──────────────────────
    computed_path: list[str]   # A* 알고리즘이 계산한 경로 (장비 tag 리스트)
    path_waypoints: list[dict] # 경로상의 3D 좌표 목록 [{"x": ..., "y": ..., "z": ...}]
    path_cost: float           # 경로 총 비용 (길이 + 벤드 페널티)
    optimized_segments: list[dict]  # OR-Tools 최적화된 세그먼트 정보

    # ── Node 4: Reflect & Validate 결과 ───────────
    validation_errors: list[str]  # UHP 기준 위반 사항 목록
    is_valid: bool             # 검증 통과 여부
    reflection_count: int      # 재계획 횟수 (무한루프 방지, 최대 3회)

    # ── Node 5: Human-in-the-loop 결과 ────────────
    final_design: dict         # 최종 설계 결과 (엔지니어 검토용 포맷)
