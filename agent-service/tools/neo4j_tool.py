"""
Neo4j 그래프 조회 Tool 모듈

[GraphRAG에서 Neo4j가 필요한 이유]
배관망 네트워크 문제는 '연결성(Topology)'이 핵심입니다.
- 일반 벡터 DB: "UHP 가스 연결 표준" 같은 의미론적 검색에 적합
- Neo4j: "V-001 밸브를 차단할 때 영향받는 하류 장비" 같은 관계 탐색에 적합

Cypher 쿼리는 JOIN 없이 O(1)에 가까운 관계 탐색이 가능하여
수만 개의 배관 세그먼트가 있어도 빠르게 경로를 추적할 수 있습니다.
"""

import logging
from core.neo4j_handler import create_handler

logger = logging.getLogger(__name__)


class Neo4jPipingTool:
    """배관 네트워크 조회를 위한 Neo4j 전용 툴 모음."""

    def __init__(self):
        self._handler = create_handler()
        self._handler.connect()

    def get_equipment_info(self, tag: str) -> dict | None:
        """장비 태그로 장비 정보(위치·스펙)를 조회합니다."""
        result = self._handler.run_query(
            """
            MATCH (e:Equipment {tag: $tag})
            RETURN e.tag AS tag, e.name AS name, e.type AS type,
                   e.spec AS spec, e.x AS x, e.y AS y, e.z AS z,
                   e.pressure_bar AS pressure_bar
            """,
            {"tag": tag},
        )
        return result[0] if result else None

    def get_all_obstacles(self) -> list[dict]:
        """모든 장애물(기둥, 보 등)의 3D 위치를 조회합니다."""
        return self._handler.run_query(
            """
            MATCH (o:Obstacle)
            RETURN o.obs_id AS obs_id, o.type AS type,
                   o.x AS x, o.y AS y, o.z AS z, o.radius_m AS radius_m
            ORDER BY o.obs_id
            """
        )

    def get_piping_topology_context(self, source_tag: str, target_tag: str) -> str:
        """
        출발-목적지 장비 주변의 배관 위상 정보를 텍스트로 반환합니다.
        이 텍스트가 LLM의 GraphRAG 컨텍스트로 사용됩니다.

        [Cypher 설명]
        FLOWS_TO*1..5: 최대 5홉(Hop) 이내의 경로를 탐색합니다.
        Variable-length paths는 RDB의 재귀 JOIN과 달리 효율적으로 처리됩니다.
        """
        # 출발 장비에서 최대 5홉 이내의 연결된 장비 조회
        neighbors = self._handler.run_query(
            """
            MATCH (src:Equipment {tag: $tag})-[:FLOWS_TO*1..5]->(downstream:Equipment)
            RETURN DISTINCT downstream.tag AS tag, downstream.name AS name,
                   downstream.type AS type, downstream.spec AS spec
            LIMIT 20
            """,
            {"tag": source_tag},
        )

        # 목적지 장비로 들어오는 상류 경로 조회
        upstream = self._handler.run_query(
            """
            MATCH (upstream:Equipment)-[:FLOWS_TO*1..5]->(dst:Equipment {tag: $tag})
            RETURN DISTINCT upstream.tag AS tag, upstream.name AS name,
                   upstream.type AS type, upstream.spec AS spec
            LIMIT 20
            """,
            {"tag": target_tag},
        )

        # 기존 배관 스펙 조회
        existing_pipes = self._handler.run_query(
            """
            MATCH (src:Equipment)-[r:FLOWS_TO]->(dst:Equipment)
            WHERE src.tag IN $tags OR dst.tag IN $tags
            RETURN src.tag AS from_tag, dst.tag AS to_tag,
                   r.spec AS spec, r.material AS material,
                   r.diameter_inch AS diameter_inch
            LIMIT 30
            """,
            {"tags": [source_tag, target_tag]},
        )

        # LLM이 이해하기 쉬운 텍스트 형식으로 변환
        context_lines = [
            f"=== 배관 위상 컨텍스트 ===",
            f"출발 장비({source_tag})의 하류 연결 장비:",
        ]
        for n in neighbors:
            context_lines.append(f"  - {n['tag']} ({n['name']}, 스펙: {n['spec']})")

        context_lines.append(f"\n목적지 장비({target_tag})의 상류 연결 장비:")
        for u in upstream:
            context_lines.append(f"  - {u['tag']} ({u['name']}, 스펙: {u['spec']})")

        context_lines.append(f"\n관련 기존 배관 스펙:")
        for p in existing_pipes:
            context_lines.append(
                f"  - {p['from_tag']} → {p['to_tag']}: "
                f"{p['spec']}, {p['material']}, {p['diameter_inch']}\" 관경"
            )

        return "\n".join(context_lines)

    def get_all_equipment(self) -> list[dict]:
        """모든 장비 노드를 조회합니다."""
        return self._handler.run_query(
            """
            MATCH (e:Equipment)
            RETURN e.tag AS tag, e.name AS name, e.type AS type,
                   e.spec AS spec, e.x AS x, e.y AS y, e.z AS z,
                   e.pressure_bar AS pressure_bar
            ORDER BY e.tag
            """
        )

    def get_all_piping(self) -> list[dict]:
        """모든 배관 관계를 조회합니다."""
        return self._handler.run_query(
            """
            MATCH (src:Equipment)-[r:FLOWS_TO]->(dst:Equipment)
            RETURN src.tag AS from_tag, dst.tag AS to_tag,
                   r.pipe_id AS pipe_id, r.spec AS spec,
                   r.material AS material, r.diameter_inch AS diameter_inch,
                   r.status AS status, r.length_m AS length_m
            ORDER BY r.pipe_id
            """
        )

    def save_designed_pipe(
        self,
        source_tag: str,
        target_tag: str,
        pipe_id: str,
        spec: str,
        path_waypoints: list[dict],
        material: str = "SS316L_EP",
    ) -> bool:
        """
        AI Agent가 계산한 최적 경로를 'AS_DESIGNED' 상태의 배관으로 저장합니다.
        이 데이터가 이후 As-Built 정합성 검증의 기준(Ground Truth)이 됩니다.
        """
        total_length = sum(
            ((w2["x"] - w1["x"]) ** 2 + (w2["y"] - w1["y"]) ** 2 + (w2["z"] - w1["z"]) ** 2) ** 0.5
            for w1, w2 in zip(path_waypoints, path_waypoints[1:])
        ) if len(path_waypoints) > 1 else 0.0

        result = self._handler.run_write(
            """
            MATCH (src:Equipment {tag: $source_tag})
            MATCH (dst:Equipment {tag: $target_tag})
            MERGE (src)-[r:FLOWS_TO {pipe_id: $pipe_id}]->(dst)
            SET r.spec = $spec,
                r.material = $material,
                r.status = 'AS_DESIGNED',
                r.length_m = $length_m,
                r.waypoints = $waypoints,
                r.created_by = 'AI_AGENT'
            RETURN r.pipe_id AS pipe_id
            """,
            {
                "source_tag": source_tag,
                "target_tag": target_tag,
                "pipe_id": pipe_id,
                "spec": spec,
                "material": material,
                "length_m": round(total_length, 3),
                "waypoints": str(path_waypoints),
            },
        )
        return len(result) > 0

    def close(self):
        self._handler.close()
