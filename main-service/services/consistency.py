"""
As-Built vs As-Designed 3D 정합성 검증 모듈

[디노 특허 기술 모사: KR102037332B1]
반도체 FAB 시공 현장에서 3D 스캔(LiDAR)으로 획득한 Point Cloud(As-Built)와
설계 도면 데이터(As-Designed)를 비교하여 정합성을 검증합니다.

배관 한 줄의 오차가 공장 전체 가동 중단으로 이어질 수 있어,
이 검증 과정이 반도체 FAB 시공의 핵심 품질 관리 절차입니다.

[ICP (Iterative Closest Point) 알고리즘]
두 Point Cloud를 정렬(Align)하여 오차를 계산합니다.

동작 원리:
1. 초기 정렬: 두 Point Cloud를 대략적으로 위치 맞춤 (초기 변환 행렬)
2. 반복 최적화:
   a. As-Built의 각 점에서 As-Designed의 가장 가까운 점(Closest Point)을 찾습니다.
   b. 두 점 집합 간의 거리를 최소화하는 변환 행렬(R, t)을 SVD로 계산합니다.
   c. As-Built에 변환을 적용합니다.
   d. 오차(RMSE)가 수렴할 때까지 반복합니다.
3. 최종 RMSE(Root Mean Square Error)가 허용 오차(5cm) 이내인지 판단합니다.

[구현 방식]
Open3D 라이브러리를 사용합니다. 없을 경우 numpy 기반 단순 거리 계산으로 대체합니다.
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# 허용 오차 (미터) - 반도체 FAB 시공 정밀도 기준
DEFAULT_TOLERANCE_M = 0.05  # 5cm


@dataclass
class ConsistencyResult:
    """정합성 검증 결과 데이터 클래스."""
    rmse_m: float                  # 최종 RMSE (미터)
    tolerance_m: float             # 허용 오차 (미터)
    is_within_tolerance: bool      # 허용 오차 이내 여부
    status: str                    # "PASS", "WARNING", "FAIL"
    transformation_matrix: list    # ICP가 계산한 변환 행렬 (4x4)
    iteration_count: int           # ICP 반복 횟수
    message: str                   # 결과 메시지


def verify_consistency(
    designed_points: list[list[float]],   # As-Designed 좌표 [[x,y,z], ...]
    built_points: list[list[float]],       # As-Built 좌표 (3D 스캔)
    tolerance_m: float = DEFAULT_TOLERANCE_M,
) -> ConsistencyResult:
    """
    As-Built vs As-Designed 3D 정합성을 ICP 알고리즘으로 검증합니다.

    Args:
        designed_points: 설계 도면의 배관 경로 점들 [[x, y, z], ...]
        built_points: 현장 3D 스캔(LiDAR)으로 획득한 배관 점들
        tolerance_m: 허용 오차 (기본값: 5cm)

    Returns:
        ConsistencyResult: RMSE, 통과 여부, 변환 행렬 포함
    """
    if not designed_points or not built_points:
        return ConsistencyResult(
            rmse_m=float("inf"),
            tolerance_m=tolerance_m,
            is_within_tolerance=False,
            status="FAIL",
            transformation_matrix=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
            iteration_count=0,
            message="입력 데이터가 비어 있습니다.",
        )

    # Open3D 사용 가능 여부 확인
    try:
        import open3d as o3d
        return _icp_with_open3d(designed_points, built_points, tolerance_m)
    except ImportError:
        logger.warning("Open3D 미설치 - NumPy 기반 단순 거리 계산으로 대체합니다.")
        return _simple_distance_check(designed_points, built_points, tolerance_m)


def _icp_with_open3d(
    designed_points: list[list[float]],
    built_points: list[list[float]],
    tolerance_m: float,
) -> ConsistencyResult:
    """
    Open3D ICP 알고리즘으로 정합성을 검증합니다.

    [ICP 파라미터 설명]
    max_correspondence_distance: 대응점 탐색 최대 거리 (클수록 넓게 탐색)
    criteria: 수렴 기준 (상대 오차 변화량, 최대 반복 횟수)
    """
    import open3d as o3d
    import numpy as np

    # Point Cloud 객체 생성
    pcd_designed = o3d.geometry.PointCloud()
    pcd_designed.points = o3d.utility.Vector3dVector(np.array(designed_points))

    pcd_built = o3d.geometry.PointCloud()
    pcd_built.points = o3d.utility.Vector3dVector(np.array(built_points))

    # ICP 실행 파라미터
    max_correspondence_dist = tolerance_m * 10  # 허용 오차의 10배를 대응 탐색 거리로 설정
    criteria = o3d.pipelines.registration.ICPConvergenceCriteria(
        relative_fitness=1e-6,
        relative_rmse=1e-6,
        max_iteration=100,
    )

    # Point-to-Point ICP 실행
    result = o3d.pipelines.registration.registration_icp(
        source=pcd_built,           # 정렬할 대상 (As-Built)
        target=pcd_designed,        # 기준 (As-Designed)
        max_correspondence_distance=max_correspondence_dist,
        init=np.eye(4),             # 초기 변환 행렬 (단위 행렬 = 변환 없음)
        estimation_method=o3d.pipelines.registration.TransformationEstimationPointToPoint(),
        criteria=criteria,
    )

    rmse = float(result.inlier_rmse)
    transformation = result.transformation.tolist()

    # 상태 결정
    if rmse <= tolerance_m:
        status = "PASS"
        message = f"정합성 검증 통과. RMSE={rmse*100:.1f}cm (허용: {tolerance_m*100:.0f}cm)"
    elif rmse <= tolerance_m * 2:
        status = "WARNING"
        message = f"경미한 오차 감지. RMSE={rmse*100:.1f}cm (허용: {tolerance_m*100:.0f}cm) - 현장 확인 권장"
    else:
        status = "FAIL"
        message = f"허용 오차 초과. RMSE={rmse*100:.1f}cm (허용: {tolerance_m*100:.0f}cm) - 재시공 또는 설계 변경 필요"

    logger.info(f"ICP 검증 완료: {status}, RMSE={rmse:.4f}m")

    return ConsistencyResult(
        rmse_m=round(rmse, 6),
        tolerance_m=tolerance_m,
        is_within_tolerance=rmse <= tolerance_m,
        status=status,
        transformation_matrix=transformation,
        iteration_count=100,   # Open3D는 정확한 반복 횟수를 미노출
        message=message,
    )


def _simple_distance_check(
    designed_points: list[list[float]],
    built_points: list[list[float]],
    tolerance_m: float,
) -> ConsistencyResult:
    """
    Open3D 없이 NumPy로 구현한 단순 최근접 거리 기반 오차 계산.
    ICP의 1회 반복과 동일한 원리입니다 (정렬 없음).
    """
    if len(designed_points) == 0 or len(built_points) == 0:
        return ConsistencyResult(
            rmse_m=float("inf"),
            tolerance_m=tolerance_m,
            is_within_tolerance=False,
            status="FAIL",
            transformation_matrix=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
            iteration_count=0,
            message="포인트 데이터 없음",
        )

    # 각 As-Built 점에서 가장 가까운 As-Designed 점까지의 거리 계산
    squared_errors = []
    for bp in built_points:
        min_dist_sq = float("inf")
        for dp in designed_points:
            dist_sq = (bp[0] - dp[0])**2 + (bp[1] - dp[1])**2 + (bp[2] - dp[2])**2
            min_dist_sq = min(min_dist_sq, dist_sq)
        squared_errors.append(min_dist_sq)

    rmse = math.sqrt(sum(squared_errors) / len(squared_errors))

    if rmse <= tolerance_m:
        status = "PASS"
        message = f"정합성 검증 통과 (단순 거리). RMSE={rmse*100:.1f}cm"
    elif rmse <= tolerance_m * 2:
        status = "WARNING"
        message = f"경미한 오차. RMSE={rmse*100:.1f}cm (허용: {tolerance_m*100:.0f}cm)"
    else:
        status = "FAIL"
        message = f"허용 오차 초과. RMSE={rmse*100:.1f}cm (허용: {tolerance_m*100:.0f}cm)"

    return ConsistencyResult(
        rmse_m=round(rmse, 6),
        tolerance_m=tolerance_m,
        is_within_tolerance=rmse <= tolerance_m,
        status=status,
        transformation_matrix=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
        iteration_count=1,
        message=message,
    )
