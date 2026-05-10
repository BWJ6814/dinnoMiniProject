"""
반도체 FAB 샘플 데이터를 Neo4j에 삽입하는 시더(Seeder).

[도메인 설명]
반도체 FAB 라인의 가스/케미컬 배관 시스템은 다음으로 구성됩니다:
- Equipment (장비): 가스 공급원, 챔버, 펌프, 밸브 등
- Piping (배관 - Edge): 장비 간 연결. 재질·압력·스펙이 지정됩니다.
- Obstacle (장애물): 기둥, 보 등 배관이 통과할 수 없는 물리적 구조물

[그래프 온톨로지]
Node Labels: :Equipment, :Obstacle
Relationship Types:
  - :FLOWS_TO   → 유체(가스/케미컬)가 흐르는 방향 (방향성 있음)
  - :CONNECTED_TO → 양방향 물리적 연결
"""

import logging
from core.neo4j_handler import create_handler

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 샘플 장비 데이터 (반도체 FAB 레이아웃)
# x, y, z 단위는 미터(m), FAB 바닥면 기준
# ──────────────────────────────────────────────
EQUIPMENT_DATA = [
    {
        "tag": "GAS-N2-001",
        "name": "N2 가스 공급 장치",
        "type": "GAS_SUPPLY",
        "spec": "UHP_N2",          # Ultra High Purity Nitrogen
        "x": 0.0, "y": 0.0, "z": 2.5,
        "pressure_bar": 8.0,
    },
    {
        "tag": "GAS-AR-001",
        "name": "Ar 가스 공급 장치",
        "type": "GAS_SUPPLY",
        "spec": "UHP_AR",
        "x": 0.0, "y": 3.0, "z": 2.5,
        "pressure_bar": 6.0,
    },
    {
        "tag": "HDR-MAIN-001",
        "name": "메인 헤더 배관",
        "type": "MAIN_HEADER",
        "spec": "SS316L",          # 스테인리스 316L (반도체 UHP 표준)
        "x": 5.0, "y": 1.5, "z": 2.5,
        "pressure_bar": 7.5,
    },
    {
        "tag": "VLV-001",
        "name": "메인 라인 밸브 1",
        "type": "VALVE",
        "spec": "DIAPHRAGM_NC",    # Normally Closed 다이어프램 밸브
        "x": 8.0, "y": 1.5, "z": 2.5,
        "pressure_bar": 7.0,
    },
    {
        "tag": "VLV-002",
        "name": "분기 밸브 2",
        "type": "VALVE",
        "spec": "DIAPHRAGM_NC",
        "x": 10.0, "y": 0.5, "z": 2.5,
        "pressure_bar": 6.8,
    },
    {
        "tag": "VLV-003",
        "name": "분기 밸브 3",
        "type": "VALVE",
        "spec": "DIAPHRAGM_NC",
        "x": 10.0, "y": 2.5, "z": 2.5,
        "pressure_bar": 6.8,
    },
    {
        "tag": "CHAMBER-A",
        "name": "웨이퍼 챔버 A (CVD)",
        "type": "PROCESS_CHAMBER",
        "spec": "CVD_CHAMBER",
        "x": 14.0, "y": 0.0, "z": 0.0,
        "pressure_bar": 0.1,       # 공정 내부는 저압
    },
    {
        "tag": "CHAMBER-B",
        "name": "웨이퍼 챔버 B (CVD)",
        "type": "PROCESS_CHAMBER",
        "spec": "CVD_CHAMBER",
        "x": 14.0, "y": 3.0, "z": 0.0,
        "pressure_bar": 0.1,
    },
    {
        "tag": "PUMP-EXH-001",
        "name": "배기 펌프 1",
        "type": "EXHAUST_PUMP",
        "spec": "DRY_PUMP",
        "x": 16.0, "y": 1.5, "z": 0.0,
        "pressure_bar": 0.01,
    },
    {
        "tag": "CCSS-001",
        "name": "케미컬 중앙공급장치",
        "type": "CCSS",            # Chemical Central Supply System
        "spec": "CCSS_HF",         # 불화수소산 (식각용)
        "x": 2.0, "y": 6.0, "z": 0.0,
        "pressure_bar": 3.0,
    },
]

