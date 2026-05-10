"""
3D 공간 경로 탐색 모듈 (NetworkX + A* 알고리즘)

[A* 알고리즘을 선택한 이유]
배관 라우팅 문제는 단순 최단거리가 아닙니다:
- 장애물(기둥, 보) 회피가 필수입니다.
- 배관 꺾임(Bend) 횟수를 최소화해야 합니다 (꺾임 = 비용 + 압력 손실).
- Dijkstra는 모든 노드를 탐색하지만, A*는 목적지 방향으로 유도되는
  휴리스틱(Heuristic) 함수 덕분에 탐색 공간을 크게 줄입니다.

[격자 그래프(Grid Graph) 방식]
3D 공간을 일정 간격의 격자(Grid)로 분할하여 탐색 공간을 이산화합니다.
- 장점: 구현이 단순하고 장애물 표현이 쉽습니다.
- 단점: 격자 해상도가 낮으면 최적 경로를 놓칠 수 있습니다.
실제 DDWorks에서는 연속 공간 탐색(Continuous Space Search)을 사용합니다.
"""

import math
import logging
from typing import Optional

import networkx as nx

logger = logging.getLogger(__name__)

# 3D 격자 해상도 (미터 단위)
GRID_RESOLUTION = 0.5

# 배관 꺾임 추가 비용 (직선 배관 대비 45도 꺾임 1회당 비용)
# 실제 프로젝트에서는 배관 재질·구경별 최소 곡률 반경(Bending Radius) 기준을 사용합니다
BEND_PENALTY = 0.8


def _euclidean_3d(p1: dict, p2: dict) -> float:
    """두 3D 좌표 간 유클리드 거리를 계산합니다."""
    return math.sqrt(
        (p1["x"] - p2["x"]) ** 2
        + (p1["y"] - p2["y"]) ** 2
        + (p1["z"] - p2["z"]) ** 2
    )


def _coord_to_node(x: float, y: float, z: float) -> tuple:
    """
    연속 좌표를 격자 노드 인덱스로 변환합니다.
    예: (5.7, 1.2, 2.5) → (11, 2, 5) (해상도 0.5m 기준)
    """
    return (
        round(x / GRID_RESOLUTION),
        round(y / GRID_RESOLUTION),
        round(z / GRID_RESOLUTION),
    )


def _node_to_coord(node: tuple) -> dict:
    """격자 노드 인덱스를 실제 미터 좌표로 변환합니다."""
    return {
        "x": node[0] * GRID_RESOLUTION,
        "y": node[1] * GRID_RESOLUTION,
        "z": node[2] * GRID_RESOLUTION,
    }


def _is_obstacle_collision(
    point: dict,
    obstacles: list[dict],
    safety_margin: float = 0.1,
) -> bool:
    """
    주어진 3D 좌표가 장애물과 충돌하는지 검사합니다.
    safety_margin: 장애물 반경에 추가하는 안전 여유 (단위: m)
    """
    for obs in obstacles:
        dist = math.sqrt(
            (point["x"] - obs["x"]) ** 2 + (point["y"] - obs["y"]) ** 2
        )
        if dist < obs.get("radius_m", 0.3) + safety_margin:
            return True
    return False


def build_3d_grid_graph(
    source_coords: dict,
    target_coords: dict,
    obstacles: list[dict],
    padding: float = 2.0,
) -> nx.Graph:
    """
    출발지-목적지 주변의 3D 격자 그래프를 생성합니다.

    [그래프 구성]
    - 노드: 격자 격자점 (장애물과 겹치지 않는 점만 포함)
    - 엣지: 인접한 격자점 간 연결 (26방향 - 3D에서의 모든 이웃)
    - 가중치(Weight): 유클리드 거리 + 꺾임 패널티

    실제 반도체 FAB에서는 배관이 주로 X, Y, Z 방향(직교)으로만 연결되므로
    현실적으로는 6방향(상하좌우앞뒤)으로 제한하는 것이 맞습니다.
    """
    # 탐색 범위 계산 (출발-도착 사이의 bounding box + padding)
    x_min = min(source_coords["x"], target_coords["x"]) - padding
    x_max = max(source_coords["x"], target_coords["x"]) + padding
    y_min = min(source_coords["y"], target_coords["y"]) - padding
    y_max = max(source_coords["y"], target_coords["y"]) + padding
    z_min = min(source_coords["z"], target_coords["z"]) - padding
    z_max = max(source_coords["z"], target_coords["z"]) + padding

    G = nx.Graph()

    # 격자 범위 계산
    ix_min = round(x_min / GRID_RESOLUTION)
    ix_max = round(x_max / GRID_RESOLUTION)
    iy_min = round(y_min / GRID_RESOLUTION)
    iy_max = round(y_max / GRID_RESOLUTION)
    iz_min = round(z_min / GRID_RESOLUTION)
    iz_max = round(z_max / GRID_RESOLUTION)

    # 노드 생성 (장애물과 충돌하지 않는 격자점만)
    valid_nodes = set()
    for ix in range(ix_min, ix_max + 1):
        for iy in range(iy_min, iy_max + 1):
            for iz in range(iz_min, iz_max + 1):
                node = (ix, iy, iz)
                coord = _node_to_coord(node)
                if not _is_obstacle_collision(coord, obstacles):
                    valid_nodes.add(node)
                    G.add_node(node, **coord)

    # 엣지 생성 (직교 6방향만 허용 - FAB 배관 현실 반영)
    directions = [
        (1, 0, 0), (-1, 0, 0),   # X 방향
        (0, 1, 0), (0, -1, 0),   # Y 방향
        (0, 0, 1), (0, 0, -1),   # Z 방향 (층간 배관)
    ]

    for node in valid_nodes:
        ix, iy, iz = node
        for dx, dy, dz in directions:
            neighbor = (ix + dx, iy + dy, iz + dz)
            if neighbor in valid_nodes:
                weight = GRID_RESOLUTION  # 직선 이동 비용
                G.add_edge(node, neighbor, weight=weight)

    logger.info(
        f"격자 그래프 생성: {G.number_of_nodes()}개 노드, "
        f"{G.number_of_edges()}개 엣지"
    )
    return G


