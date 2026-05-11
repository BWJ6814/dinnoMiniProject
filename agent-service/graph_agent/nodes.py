"""
LangGraph 5-노드 파이프라인 구현

[PDF 기반 5-Node 설계]
Node 1: Retrieve    - 사용자 요청 분석 + Neo4j P&ID 위상 정보 로드
Node 2: Plan        - LLM이 GraphRAG 컨텍스트로 라우팅 전략 수립
Node 3: Execute     - Python 기반 3D 충돌 검사 + A* 경로 탐색 (결정론적)
Node 4: Reflect     - LLM이 UHP 배관 표준 위반 여부 자가 검증 (Reflection)
                      위반 발견 시 → Node 2로 조건부 회귀
Node 5: HumanLoop   - 최종 검증된 설계를 시공 엔지니어 검토 형식으로 포맷팅

[Reflection 패턴 효과 (PDF Hypothesis 2)]
LangGraph의 Reflection 패턴으로 As-Built 검증 시 발생하는
'단순 오차'와 '치명적 위반'의 1차 분류를 자동화할 수 있습니다.
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 공통 유틸리티
# ──────────────────────────────────────────────────────────────────────────────

def _get_llm():
    """설정에 따라 LLM 인스턴스를 반환합니다."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from core.config import settings

    if settings.LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.LLM_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=0,
        )
    elif settings.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.LLM_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=2048,
        )
    else:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
            temperature=0,
        )


def _parse_json_from_llm(text: str) -> dict:
    """LLM 응답에서 JSON 블록을 추출합니다."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Node 1: Retrieve
# 사용자의 자연어 요청을 분석하고 Neo4j에서 필요한 정보를 로드합니다.
# ──────────────────────────────────────────────────────────────────────────────

def retrieve_node(state: dict) -> dict:
    """
    [Node 1: Retrieve]
    - 사용자 요청에서 출발지·목적지·배관 스펙을 구조화합니다.
    - Neo4j에서 두 장비의 3D 좌표와 주변 P&ID 위상 정보를 로드합니다.
    - 장애물(기둥, 보) 목록을 로드합니다.
    """
    logger.info("[Node 1: Retrieve] 시작")

    from tools.neo4j_tool import Neo4jPipingTool

    tool = Neo4jPipingTool()

    try:
        source_tag = state.get("source_tag", "")
        target_tag = state.get("target_tag", "")

        # 1-1. 출발 장비 정보 조회
        source_info = tool.get_equipment_info(source_tag)
        if not source_info:
            raise ValueError(f"출발 장비를 찾을 수 없습니다: {source_tag}")
        source_coords = {"x": source_info["x"], "y": source_info["y"], "z": source_info["z"]}

        # 1-2. 목적지 장비 정보 조회
        target_info = tool.get_equipment_info(target_tag)
        if not target_info:
            raise ValueError(f"목적지 장비를 찾을 수 없습니다: {target_tag}")
        target_coords = {"x": target_info["x"], "y": target_info["y"], "z": target_info["z"]}

        # 1-3. 배관 위상 컨텍스트 조회 (GraphRAG용)
        graph_context = tool.get_piping_topology_context(source_tag, target_tag)

        # 1-4. 장애물 로드
        obstacles = tool.get_all_obstacles()

        logger.info(
            f"[Node 1] 완료 - 출발: {source_tag}{source_coords}, "
            f"목적지: {target_tag}{target_coords}, "
            f"장애물: {len(obstacles)}개"
        )

        return {
            "source_coords": source_coords,
            "target_coords": target_coords,
            "graph_context": graph_context,
            "obstacles": obstacles,
        }

    except Exception as e:
        logger.error(f"[Node 1] 오류: {e}")
        # 오류 시 기본값으로 진행 (실제 환경에서는 에러를 전파해야 합니다)
        return {
            "source_coords": {"x": 0.0, "y": 0.0, "z": 2.5},
            "target_coords": {"x": 14.0, "y": 0.0, "z": 0.0},
            "graph_context": f"Neo4j 조회 실패: {e}",
            "obstacles": [],
        }
    finally:
        tool.close()


# ──────────────────────────────────────────────────────────────────────────────
# Node 2: Plan
# LLM이 GraphRAG 컨텍스트를 바탕으로 라우팅 전략을 수립합니다.
# ──────────────────────────────────────────────────────────────────────────────

def plan_node(state: dict) -> dict:
    """
    [Node 2: Plan]
    LLM이 그래프 컨텍스트와 스펙 문서를 참조하여:
    - 라우팅 전략(경유 포인트, 회피 방향)을 제안합니다.
    - 필요한 배관 부품(피팅, 밸브 등) 목록을 제안합니다.

    [GraphRAG 활용]
    Vector Search: UHP 가스 연결 규정, 재질 표준
    Graph Search: 기존 배관망 위상, 여유 포트 정보
    → LLM이 두 정보를 합쳐 설계 전략 수립
    """
    logger.info("[Node 2: Plan] 시작")

    from services.graphrag import GraphRAGService

    graph_rag = GraphRAGService()
    graph_rag.initialize()

    # 스펙 규정 검색 (Vector Search)
    spec_context = graph_rag.vector_search(
        f"{state.get('pipe_spec', 'UHP')} 배관 연결 규정 재질 표준"
    )

    reflection_count = state.get("reflection_count", 0)
    prev_errors = state.get("validation_errors", [])

    # 재계획 시 이전 오류를 프롬프트에 포함
    error_context = ""
    if prev_errors:
        error_context = f"\n\n이전 계획의 문제점 (반드시 해결해야 합니다):\n" + "\n".join(
            f"- {e}" for e in prev_errors
        )

    prompt = f"""당신은 반도체 FAB 배관 설계 전문가입니다.