# ──────────────────────────────────────────────
# 배관 연결 데이터 (As-Designed)
# source → target, 스펙 및 상태 포함
# ──────────────────────────────────────────────
PIPING_DATA = [
    {
        "source": "GAS-N2-001", "target": "HDR-MAIN-001",
        "pipe_id": "PIPE-001", "spec": "UHP_N2",
        "diameter_inch": 0.5, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 5.2,
    },
    {
        "source": "GAS-AR-001", "target": "HDR-MAIN-001",
        "pipe_id": "PIPE-002", "spec": "UHP_AR",
        "diameter_inch": 0.5, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 4.8,
    },
    {
        "source": "HDR-MAIN-001", "target": "VLV-001",
        "pipe_id": "PIPE-003", "spec": "UHP_N2",
        "diameter_inch": 0.75, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 3.0,
    },
    {
        "source": "VLV-001", "target": "VLV-002",
        "pipe_id": "PIPE-004", "spec": "UHP_N2",
        "diameter_inch": 0.5, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 2.1,
    },
    {
        "source": "VLV-001", "target": "VLV-003",
        "pipe_id": "PIPE-005", "spec": "UHP_N2",
        "diameter_inch": 0.5, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 2.1,
    },
    {
        "source": "VLV-002", "target": "CHAMBER-A",
        "pipe_id": "PIPE-006", "spec": "UHP_N2",
        "diameter_inch": 0.375, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 4.5,
    },
    {
        "source": "VLV-003", "target": "CHAMBER-B",
        "pipe_id": "PIPE-007", "spec": "UHP_N2",
        "diameter_inch": 0.375, "material": "SS316L_EP",
        "status": "AS_DESIGNED", "length_m": 4.5,
    },
    {
        "source": "CHAMBER-A", "target": "PUMP-EXH-001",
        "pipe_id": "PIPE-008", "spec": "EXHAUST",
        "diameter_inch": 1.0, "material": "SUS304",
        "status": "AS_DESIGNED", "length_m": 2.5,
    },
    {
        "source": "CHAMBER-B", "target": "PUMP-EXH-001",
        "pipe_id": "PIPE-009", "spec": "EXHAUST",
        "diameter_inch": 1.0, "material": "SUS304",
        "status": "AS_DESIGNED", "length_m": 2.5,
    },
]

# ──────────────────────────────────────────────
# 장애물 데이터 (기둥 위치)
# A* 알고리즘이 회피해야 할 구조물
# ──────────────────────────────────────────────
OBSTACLE_DATA = [
    {"obs_id": "COL-001", "type": "COLUMN", "x": 6.0, "y": 1.5, "z": 0.0, "radius_m": 0.3},
    {"obs_id": "COL-002", "type": "COLUMN", "x": 11.0, "y": 1.5, "z": 0.0, "radius_m": 0.3},
    {"obs_id": "COL-003", "type": "COLUMN", "x": 6.0, "y": 5.0, "z": 0.0, "radius_m": 0.3},
    {"obs_id": "BEAM-001", "type": "BEAM", "x": 8.0, "y": 3.5, "z": 2.5, "radius_m": 0.2},
]


def seed_neo4j() -> dict:
    """
    Neo4j에 샘플 FAB 데이터를 삽입합니다.
    MERGE를 사용하여 중복 실행 시 데이터가 중복 생성되지 않습니다.
    """
    handler = create_handler()
    handler.connect()

    results = {"equipment": 0, "piping": 0, "obstacles": 0}

    # 1. 기존 데이터 초기화 (재실행 안전성)
    handler.run_write("MATCH (n) DETACH DELETE n")
    logger.info("기존 그래프 데이터 초기화 완료")

    # 2. 인덱스 생성 (tag 속성으로 빠른 검색)
    handler.run_write("CREATE INDEX equipment_tag IF NOT EXISTS FOR (e:Equipment) ON (e.tag)")
    handler.run_write("CREATE INDEX obstacle_id IF NOT EXISTS FOR (o:Obstacle) ON (o.obs_id)")

    # 3. 장비 노드 삽입
    for eq in EQUIPMENT_DATA:
        handler.run_write(
            """
            MERGE (e:Equipment {tag: $tag})
            SET e.name = $name,
                e.type = $type,
                e.spec = $spec,
                e.x = $x, e.y = $y, e.z = $z,
                e.pressure_bar = $pressure_bar
            """,
            eq,
        )
    results["equipment"] = len(EQUIPMENT_DATA)
    logger.info(f"장비 노드 {len(EQUIPMENT_DATA)}개 삽입 완료")

    # 4. 배관 관계(Edge) 삽입
    for pipe in PIPING_DATA:
        handler.run_write(
            """
            MATCH (src:Equipment {tag: $source})
            MATCH (dst:Equipment {tag: $target})
            MERGE (src)-[r:FLOWS_TO {pipe_id: $pipe_id}]->(dst)
            SET r.spec = $spec,
                r.diameter_inch = $diameter_inch,
                r.material = $material,
                r.status = $status,
                r.length_m = $length_m
            """,
            pipe,
        )
    results["piping"] = len(PIPING_DATA)
    logger.info(f"배관 관계 {len(PIPING_DATA)}개 삽입 완료")

    # 5. 장애물 노드 삽입
    for obs in OBSTACLE_DATA:
        handler.run_write(
            """
            MERGE (o:Obstacle {obs_id: $obs_id})
            SET o.type = $type,
                o.x = $x, o.y = $y, o.z = $z,
                o.radius_m = $radius_m
            """,
            obs,
        )
    results["obstacles"] = len(OBSTACLE_DATA)
    logger.info(f"장애물 노드 {len(OBSTACLE_DATA)}개 삽입 완료")

    handler.close()
    return results


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    logging.basicConfig(level=logging.INFO)
    result = seed_neo4j()
    print(f"시드 완료: {result}")
