"""
As-Built vs As-Designed 정합성 검증 라우터

POST /api/v1/verify/consistency
- 두 Point Cloud 데이터셋을 받아 ICP 알고리즘으로 오차를 검증합니다.
- 디노 특허 KR102037332B1 핵심 기능의 미니 구현입니다.
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from main_service.services.consistency import verify_consistency
except ImportError:
    from services.consistency import verify_consistency

logger = logging.getLogger(__name__)
router = APIRouter()


class ConsistencyVerifyRequest(BaseModel):
    """정합성 검증 요청 스키마."""

    designed_points: list[list[float]] = Field(
        ...,
        description="설계 도면(As-Designed)의 배관 경로 3D 좌표 목록 [[x, y, z], ...]",
        examples=[[[0.0, 0.0, 2.5], [5.0, 0.0, 2.5], [5.0, 3.0, 2.5], [14.0, 3.0, 0.0]]],
    )
    built_points: list[list[float]] = Field(
        ...,
        description="현장 3D 스캔(As-Built) Point Cloud 좌표 목록",
        examples=[[[0.02, 0.01, 2.52], [5.03, -0.01, 2.49], [5.01, 3.02, 2.51], [14.04, 3.01, 0.02]]],
    )
    tolerance_m: float = Field(
        default=0.05,
        description="허용 오차 (미터 단위, 기본값 5cm)",
        ge=0.001,
        le=1.0,
    )
    pipe_id: str = Field(
        default="",
        description="검증 대상 배관 ID (선택 사항, 결과 추적용)",
    )


@router.post("/consistency", summary="As-Built vs As-Designed 3D 정합성 검증")
async def verify_consistency_endpoint(request: ConsistencyVerifyRequest):
    """
    현장 시공 데이터(As-Built Point Cloud)와 설계 도면 데이터(As-Designed)를 비교하여
    ICP 알고리즘으로 정합성을 검증합니다.

    **디노 특허 KR102037332B1의 핵심 기능을 구현합니다.**

    **검증 기준:**
    - PASS: RMSE ≤ 허용 오차 (기본 5cm)
    - WARNING: 허용 오차 < RMSE ≤ 허용 오차 × 2
    - FAIL: RMSE > 허용 오차 × 2 → 재시공 또는 설계 변경 필요

    **ICP 알고리즘 (Iterative Closest Point):**
    두 Point Cloud를 반복적으로 정렬하여 최소 오차 변환 행렬을 계산합니다.
    Open3D 설치 시 ICP 사용, 미설치 시 단순 최근접 거리 계산으로 대체됩니다.
    """
    logger.info(
        f"정합성 검증 요청: designed={len(request.designed_points)}점, "
        f"built={len(request.built_points)}점, tolerance={request.tolerance_m}m"
    )

    if len(request.designed_points) < 2:
        raise HTTPException(
            status_code=422,
            detail="설계 포인트는 최소 2개 이상 필요합니다.",
        )

    if len(request.built_points) < 2:
        raise HTTPException(
            status_code=422,
            detail="시공 포인트는 최소 2개 이상 필요합니다.",
        )

    try:
        result = verify_consistency(
            designed_points=request.designed_points,
            built_points=request.built_points,
            tolerance_m=request.tolerance_m,
        )

        response_data = {
            "pipe_id": request.pipe_id or "N/A",
            "status": result.status,
            "is_within_tolerance": result.is_within_tolerance,
            "rmse_m": result.rmse_m,
            "rmse_cm": round(result.rmse_m * 100, 2),
            "tolerance_m": result.tolerance_m,
            "tolerance_cm": result.tolerance_m * 100,
            "message": result.message,
            "iteration_count": result.iteration_count,
            "transformation_matrix": result.transformation_matrix,
            "recommendation": _get_recommendation(result.status),
        }

        # 검증 실패 시 경고 로그
        if result.status == "FAIL":
            logger.warning(
                f"정합성 검증 실패 [{request.pipe_id}]: RMSE={result.rmse_m*100:.1f}cm "
                f"(허용: {request.tolerance_m*100:.0f}cm)"
            )

        return response_data

    except Exception as e:
        logger.error(f"정합성 검증 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"검증 처리 오류: {str(e)}")


def _get_recommendation(status: str) -> str:
    """검증 상태에 따른 권장 조치를 반환합니다."""
    recommendations = {
        "PASS": "시공 품질 기준 충족. 다음 단계로 진행 가능합니다.",
        "WARNING": "경미한 오차가 감지되었습니다. 현장 재확인 후 진행을 권장합니다.",
        "FAIL": "허용 오차를 초과했습니다. 재시공(Re-work) 또는 설계 변경 승인이 필요합니다.",
    }
    return recommendations.get(status, "알 수 없는 상태")