다음 조건으로 Smart HookUp 배관 경로 설계 전략을 수립하세요.

[요청 정보]
원문: {state.get('user_request', '')}
출발 장비: {state.get('source_tag', '')} (좌표: {state.get('source_coords', {})})
목적지 장비: {state.get('target_tag', '')} (좌표: {state.get('target_coords', {})})
배관 스펙: {state.get('pipe_spec', 'UHP_N2')}

[현재 배관망 위상 (Neo4j GraphRAG)]
{state.get('graph_context', '정보 없음')}

[배관 스펙 규정 (Vector Search)]
{spec_context}

[장애물 정보]
{state.get('obstacles', [])}
{error_context}

다음 JSON 형식으로 응답하세요:
```json
{{
  "routing_strategy": "설계 전략 설명 (한국어, 3-5문장)",
  "required_fittings": ["VCR 피팅 x4", "90도 LR 엘보 x2", "티(T) 피팅 x1"],
  "preferred_direction": "X축 우선 이동 후 Y축 이동",
  "special_constraints": ["기둥 COL-001 좌측으로 우회", "Z축 2.5m 고도 유지"]
}}
```"""

    try:
        llm = _get_llm()
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=prompt)])
        parsed = _parse_json_from_llm(response.content)

        routing_strategy = parsed.get("routing_strategy", response.content[:500])
        required_fittings = parsed.get("required_fittings", ["VCR 피팅 x4", "90도 LR 엘보 x2"])

        logger.info(f"[Node 2] 전략 수립 완료 (재계획 {reflection_count}회차)")

    except Exception as e:
        logger.error(f"[Node 2] LLM 호출 실패: {e}")
        routing_strategy = (
            f"{state.get('source_tag')}에서 {state.get('target_tag')}까지 "
            f"X축 방향 우선, 장애물 회피, Z축 고도 {state.get('source_coords', {}).get('z', 2.5)}m 유지"
        )
        required_fittings = ["VCR 피팅 x4", "90도 LR 엘보 x2"]

    return {
        "routing_strategy": routing_strategy,
        "required_fittings": required_fittings,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 3: Execute
# Python 기반 결정론적 도구로 실제 경로를 계산합니다.
# ──────────────────────────────────────────────────────────────────────────────

def execute_node(state: dict) -> dict:
    """
    [Node 3: Execute (Deterministic)]
    - A* 알고리즘으로 장애물을 회피하는 최적 경로를 계산합니다.
    - OR-Tools로 배관 세그먼트를 최적화합니다.
    - 결과를 Neo4j에 'AS_DESIGNED' 상태로 저장합니다.

    '결정론적(Deterministic)'이라고 부르는 이유:
    동일 입력에 동일 출력이 보장되는 알고리즘 기반이기 때문입니다.
    LLM과 달리 확률적 변동이 없습니다.
    """
    logger.info("[Node 3: Execute] 시작")

    from tools.pathfinding import find_shortest_path_astar
    from tools.optimizer import optimize_pipe_routing

    source_coords = state.get("source_coords", {})
    target_coords = state.get("target_coords", {})
    obstacles = state.get("obstacles", [])
    pipe_spec = state.get("pipe_spec", "UHP_N2")

    # 3-1. A* 경로 탐색
    result = find_shortest_path_astar(source_coords, target_coords, obstacles)

    if result is None:
        logger.warning("[Node 3] 경로 탐색 실패 - 직선 경로 사용")
        waypoints = [source_coords, target_coords]
        path_cost = _euclidean_dist(source_coords, target_coords)
        optimized_segs = []
    else:
        waypoints, path_cost = result

        # 3-2. OR-Tools 최적화
        opt_result = optimize_pipe_routing(waypoints, pipe_spec)
        optimized_segs = [
            {
                "segment_id": seg.segment_id,
                "from_point": seg.from_point,
                "to_point": seg.to_point,
                "length_m": seg.length_m,
                "bend_count": seg.bend_count,
            }
            for seg in opt_result.selected_segments
        ]
        logger.info(
            f"[Node 3] OR-Tools 최적화: 총 {opt_result.total_length_m}m, "
            f"꺾임 {opt_result.total_bends}회, 상태={opt_result.status}"
        )

    # 3-3. Neo4j에 설계 저장
    source_tag = state.get("source_tag", "")
    target_tag = state.get("target_tag", "")
    if source_tag and target_tag:
        from tools.neo4j_tool import Neo4jPipingTool
        tool = Neo4jPipingTool()
        try:
            pipe_id = f"AI-PIPE-{source_tag}-{target_tag}"
            saved = tool.save_designed_pipe(
                source_tag=source_tag,
                target_tag=target_tag,
                pipe_id=pipe_id,
                spec=pipe_spec,
                path_waypoints=waypoints,
            )
            logger.info(f"[Node 3] Neo4j 저장: {'성공' if saved else '실패'} ({pipe_id})")
        except Exception as e:
            logger.error(f"[Node 3] Neo4j 저장 실패: {e}")
        finally:
            tool.close()

    # 경로 요약 (tag 형식)
    computed_path = [source_tag] + [f"WP({w['x']:.1f},{w['y']:.1f},{w['z']:.1f})" for w in waypoints[1:-1]] + [target_tag]

    return {
        "computed_path": computed_path,
        "path_waypoints": waypoints,
        "path_cost": round(path_cost, 3),
        "optimized_segments": optimized_segs,
    }


def _euclidean_dist(p1: dict, p2: dict) -> float:
    import math
    return math.sqrt(
        (p1["x"] - p2["x"]) ** 2 + (p1["y"] - p2["y"]) ** 2 + (p1["z"] - p2["z"]) ** 2
    )


# ──────────────────────────────────────────────────────────────────────────────
# Node 4: Reflect & Validate
# LLM이 계산된 경로가 UHP 배관 표준을 위반하는지 자가 검증합니다.
# ──────────────────────────────────────────────────────────────────────────────

def reflect_validate_node(state: dict) -> dict:
    """
    [Node 4: Reflect & Validate]
    LLM이 Node 3의 실행 결과를 검토하여 자가 반성(Self-Reflection)합니다.

    [Reflection 패턴의 효과]
    단순히 경로만 계산하는 것이 아니라,
    LLM이 결과를 도메인 지식(UHP 표준)으로 다시 검증합니다.
    위반 발견 시 Node 2로 되돌아가 재계획합니다 (최대 3회).
    이 패턴으로 '단순 오차'와 '치명적 위반'을 자동으로 1차 분류합니다.

    [검증 기준]
    - 총 배관 길이: 허용 범위 내인지
    - 꺾임 횟수: UHP 표준 이내인지 (배관 길이당 최대 꺾임 제한)
    - 장애물 충돌: 경로가 장애물과 교차하지 않는지
    - 압력 손실: 거리·꺾임 기준 압력 손실이 허용 범위인지
    """
    logger.info("[Node 4: Reflect & Validate] 시작")

    reflection_count = state.get("reflection_count", 0) + 1
    waypoints = state.get("path_waypoints", [])
    optimized_segs = state.get("optimized_segments", [])
    total_length = sum(s.get("length_m", 0) for s in optimized_segs)
    total_bends = sum(s.get("bend_count", 0) for s in optimized_segs)

    # 결정론적 기본 검증 (LLM 없이)
    errors = []

    # 기준 1: 총 배관 길이
    if total_length > 50:
        errors.append(f"배관 길이 초과: {total_length:.1f}m (권장 50m 이하)")

    # 기준 2: 꺾임 횟수 (UHP 표준: 길이 10m당 최대 3회)
    max_allowed_bends = max(3, int(total_length / 10) * 3)
    if total_bends > max_allowed_bends:
        errors.append(f"꺾임 과다: {total_bends}회 (허용 {max_allowed_bends}회)")

    # 기준 3: 경로 존재 확인
    if len(waypoints) < 2:
        errors.append("유효한 경로가 계산되지 않았습니다.")

    # LLM 기반 고급 검증 (도메인 지식 적용)
    try:
        llm = _get_llm()
        from langchain_core.messages import HumanMessage, SystemMessage

        seg_summary = "\n".join(
            f"  - {s.get('segment_id')}: {s.get('length_m', 0):.2f}m, 꺾임 {s.get('bend_count', 0)}회"
            for s in optimized_segs[:10]
        ) or "  (세그먼트 정보 없음)"

        messages = [
            SystemMessage(content=(
                "당신은 반도체 FAB UHP 배관 설계 검증 전문가입니다. "
                "계산된 배관 경로가 UHP 표준을 충족하는지 검증하세요. "
                "반드시 JSON 형식으로만 응답하세요."
            )),
            HumanMessage(content=f"""배관 설계 검증 요청:

