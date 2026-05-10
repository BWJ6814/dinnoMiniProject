"""
OR-Tools를 이용한 배관 최적화 모듈

[OR-Tools CP-SAT Solver를 사용하는 이유]
A* 알고리즘은 단일 목적 함수(최단거리)만 최적화하지만,
실제 FAB 배관 설계는 복수의 제약과 목적이 있습니다:

1. 제약 조건 (Constraint):
   - 허용 최대 배관 길이 (비용 예산)
   - 최대 꺾임 횟수 (시공 표준: UHP 배관 1m당 최대 2회)
   - 최소 배관 곡률 반경 (Bending Radius: 3D ≥ 재질별 기준)

2. 목적 함수 (Objective):
   - 총 배관 길이 최소화 (자재비 절감)
   - 꺾임 횟수 최소화 (시공비 절감, 압력 손실 최소화)

OR-Tools CP-SAT는 이러한 다목적 최적화 문제를 효율적으로 풉니다.

[주의]
이 구현은 교육 목적의 단순화된 버전입니다.
실제 DDWorks에서는 MILP(혼합 정수 선형 계획법)을 사용하며
배관 세그먼트 선택 문제를 이진 결정 변수로 모델링합니다.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PipeSegment:
    """배관 세그먼트 옵션을 나타내는 데이터 클래스."""
    segment_id: str
    from_point: dict       # {"x": float, "y": float, "z": float}
    to_point: dict
    length_m: float
    bend_count: int
    material_cost: float   # 임의 단위


@dataclass
class OptimizationResult:
    """OR-Tools 최적화 결과."""
    selected_segments: list[PipeSegment]
    total_length_m: float
    total_bends: int
    total_cost: float
    status: str            # "OPTIMAL", "FEASIBLE", "INFEASIBLE"


def optimize_pipe_routing(
    waypoints: list[dict],
    pipe_spec: str,
    max_length_m: float = 100.0,
    max_bends: int = 20,
) -> OptimizationResult:
    """
    A*로 계산된 웨이포인트 경로를 OR-Tools로 추가 최적화합니다.

    [최적화 전략]
    1. 웨이포인트를 세그먼트로 분할
    2. 연속된 같은 방향의 세그먼트를 하나로 병합 (꺾임 최소화)
    3. 총 비용 = 길이 비용 + 꺾임 비용 계산

    실제 CP-SAT 모델 대신, 여기서는 그리디(Greedy) 방식으로
    같은 방향 세그먼트를 병합하는 단순화된 최적화를 수행합니다.
    (CP-SAT 라이브러리 의존성 없이도 동일한 결과를 얻을 수 있는 경우)
    """
    if not waypoints or len(waypoints) < 2:
        return OptimizationResult(
            selected_segments=[],
            total_length_m=0.0,
            total_bends=0,
            total_cost=0.0,
            status="INFEASIBLE",
        )

    # Step 1: 웨이포인트를 방향별 세그먼트로 분할
    raw_segments = _split_into_directional_segments(waypoints)

    # Step 2: CP-SAT 기반 최적화 시도
    try:
        result = _optimize_with_ortools(raw_segments, max_length_m, max_bends)
        logger.info(
            f"OR-Tools 최적화 완료: {result.total_length_m:.2f}m, "
            f"꺾임 {result.total_bends}회, 상태={result.status}"
        )
        return result
    except ImportError:
        logger.warning("OR-Tools 미설치 - 그리디 최적화로 대체합니다.")
        return _greedy_optimize(raw_segments)


def _split_into_directional_segments(waypoints: list[dict]) -> list[PipeSegment]:
    """웨이포인트 목록을 방향이 일정한 세그먼트로 분할합니다."""
    import math

    segments = []
    if len(waypoints) < 2:
        return segments

    seg_start = waypoints[0]
    current_dir = None

    for i in range(1, len(waypoints)):
        prev = waypoints[i - 1]
        curr = waypoints[i]

        direction = (
            round(curr["x"] - prev["x"], 6),
            round(curr["y"] - prev["y"], 6),
            round(curr["z"] - prev["z"], 6),
        )

        if current_dir is None:
            current_dir = direction

        if direction != current_dir:
            # 방향이 바뀌면 새 세그먼트 시작
            seg_end = prev
            length = math.sqrt(
                (seg_end["x"] - seg_start["x"]) ** 2
                + (seg_end["y"] - seg_start["y"]) ** 2
                + (seg_end["z"] - seg_start["z"]) ** 2
            )
            segments.append(
                PipeSegment(
                    segment_id=f"SEG-{len(segments) + 1:03d}",
                    from_point=seg_start,
                    to_point=seg_end,
                    length_m=round(length, 3),
                    bend_count=0,
                    material_cost=length * 150,  # ₩150/m 임의 단가
                )
            )
            seg_start = prev
            current_dir = direction

    # 마지막 세그먼트 추가
    seg_end = waypoints[-1]
    length = math.sqrt(
        (seg_end["x"] - seg_start["x"]) ** 2
        + (seg_end["y"] - seg_start["y"]) ** 2
        + (seg_end["z"] - seg_start["z"]) ** 2
    )
    if length > 0:
        segments.append(
            PipeSegment(
                segment_id=f"SEG-{len(segments) + 1:03d}",
                from_point=seg_start,
                to_point=seg_end,
                length_m=round(length, 3),
                bend_count=0,
                material_cost=length * 150,
            )
        )

    # 세그먼트 경계(꺾임) 표시
    for i in range(len(segments) - 1):
        segments[i + 1].bend_count = 1

    return segments


def _optimize_with_ortools(
    segments: list[PipeSegment],
    max_length_m: float,
    max_bends: int,
) -> OptimizationResult:
    """
    OR-Tools CP-SAT Solver로 세그먼트 선택 최적화.

    [모델 설명]
    변수: is_selected[i] ∈ {0, 1} — i번째 세그먼트 선택 여부
    목적: minimize(Σ length[i] * is_selected[i] + Σ bend[i] * is_selected[i] * PENALTY)
    제약: Σ length[i] * is_selected[i] ≤ max_length_m
          Σ bend[i] * is_selected[i] ≤ max_bends
          경로 연결성 유지 (모든 세그먼트 선택)

    배관 라우팅에서는 경로 연결성 제약 때문에 모든 세그먼트를 선택해야 하므로
    실질적으로는 비용 계산 및 검증 역할을 합니다.
    """
    from ortools.sat.python import cp_model  # type: ignore

    model = cp_model.CpModel()
    SCALE = 1000  # float → int 변환용 스케일 팩터

    # 변수 정의
    is_selected = [model.NewBoolVar(f"seg_{i}") for i in range(len(segments))]

    # 제약: 모든 세그먼트 필수 선택 (경로 연결성)
    for var in is_selected:
        model.Add(var == 1)

    # 제약: 총 길이 ≤ max_length_m
    total_length_scaled = sum(
        int(seg.length_m * SCALE) * is_selected[i]
        for i, seg in enumerate(segments)
    )
    model.Add(total_length_scaled <= int(max_length_m * SCALE))

    # 제약: 꺾임 횟수 ≤ max_bends
    total_bends = sum(
        seg.bend_count * is_selected[i]
        for i, seg in enumerate(segments)
    )
    model.Add(total_bends <= max_bends)

    # 목적: 총 비용 최소화 (길이 + 꺾임 페널티)
    BEND_COST_SCALED = int(0.8 * SCALE)
    objective = sum(
        int(seg.length_m * SCALE) * is_selected[i]
        + seg.bend_count * BEND_COST_SCALED * is_selected[i]
        for i, seg in enumerate(segments)
    )
    model.Minimize(objective)

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status_code = solver.Solve(model)

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status = status_map.get(status_code, "UNKNOWN")

    selected = [seg for i, seg in enumerate(segments) if solver.Value(is_selected[i]) == 1]
    total_len = sum(s.length_m for s in selected)
    total_bend = sum(s.bend_count for s in selected)
    total_cost = total_len * 150 + total_bend * 50_000

    return OptimizationResult(
        selected_segments=selected,
        total_length_m=round(total_len, 3),
        total_bends=total_bend,
        total_cost=round(total_cost),
        status=status,
    )


def _greedy_optimize(segments: list[PipeSegment]) -> OptimizationResult:
    """OR-Tools가 없을 때 사용하는 그리디 폴백 최적화."""
    total_len = sum(s.length_m for s in segments)
    total_bend = sum(s.bend_count for s in segments)
    total_cost = total_len * 150 + total_bend * 50_000

    return OptimizationResult(
        selected_segments=segments,
        total_length_m=round(total_len, 3),
        total_bends=total_bend,
        total_cost=round(total_cost),
        status="FEASIBLE",
    )