def find_shortest_path_astar(
    source_coords: dict,
    target_coords: dict,
    obstacles: list[dict],
) -> Optional[tuple[list[dict], float]]:
    """
    A* 알고리즘으로 장애물을 회피하는 최단 경로를 탐색합니다.

    [A* 휴리스틱 함수]
    h(n) = 현재 노드 n에서 목적지까지의 유클리드 거리
    f(n) = g(n) + h(n)
    - g(n): 출발지에서 n까지의 실제 비용
    - h(n): n에서 목적지까지의 추정 비용 (낙관적 추정, 절대 과대평가 안 함)

    휴리스틱이 '허용 가능(Admissible)'하면 A*는 항상 최적 경로를 보장합니다.
    유클리드 거리는 실제 거리보다 절대 크지 않으므로 허용 가능합니다.

    Returns:
        (waypoints, total_cost) 또는 None (경로 없음)
    """
    G = build_3d_grid_graph(source_coords, target_coords, obstacles)

    source_node = _coord_to_node(source_coords["x"], source_coords["y"], source_coords["z"])
    target_node = _coord_to_node(target_coords["x"], target_coords["y"], target_coords["z"])

    # 노드가 그래프에 없으면 가장 가까운 유효 노드 사용
    if source_node not in G:
        source_node = min(G.nodes(), key=lambda n: _euclidean_3d(_node_to_coord(n), source_coords))
    if target_node not in G:
        target_node = min(G.nodes(), key=lambda n: _euclidean_3d(_node_to_coord(n), target_coords))

    def heuristic(n1, n2) -> float:
        """A* 휴리스틱: 두 격자 노드 간의 유클리드 거리."""
        return _euclidean_3d(_node_to_coord(n1), _node_to_coord(n2))

    try:
        path_nodes = nx.astar_path(G, source_node, target_node, heuristic=heuristic, weight="weight")
        total_cost = nx.astar_path_length(G, source_node, target_node, heuristic=heuristic, weight="weight")

        # 격자 노드 → 실제 3D 좌표로 변환
        waypoints = [_node_to_coord(n) for n in path_nodes]

        # 경로에 꺾임 패널티 추가 계산
        bend_count = _count_bends(path_nodes)
        total_cost_with_penalty = total_cost + bend_count * BEND_PENALTY

        logger.info(
            f"A* 경로 탐색 성공: {len(waypoints)}개 웨이포인트, "
            f"총 비용={total_cost_with_penalty:.2f}m (꺾임 {bend_count}회)"
        )
        return waypoints, total_cost_with_penalty

    except nx.NetworkXNoPath:
        logger.warning(f"경로 없음: {source_coords} → {target_coords}")
        return None


def _count_bends(path_nodes: list[tuple]) -> int:
    """
    경로에서 방향이 바뀌는 지점(꺾임) 수를 계산합니다.
    배관 꺾임은 재료비 증가 + 압력 손실 증가 + 시공 난이도 증가를 유발합니다.
    """
    if len(path_nodes) < 3:
        return 0

    bends = 0
    for i in range(1, len(path_nodes) - 1):
        prev_dir = (
            path_nodes[i][0] - path_nodes[i - 1][0],
            path_nodes[i][1] - path_nodes[i - 1][1],
            path_nodes[i][2] - path_nodes[i - 1][2],
        )
        next_dir = (
            path_nodes[i + 1][0] - path_nodes[i][0],
            path_nodes[i + 1][1] - path_nodes[i][1],
            path_nodes[i + 1][2] - path_nodes[i][2],
        )
        if prev_dir != next_dir:
            bends += 1
    return bends