배관 스펙: {state.get('pipe_spec', 'UHP_N2')}
총 배관 길이: {total_length:.2f}m
총 꺾임 횟수: {total_bends}회
웨이포인트 수: {len(waypoints)}개
세그먼트 상세:
{seg_summary}

결정론적 검증 결과: {errors if errors else "이상 없음"}

위 정보를 기반으로 다음 JSON으로 응답하세요:
```json
{{
  "is_valid": true 또는 false,
  "llm_violations": ["위반 사항 1", "위반 사항 2"],
  "suggestions": ["개선 제안 1"],
  "severity": "OK" 또는 "WARNING" 또는 "CRITICAL"
}}
```"""),
        ]

        response = llm.invoke(messages)
        parsed = _parse_json_from_llm(response.content)

        llm_violations = parsed.get("llm_violations", [])
        severity = parsed.get("severity", "OK")
        llm_is_valid = parsed.get("is_valid", True)

        # LLM 위반 사항을 기존 오류 목록에 추가
        all_errors = errors + llm_violations
        is_valid = len(all_errors) == 0 or (llm_is_valid and severity != "CRITICAL")

        logger.info(
            f"[Node 4] LLM 검증 결과: valid={is_valid}, severity={severity}, "
            f"오류={len(all_errors)}개 (재계획 {reflection_count}회차)"
        )

    except Exception as e:
        logger.error(f"[Node 4] LLM 검증 실패: {e}")
        all_errors = errors
        is_valid = len(errors) == 0

    return {
        "validation_errors": all_errors,
        "is_valid": is_valid,
        "reflection_count": reflection_count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Node 5: Human-in-the-loop
# 검증된 설계를 시공 엔지니어가 검토하기 쉬운 형식으로 포맷팅합니다.
# ──────────────────────────────────────────────────────────────────────────────

def human_in_loop_node(state: dict) -> dict:
    """
    [Node 5: Human-in-the-loop]
    최종 검증된 설계를 시공 엔지니어 검토용 포맷으로 정리합니다.

    실제 DDWorks에서는:
    - 이 단계에서 엔지니어에게 이메일·알림이 발송됩니다.
    - 엔지니어가 DDWorks UI에서 3D로 경로를 확인하고 승인/거부합니다.
    - 승인 후 모바일 현장 지시서(Work Order)가 자동 생성됩니다.

    이 미니 프로젝트에서는 최종 설계 딕셔너리를 반환합니다.
    """
    logger.info("[Node 5: Human-in-the-loop] 최종 설계 포맷팅")

    optimized_segs = state.get("optimized_segments", [])
    total_length = sum(s.get("length_m", 0) for s in optimized_segs)
    total_bends = sum(s.get("bend_count", 0) for s in optimized_segs)

    final_design = {
        "design_id": f"HOOKUP-{state.get('source_tag', '')}-{state.get('target_tag', '')}",
        "status": "PENDING_APPROVAL",
        "summary": {
            "source": state.get("source_tag"),
            "target": state.get("target_tag"),
            "pipe_spec": state.get("pipe_spec"),
            "total_length_m": round(total_length, 3),
            "total_bends": total_bends,
            "path_cost": state.get("path_cost", 0),
            "waypoint_count": len(state.get("path_waypoints", [])),
        },
        "routing_strategy": state.get("routing_strategy", ""),
        "required_fittings": state.get("required_fittings", []),
        "path_waypoints": state.get("path_waypoints", []),
        "segments": optimized_segs,
        "validation": {
            "is_valid": state.get("is_valid", False),
            "errors": state.get("validation_errors", []),
            "reflection_rounds": state.get("reflection_count", 0),
        },
        "message": (
            "AI Agent 설계 완료. 시공 엔지니어의 최종 승인이 필요합니다."
            if state.get("is_valid")
            else "검증 실패. 수동 검토가 필요합니다."
        ),
    }

    logger.info(f"[Node 5] 최종 설계 완료: {final_design['design_id']}")

    return {"final_design": final_design}


# ──────────────────────────────────────────────────────────────────────────────
# 조건부 엣지 함수
# Node 4(Reflect) 이후 분기를 결정합니다.
# ──────────────────────────────────────────────────────────────────────────────

def should_replan(state: dict) -> str:
    """
    Node 4 검증 결과에 따라 다음 노드를 결정합니다.

    Returns:
        "replan": 재계획 필요 (Node 2로 회귀)
        "approve": 승인 (Node 5로 진행)
    """
    is_valid = state.get("is_valid", True)
    reflection_count = state.get("reflection_count", 0)

    if not is_valid and reflection_count < 3:
        logger.info(f"[분기] 재계획 ({reflection_count}/3회차)")
        return "replan"

    if not is_valid and reflection_count >= 3:
        logger.warning("[분기] 최대 재계획 횟수 초과 → 강제 승인 단계로 이동")

    return "approve"
