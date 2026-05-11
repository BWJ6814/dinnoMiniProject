# LLM Agent 구현 완전 가이드

> 버스에서 읽는 용. 이 프로젝트의 AI 핵심 엔진이 어떻게 동작하는지
> 코드 한 줄씩 처음부터 끝까지 설명합니다.

---

## 목차

1. LLM Agent란?
2. 프로젝트 전체 구조
3. 요청부터 응답까지 전체 흐름
4. LangGraph란?
5. AgentState — 공유 메모리
6. 노드 0: 파이프라인 진입점 (routers/agent.py)
7. Node 1: retrieve_node — DB 조회
8. Node 2: plan_node — LLM 전략 수립
9. Node 3: execute_node — A* + OR-Tools
10. Node 4: reflect_validate_node — 자가 검증
11. Node 5: human_in_loop_node — 최종 포맷팅
12. 조건부 분기: should_replan
13. GraphRAG — 하이브리드 검색
14. Neo4j Cypher 쿼리
15. 면접 포인트

---

## 1. LLM Agent란?

### 일반 LLM (ChatGPT)
```
나: "N2 배관 어떻게 연결해?"
AI: "이렇게 하면 됩니다~" (텍스트 답변만)
```
- 질문 1개 → 답변 1개
- 실제로 DB 조회, 계산, 저장을 직접 하지 않음

### LLM Agent (이 프로젝트)
```
나: "GAS-N2-001에서 CHAMBER-A까지 배관 연결해줘"

Agent 내부에서 일어나는 일:
  Step 1. Neo4j DB에서 두 장비 좌표 직접 조회
  Step 2. LLM에게 "어떤 전략으로 배관 설계할까?" 질문
  Step 3. A* 알고리즘으로 3D 경로 계산
  Step 4. OR-Tools로 세그먼트 최적화
  Step 5. Neo4j에 결과 직접 저장
  Step 6. LLM에게 "이 경로 표준 위반 없어?" 재검증
  Step 7. 실패 시 Step 2로 돌아가서 재계획 (최대 3회)
  Step 8. 최종 결과 반환

나: JSON 결과 수신
```
- 여러 단계를 순서대로 실행 (Multi-step Pipeline)
- 도구(DB, 알고리즘)를 실제로 사용 (Tool Use)
- 결과를 스스로 검증하고 재시도 (Self-Reflection)
- LLM은 "전략 수립"과 "검증"에만 사용, 계산은 알고리즘이 담당

---

## 2. 프로젝트 전체 구조

```
dinnoMiniProject/
│
├── core/                          ← 두 서비스가 공유하는 모듈
│   ├── config.py                  ← .env 파일 읽기 (API 키, DB 주소 등)
│   ├── neo4j_handler.py           ← Neo4j 연결 관리
│   └── seed_data.py               ← 샘플 FAB 데이터 삽입
│
├── agent-service/                 ← ★ LLM Agent가 사는 곳 (포트 8001)
│   ├── main.py                    ← FastAPI 서버 시작
│   ├── graph_agent/
│   │   ├── state.py               ← AgentState 정의 (공유 메모리 구조)
│   │   ├── pipeline.py            ← 5노드 파이프라인 연결
│   │   └── nodes.py               ← ★★ 5개 노드 함수 (핵심 중의 핵심)
│   ├── tools/
│   │   ├── neo4j_tool.py          ← Neo4j Cypher 쿼리 모음
│   │   ├── pathfinding.py         ← A* 알고리즘
│   │   └── optimizer.py           ← OR-Tools 최적화
│   ├── services/
│   │   └── graphrag.py            ← 벡터 검색 + 그래프 검색 결합
│   └── routers/
│       └── agent.py               ← HTTP 엔드포인트 (외부에서 부르는 문)
│
├── main-service/                  ← API Gateway (포트 8000)
│   ├── routers/
│   │   ├── agent.py               ← POST /api/v1/agent/hookup-design
│   │   ├── verify.py              ← POST /api/v1/verify/consistency
│   │   └── graph.py               ← GET /api/v1/graph/equipment 등
│   └── services/
│       ├── agent_client.py        ← agent-service HTTP 호출
│       └── consistency.py         ← ICP 정합성 검증 (Open3D/NumPy)
│
├── docker-compose.yml
├── requirements.txt
└── .env
```

---

## 3. 요청부터 응답까지 전체 흐름

```
[Swagger UI에서 Execute 버튼 클릭]
  POST /api/v1/agent/hookup-design
  body: { source_tag: "GAS-N2-001", target_tag: "CHAMBER-A", ... }
         │
         ▼
┌─────────────────────────────────────────────┐
│  main-service/routers/agent.py              │
│                                             │
│  async def design_hookup(request):          │
│    # 요청 검증만 하고 agent-service로 전달   │
│    result = await run_hookup_agent(request) │
│    return result                            │
└──────────────────┬──────────────────────────┘
                   │ HTTP POST
                   │ http://agent-service:8001/internal/run-hookup-agent
                   ▼
┌─────────────────────────────────────────────────────────┐
│  agent-service/routers/agent.py                         │
│                                                         │
│  async def run_hookup_agent(request):                   │
│    initial_state = {                                    │
│      "user_request": "N2 가스를 챔버A까지...",           │
│      "source_tag": "GAS-N2-001",                        │
│      "target_tag": "CHAMBER-A",                         │
│      "pipe_spec": "UHP_N2",                             │
│      # 나머지 필드는 모두 빈 값으로 초기화              │
│    }                                                    │
│    pipeline = get_pipeline()         # 파이프라인 가져오기│
│    final_state = pipeline.invoke(initial_state)  # 실행  │
│    return final_state["final_design"]                   │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
     LangGraph 파이프라인 실행 (순서대로)
     ┌──────────┐
     │ retrieve │ ← Node 1: Neo4j에서 좌표, 장애물 조회
     └────┬─────┘
          │
     ┌────▼─────┐
     │   plan   │ ← Node 2: LLM에게 전략 수립 요청 (Gemini 1차 호출)
     └────┬─────┘
          │
     ┌────▼─────┐
     │ execute  │ ← Node 3: A* 경로 계산 + OR-Tools 최적화 + Neo4j 저장
     └────┬─────┘
          │
     ┌────▼─────┐
     │ reflect  │ ← Node 4: LLM에게 검증 요청 (Gemini 2차 호출)
     └────┬─────┘
          │
    검증 실패 AND 재계획 < 3회?
     YES │                   NO │
         │                      │
    ┌────▼─────┐          ┌─────▼──────┐
    │  plan    │ (재계획)  │ human_loop │ ← Node 5: 최종 JSON 포맷팅
    └──────────┘          └─────┬──────┘
                                │
                           최종 응답 반환
```

---

## 4. LangGraph란?

### 핵심 개념: State Machine (상태 기계)

자판기를 생각해보세요:
```
[대기] → 돈 넣기 → [돈 받음] → 버튼 클릭 → [상품 나옴] → [대기]
```
각 상태(State)에서 조건에 따라 다음 상태로 이동합니다.

LangGraph도 똑같습니다. 각 "노드"가 State를 받아서 처리하고 다음 노드로 넘깁니다.

### 파일: `agent-service/graph_agent/pipeline.py`

```python
from langgraph.graph import StateGraph, END
from graph_agent.state import AgentState
from graph_agent.nodes import (
    retrieve_node, plan_node, execute_node,
    reflect_validate_node, human_in_loop_node, should_replan
)

def build_hookup_pipeline():

    # ① 그래프 생성 (AgentState를 공유 메모리로 사용)
    workflow = StateGraph(AgentState)

    # ② 노드 등록 (이름 → 함수)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("plan",     plan_node)
    workflow.add_node("execute",  execute_node)
    workflow.add_node("reflect",  reflect_validate_node)
    workflow.add_node("human_loop", human_in_loop_node)

    # ③ 시작점 설정
    workflow.set_entry_point("retrieve")

    # ④ 고정 엣지 (항상 이 순서로 실행)
    workflow.add_edge("retrieve",   "plan")
    workflow.add_edge("plan",       "execute")
    workflow.add_edge("execute",    "reflect")
    workflow.add_edge("human_loop", END)      # END = LangGraph 종료 신호

    # ⑤ 조건부 엣지 (reflect 결과에 따라 분기)
    workflow.add_conditional_edges(
        "reflect",       # reflect 노드 실행 후 이 함수 호출
        should_replan,   # 반환값: "replan" 또는 "approve"
        {
            "replan":  "plan",       # "replan" → plan으로 돌아감
            "approve": "human_loop", # "approve" → human_loop로 진행
        }
    )

    # ⑥ 컴파일 (그래프 검증 + 실행 준비)
    app = workflow.compile()
    return app

# 싱글톤 패턴: 서버 시작 시 한 번만 빌드
_pipeline = None
def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = build_hookup_pipeline()
    return _pipeline
```

---

## 5. AgentState — 노드들이 공유하는 메모리

### 파일: `agent-service/graph_agent/state.py`

```python
from typing import TypedDict

class AgentState(TypedDict):
    # ── 사용자 입력 (파이프라인 시작 시 채워짐) ──────────
    user_request: str       # "N2 가스를 챔버A까지 연결해줘"
    source_tag: str         # "GAS-N2-001"
    target_tag: str         # "CHAMBER-A"
    pipe_spec: str          # "UHP_N2"

    # ── Node 1 (retrieve)가 채우는 필드 ─────────────────
    graph_context: str      # Neo4j 위상 정보 텍스트
    source_coords: dict     # {"x": 0.0, "y": 0.0, "z": 2.5}
    target_coords: dict     # {"x": 14.0, "y": 0.0, "z": 0.0}
    obstacles: list[dict]   # [{"obs_id": "COL-001", "x": 4, ...}]

    # ── Node 2 (plan)가 채우는 필드 ─────────────────────
    routing_strategy: str   # LLM이 제안한 전략 텍스트
    required_fittings: list # ["VCR 피팅 x4", "90도 LR 엘보 x2"]

    # ── Node 3 (execute)가 채우는 필드 ──────────────────
    computed_path: list     # ["GAS-N2-001", "WP(0.5,0,2.5)", ..., "CHAMBER-A"]
    path_waypoints: list    # [{"x":0,"y":0,"z":2.5}, {"x":0.5,...}, ...]
    path_cost: float        # 22.9 (거리 + 꺾임 패널티 합산)
    optimized_segments: list  # [{"segment_id": "SEG-001", "length_m": 11.5, ...}]

    # ── Node 4 (reflect)가 채우는 필드 ──────────────────
    validation_errors: list # ["꺾임 과다: 8회 (허용 3회)"]
    is_valid: bool          # True / False
    reflection_count: int   # 재계획 횟수 (0→1→2→3, 3이 되면 강제 종료)

    # ── Node 5 (human_loop)가 채우는 필드 ───────────────
    final_design: dict      # 최종 결과 딕셔너리 전체
```

**핵심 규칙:**
- 각 노드는 `state` 전체를 받지만, 자기가 담당하는 필드만 반환합니다
- LangGraph가 반환된 딕셔너리를 기존 state에 병합(merge)합니다

```python
# 노드 함수의 기본 형태
def some_node(state: dict) -> dict:
    # state에서 필요한 값 읽기
    source = state["source_tag"]

    # 처리 후 자기 담당 필드만 반환
    return {
        "routing_strategy": "X축 우선...",   # 이것만 반환
        "required_fittings": ["VCR 피팅 x4"] # 이것만 반환
        # 나머지 필드는 건드리지 않음
    }
```

---

## 6. 노드 0: 파이프라인 진입점

### 파일: `agent-service/routers/agent.py`

```python
class HookupDesignRequest(BaseModel):
    user_request: str = Field(..., description="자연어 배관 설계 요청")
    source_tag: str   = Field(..., description="출발 장비 태그")
    target_tag: str   = Field(..., description="목적지 장비 태그")
    pipe_spec: str    = Field(default="UHP_N2", description="배관 스펙")

@router.post("/run-hookup-agent")
async def run_hookup_agent(request: HookupDesignRequest):

    # ① AgentState 초기값 설정 (나머지는 각 노드가 채울 예정)
    initial_state: AgentState = {
        "user_request": request.user_request,
        "source_tag":   request.source_tag,
        "target_tag":   request.target_tag,
        "pipe_spec":    request.pipe_spec,
        # 아래는 모두 빈 값 → 각 노드가 채워나감
        "graph_context": "",
        "source_coords": {},
        "target_coords": {},
        "obstacles": [],
        "routing_strategy": "",
        "required_fittings": [],
        "computed_path": [],
        "path_waypoints": [],
        "path_cost": 0.0,
        "optimized_segments": [],
        "validation_errors": [],
        "is_valid": False,
        "reflection_count": 0,
        "final_design": {},
    }

    # ② 파이프라인 실행 (이 한 줄이 5개 노드를 순서대로 실행)
    pipeline = get_pipeline()
    final_state = pipeline.invoke(initial_state)

    # ③ 결과 반환
    return {
        "success": True,
        "final_design": final_state["final_design"],
        "reflection_rounds": final_state["reflection_count"],
        "is_valid": final_state["is_valid"],
    }
```

---

## 7. Node 1: retrieve_node — DB 조회

### 파일: `agent-service/graph_agent/nodes.py`

**역할:** Neo4j에서 장비 좌표, 배관망 위상, 장애물 정보를 꺼냅니다.
**LLM 사용:** ❌ 없음 (순수 DB 조회)

```python
def retrieve_node(state: dict) -> dict:
    from tools.neo4j_tool import Neo4jPipingTool
    tool = Neo4jPipingTool()   # Neo4j 연결

    source_tag = state["source_tag"]  # "GAS-N2-001"
    target_tag = state["target_tag"]  # "CHAMBER-A"

    # ① 출발 장비 좌표 조회
    source_info = tool.get_equipment_info(source_tag)
    # 결과: {"tag": "GAS-N2-001", "x": 0.0, "y": 0.0, "z": 2.5, "type": "GAS_SUPPLY"}

    # ② 목적지 장비 좌표 조회
    target_info = tool.get_equipment_info(target_tag)
    # 결과: {"tag": "CHAMBER-A", "x": 14.0, "y": 0.0, "z": 0.0, "type": "PROCESS_CHAMBER"}

    # ③ 배관 위상 컨텍스트 조회 (LLM에게 줄 참고 정보)
    graph_context = tool.get_piping_topology_context(source_tag, target_tag)
    # 결과: "=== 배관 위상 컨텍스트 ===\n출발 장비(GAS-N2-001)의 하류 연결 장비:\n..."

    # ④ 장애물 목록 조회 (A*가 회피해야 할 위치들)
    obstacles = tool.get_all_obstacles()
    # 결과: [
    #   {"obs_id": "COL-001", "type": "COLUMN", "x": 4.0, "y": 0.0, "z": 0.0, "radius_m": 0.3},
    #   {"obs_id": "COL-002", ...},
    # ]

    tool.close()  # 연결 반드시 닫기

    # 이 필드들만 반환 → LangGraph가 state에 병합
    return {
        "source_coords": {"x": source_info["x"], "y": source_info["y"], "z": source_info["z"]},
        "target_coords": {"x": target_info["x"], "y": target_info["y"], "z": target_info["z"]},
        "graph_context": graph_context,
        "obstacles": obstacles,
    }
```

---

## 8. Node 2: plan_node — LLM 전략 수립

### 파일: `agent-service/graph_agent/nodes.py`

**역할:** LLM에게 "어떤 전략으로 배관을 연결할지" 물어봅니다.
**LLM 사용:** ✅ Gemini 1차 호출

```python
def plan_node(state: dict) -> dict:
    from services.graphrag import GraphRAGService
    graph_rag = GraphRAGService()
    graph_rag.initialize()

    # ① 배관 스펙 문서 검색 (벡터 검색)
    spec_context = graph_rag.vector_search(
        f"{state['pipe_spec']} 배관 연결 규정 재질 표준"
    )
    # spec_context = "[UHP N2 배관 연결 표준]\nUHP(Ultra High Purity) N2 가스 배관은
    #                 SS316L EP 재질을 사용해야 합니다. 최소 관경은 1/4인치..."

    # ② 재계획일 경우 이전 실패 이유를 프롬프트에 포함
    error_context = ""
    if state.get("validation_errors"):
        error_context = "\n\n이전 계획의 문제점 (반드시 해결):\n"
        error_context += "\n".join(f"- {e}" for e in state["validation_errors"])
        # error_context = "이전 계획의 문제점:\n- 꺾임 과다: 8회 (허용 3회)"

    # ③ LLM 프롬프트 구성
    prompt = f"""당신은 반도체 FAB 배관 설계 전문가입니다.

[요청 정보]
원문: {state['user_request']}
출발 장비: {state['source_tag']} (좌표: {state['source_coords']})
목적지 장비: {state['target_tag']} (좌표: {state['target_coords']})
배관 스펙: {state['pipe_spec']}

[현재 배관망 위상 (Neo4j GraphRAG)]
{state['graph_context']}

[배관 스펙 규정 (Vector Search)]
{spec_context}

[장애물 정보]
{state['obstacles']}
{error_context}

다음 JSON 형식으로 응답하세요:
```json
{{
  "routing_strategy": "설계 전략 설명",
  "required_fittings": ["VCR 피팅 x4", "90도 LR 엘보 x2"],
  "preferred_direction": "X축 우선 이동 후 Y축",
  "special_constraints": ["기둥 COL-001 좌측으로 우회"]
}}
```"""

    # ④ LLM 호출
    llm = _get_llm()          # Gemini 인스턴스 가져오기
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    # response.content = '```json\n{"routing_strategy": "GAS-N2-001에서...", ...}\n```'

    # ⑤ 응답에서 JSON 추출
    parsed = _parse_json_from_llm(response.content)
    routing_strategy  = parsed.get("routing_strategy", response.content[:500])
    required_fittings = parsed.get("required_fittings", ["VCR 피팅 x4", "90도 LR 엘보 x2"])

    return {
        "routing_strategy": routing_strategy,
        "required_fittings": required_fittings,
    }
```

**`_get_llm()` 함수:**

```python
def _get_llm():
    from core.config import settings

    if settings.LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=0,    # 0 = 항상 같은 결과 (재현성 보장)
        )
    elif settings.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model="claude-sonnet-4-6",
            api_key=settings.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=2048,
        )
    else:  # openai
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model="gpt-4o", api_key=settings.OPENAI_API_KEY, temperature=0)
```

**LangChain을 쓰는 이유:**
모든 LLM이 `.invoke()` 하나로 통일됩니다. `.env`에서 `LLM_PROVIDER=google` 한 줄만 바꾸면 Gemini ↔ Claude ↔ GPT 교체가 됩니다.

---

## 9. Node 3: execute_node — A* + OR-Tools

### 파일: `agent-service/graph_agent/nodes.py`

**역할:** LLM 전략을 바탕으로 실제 수학적 계산을 합니다.
**LLM 사용:** ❌ 없음 (순수 알고리즘)

```python
def execute_node(state: dict) -> dict:
    from tools.pathfinding import find_shortest_path_astar
    from tools.optimizer import optimize_pipe_routing

    source_coords = state["source_coords"]  # {"x": 0, "y": 0, "z": 2.5}
    target_coords = state["target_coords"]  # {"x": 14, "y": 0, "z": 0}
    obstacles     = state["obstacles"]      # [{"obs_id": "COL-001", ...}]
    pipe_spec     = state["pipe_spec"]      # "UHP_N2"

    # ① A* 알고리즘으로 3D 최단 경로 탐색
    result = find_shortest_path_astar(source_coords, target_coords, obstacles)
    waypoints, path_cost = result
    # waypoints = [
    #   {"x":0.0, "y":0.0, "z":2.5},   ← 출발
    #   {"x":0.5, "y":0.0, "z":2.5},   ← 0.5m 이동
    #   {"x":1.0, "y":0.0, "z":2.5},   ← 계속...
    #   ...
    #   {"x":14.0, "y":0.0, "z":0.0}   ← 도착
    # ]
    # path_cost = 22.9 (거리 + 꺾임 패널티 합산)

    # ② OR-Tools로 배관 세그먼트 최적화
    opt_result = optimize_pipe_routing(waypoints, pipe_spec)
    # opt_result.selected_segments = [
    #   PipeSegment(id="SEG-001", 직선 11.5m, 꺾임 0회),
    #   PipeSegment(id="SEG-002", 0.5m, 꺾임 1회),  ← 방향 바뀌는 지점
    #   ...
    # ]

    # ③ Neo4j에 설계 결과 저장
    from tools.neo4j_tool import Neo4jPipingTool
    tool = Neo4jPipingTool()
    tool.save_designed_pipe(
        source_tag="GAS-N2-001",
        target_tag="CHAMBER-A",
        pipe_id="AI-PIPE-GAS-N2-001-CHAMBER-A",
        spec="UHP_N2",
        path_waypoints=waypoints,
    )
    tool.close()

    return {
        "path_waypoints": waypoints,
        "path_cost": round(path_cost, 3),
        "optimized_segments": [
            {
                "segment_id": seg.segment_id,
                "from_point": seg.from_point,
                "to_point":   seg.to_point,
                "length_m":   seg.length_m,
                "bend_count": seg.bend_count,
            }
            for seg in opt_result.selected_segments
        ],
    }
```

### A* 알고리즘 상세: `agent-service/tools/pathfinding.py`

```python
GRID_RESOLUTION = 0.5  # 3D 공간을 0.5m 격자로 분할
BEND_PENALTY    = 0.8  # 꺾임 1회당 추가 비용 0.8m (꺾임 최소화 유도)

def find_shortest_path_astar(source_coords, target_coords, obstacles):

    # ① 3D 격자 그래프 생성
    G = build_3d_grid_graph(source_coords, target_coords, obstacles)
    # 출발-도착 사이 공간을 0.5m 격자로 분할
    # 장애물과 겹치는 격자점은 제외
    # 인접한 격자점끼리 엣지 연결 (6방향: ±X, ±Y, ±Z)

    # ② 연속 좌표 → 격자 인덱스 변환
    # (0.0, 0.0, 2.5) → (0, 0, 5)  [0.5m 단위이므로 2.5/0.5=5]
    source_node = _coord_to_node(source_coords["x"], source_coords["y"], source_coords["z"])
    target_node = _coord_to_node(target_coords["x"], target_coords["y"], target_coords["z"])

    # ③ A* 실행
    def heuristic(n1, n2):
        # h(n) = 현재 위치에서 목적지까지 직선 거리 (낙관적 추정)
        # 이 값이 실제보다 절대 크지 않으므로 A*가 최적해 보장
        return _euclidean_3d(_node_to_coord(n1), _node_to_coord(n2))

    path_nodes = nx.astar_path(G, source_node, target_node,
                               heuristic=heuristic, weight="weight")
    # path_nodes = [(0,0,5), (1,0,5), (2,0,5), ..., (28,0,0)]

    # ④ 격자 인덱스 → 실제 좌표로 역변환
    waypoints = [_node_to_coord(n) for n in path_nodes]
    # waypoints = [{"x":0,"y":0,"z":2.5}, {"x":0.5,"y":0,"z":2.5}, ...]

    # ⑤ 꺾임 횟수 계산 및 패널티 추가
    bend_count = _count_bends(path_nodes)  # 방향이 바뀌는 지점 수
    total_cost = path_length + bend_count * BEND_PENALTY

    return waypoints, total_cost


def _count_bends(path_nodes):
    """방향이 바뀌는 지점 수를 셉니다."""
    bends = 0
    for i in range(1, len(path_nodes) - 1):
        prev_dir = (path_nodes[i][0]-path_nodes[i-1][0], ...)  # 이전 방향 벡터
        next_dir = (path_nodes[i+1][0]-path_nodes[i][0], ...)  # 다음 방향 벡터
        if prev_dir != next_dir:   # 방향이 바뀌면 꺾임
            bends += 1
    return bends
```

**A* vs Dijkstra 차이:**
```
Dijkstra: 출발점에서 모든 방향으로 균등하게 퍼져나감
           → 불필요한 탐색이 많음

A*:       휴리스틱(목적지 방향)으로 유도되며 탐색
           → 훨씬 빠름, 특히 목적지가 명확할 때
```

### OR-Tools 상세: `agent-service/tools/optimizer.py`

```python
def optimize_pipe_routing(waypoints, pipe_spec):

    # ① 웨이포인트를 방향별 세그먼트로 분할
    raw_segments = _split_into_directional_segments(waypoints)
    # 같은 방향으로 계속 가는 점들을 하나의 세그먼트로 묶음
    # 예) (0→11.5m, X방향) = SEG-001 (직선, 꺾임 없음)
    #     (11.5→11.5m, Z방향 하강) = SEG-002 (꺾임 1회)

    # ② OR-Tools CP-SAT Solver로 최적화
    from ortools.sat.python import cp_model
    model = cp_model.CpModel()

    # 변수: 각 세그먼트 선택 여부 (0 또는 1)
    is_selected = [model.NewBoolVar(f"seg_{i}") for i in range(len(segments))]

    # 제약: 모든 세그먼트 필수 선택 (경로 연결성 유지)
    for var in is_selected:
        model.Add(var == 1)

    # 제약: 총 길이 ≤ 100m
    model.Add(sum(int(seg.length_m * 1000) * var for seg, var in ...) <= 100000)

    # 제약: 꺾임 횟수 ≤ 20회
    model.Add(sum(seg.bend_count * var for seg, var in ...) <= 20)

    # 목적: 총 비용 최소화 (길이 비용 + 꺾임 패널티)
    model.Minimize(sum(length_cost + bend_cost for each segment))

    # 풀기
    solver = cp_model.CpSolver()
    solver.Solve(model)
    # → OPTIMAL (최적해 발견) 또는 FEASIBLE (가능해 발견)
```

---

## 10. Node 4: reflect_validate_node — 자가 검증

### 파일: `agent-service/graph_agent/nodes.py`

**역할:** 계산 결과가 UHP 표준을 지키는지 검증합니다.
**LLM 사용:** ✅ Gemini 2차 호출

```python
def reflect_validate_node(state: dict) -> dict:

    reflection_count = state.get("reflection_count", 0) + 1  # 카운터 증가
    optimized_segs = state.get("optimized_segments", [])

    total_length = sum(s["length_m"] for s in optimized_segs)   # 16.5m
    total_bends  = sum(s["bend_count"] for s in optimized_segs) # 8회

    # ── 1단계: 규칙 기반 검증 (LLM 없이, 빠름) ────────────
    errors = []

    # 검증 1: 총 길이
    if total_length > 50:
        errors.append(f"배관 길이 초과: {total_length:.1f}m (권장 50m 이하)")

    # 검증 2: 꺾임 횟수 (UHP 표준: 길이 10m당 최대 3회)
    max_allowed_bends = max(3, int(total_length / 10) * 3)  # 16.5m → max 3회
    if total_bends > max_allowed_bends:
        errors.append(f"꺾임 과다: {total_bends}회 (허용 {max_allowed_bends}회)")
        # → "꺾임 과다: 8회 (허용 3회)" 추가됨

    # 검증 3: 경로 존재 여부
    if len(state.get("path_waypoints", [])) < 2:
        errors.append("유효한 경로가 계산되지 않았습니다.")

    # ── 2단계: LLM 기반 검증 (도메인 전문가 역할) ─────────
    llm = _get_llm()
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=(
            "당신은 반도체 FAB UHP 배관 설계 검증 전문가입니다. "
            "반드시 JSON 형식으로만 응답하세요."
        )),
        HumanMessage(content=f"""배관 설계 검증 요청:
배관 스펙: {state['pipe_spec']}
총 배관 길이: {total_length:.2f}m
총 꺾임 횟수: {total_bends}회
규칙 검증 결과: {errors if errors else "이상 없음"}

```json
{{
  "is_valid": true 또는 false,
  "llm_violations": ["추가 위반 사항"],
  "severity": "OK" 또는 "WARNING" 또는 "CRITICAL"
}}
```"""),
    ]

    response = llm.invoke(messages)
    parsed = _parse_json_from_llm(response.content)

    llm_violations = parsed.get("llm_violations", [])
    severity       = parsed.get("severity", "OK")
    llm_is_valid   = parsed.get("is_valid", True)

    # 규칙 검증 + LLM 검증 오류 합산
    all_errors = errors + llm_violations
    is_valid = len(all_errors) == 0 or (llm_is_valid and severity != "CRITICAL")

    return {
        "validation_errors": all_errors,  # ["꺾임 과다: 8회..."]
        "is_valid": is_valid,             # False
        "reflection_count": reflection_count,  # 1 → 2 → 3
    }
```

---

## 11. Node 5: human_in_loop_node — 최종 포맷팅

### 파일: `agent-service/graph_agent/nodes.py`

**역할:** 최종 결과를 엔지니어 검토용 JSON으로 정리합니다.
**LLM 사용:** ❌ 없음

```python
def human_in_loop_node(state: dict) -> dict:
    optimized_segs = state.get("optimized_segments", [])
    total_length = sum(s["length_m"] for s in optimized_segs)  # 16.5
    total_bends  = sum(s["bend_count"] for s in optimized_segs)  # 8

    final_design = {
        "design_id": f"HOOKUP-{state['source_tag']}-{state['target_tag']}",
        # → "HOOKUP-GAS-N2-001-CHAMBER-A"

        "status": "PENDING_APPROVAL",  # 엔지니어 승인 대기 상태

        "summary": {
            "source": state["source_tag"],    # "GAS-N2-001"
            "target": state["target_tag"],    # "CHAMBER-A"
            "pipe_spec": state["pipe_spec"],  # "UHP_N2"
            "total_length_m": 16.5,
            "total_bends": 8,
            "path_cost": state["path_cost"],  # 22.9
            "waypoint_count": 34,
        },

        "routing_strategy": state["routing_strategy"],   # LLM이 만든 전략
        "required_fittings": state["required_fittings"], # ["VCR 피팅 x4", ...]
        "path_waypoints": state["path_waypoints"],       # 34개 3D 좌표
        "segments": optimized_segs,                      # SEG-001~009

        "validation": {
            "is_valid": state["is_valid"],               # False
            "errors": state["validation_errors"],        # ["꺾임 과다..."]
            "reflection_rounds": state["reflection_count"],  # 3
        },

        "message": (
            "AI Agent 설계 완료. 시공 엔지니어의 최종 승인이 필요합니다."
            if state["is_valid"]
            else "검증 실패. 수동 검토가 필요합니다."
        ),
    }

    return {"final_design": final_design}
```

**실제 DDWorks에서는:**
- 여기서 엔지니어에게 카카오톡/이메일 알림 발송
- 엔지니어가 DDWorks 3D UI에서 경로 확인 후 승인/거부
- 승인 시 현장 Work Order 자동 생성

---

## 12. 조건부 분기: should_replan

### 파일: `agent-service/graph_agent/nodes.py`

```python
def should_replan(state: dict) -> str:
    """
    Node 4(reflect) 이후 어디로 갈지 결정.
    반환값이 pipeline.py의 conditional_edges 딕셔너리 키와 매칭됩니다.
    """
    is_valid         = state.get("is_valid", True)
    reflection_count = state.get("reflection_count", 0)

    if not is_valid and reflection_count < 3:
        # 검증 실패 AND 아직 3회 미만 → 재계획
        return "replan"   # → plan 노드로 돌아감

    # 검증 통과 OR 3회 초과 → 종료
    return "approve"  # → human_loop 노드로 진행
```

**이번 테스트에서 실제 일어난 일:**
```
1회차: reflect 실행 → is_valid=False, count=1 → "replan" 반환
         ↓ plan으로 돌아감 (error_context에 "꺾임 과다" 포함해서 재시도)
       plan → execute → reflect
2회차: reflect 실행 → is_valid=False, count=2 → "replan" 반환
         ↓ plan으로 돌아감
       plan → execute → reflect
3회차: reflect 실행 → is_valid=False, count=3 → "approve" 반환 (3회 초과)
         ↓ 어쩔 수 없이 human_loop로 진행
       human_loop → 응답 (status: PENDING_APPROVAL, message: "수동 검토 필요")
```

---

## 13. GraphRAG — 하이브리드 검색

### 파일: `agent-service/services/graphrag.py`

**GraphRAG = Graph + RAG (Retrieval Augmented Generation)**

일반 RAG의 한계:
- "UHP 가스 연결 표준이 뭐야?" → 벡터 검색으로 찾을 수 있음 ✅
- "VLV-001 밸브 닫으면 영향받는 하류 장비는?" → 벡터 검색으로 못 찾음 ❌

GraphRAG의 해결책:
```
질의: "CHAMBER-A 주변 여유 포트와 UHP 규정 알려줘"
  │
  ├─ Vector Search (ChromaDB)
  │   → 의미 유사한 문서 검색
  │   → "UHP N2 배관 연결 표준: SS316L EP 재질 사용, VCR 피팅 필수..."
  │
  └─ Graph Cypher Search (Neo4j)
      → CHAMBER-A 주변 연결 관계 탐색
      → "CHAMBER-A ← VLV-002 ← HDR-MAIN-001 ← GAS-N2-001"
  │
  두 결과 합쳐서 LLM에 전달
  → "CHAMBER-A는 현재 VLV-002를 통해 메인 헤더에 연결되어 있으며,
     UHP N2 규정상 SS316L EP 재질과 VCR 피팅을 사용해야 합니다."
```

```python
class GraphRAGService:

    def vector_search(self, query: str) -> str:
        """배관 스펙 문서에서 의미 유사한 내용 검색"""
        if self._vector_store:
            # ChromaDB로 코사인 유사도 기반 검색
            docs = self._vector_store.similarity_search(query, k=3)
            return "\n\n".join(doc.page_content for doc in docs)
        else:
            # ChromaDB 없을 때 키워드 폴백
            return self._keyword_fallback_search(query)

    def graph_cypher_search(self, query: str) -> str:
        """Neo4j에서 배관망 위상 정보 검색"""
        all_equip = self._neo4j_tool.get_all_equipment()
        all_pipes = self._neo4j_tool.get_all_piping()
        # 장비 목록과 배관 연결 관계를 텍스트로 반환

    def hybrid_query(self, query: str) -> str:
        """벡터 검색 + 그래프 검색 결과를 합쳐 LLM으로 최종 답변 생성"""
        vector_context = self.vector_search(query)
        graph_context  = self.graph_cypher_search(query)
        combined = f"[스펙 문서]\n{vector_context}\n\n[배관망 현황]\n{graph_context}"

        messages = [
            SystemMessage(content="반도체 FAB 배관 전문가로서 정확하게 답변하세요."),
            HumanMessage(content=f"질문: {query}\n\n참고 정보:\n{combined}")
        ]
        response = self._llm.invoke(messages)
        return response.content
```

**지식 베이스 (5개 문서):**
1. UHP N2 배관 연결 표준 (재질, 관경, VCR 피팅)
2. CCSS 케미컬 배관 안전 기준 (HF, PFA 재질)
3. 배관 꺾임(Bend) 설계 기준 (최소 곡률 반경)
4. 배관 압력 손실 계산 기준 (Darcy-Weisbach 공식)
5. As-Built 정합성 허용 오차 기준 (±50mm, ICP 알고리즘)

---

## 14. Neo4j Cypher 쿼리

### 파일: `agent-service/tools/neo4j_tool.py`

Neo4j는 관계형 DB(MySQL)와 다릅니다. 관계를 직접 탐색합니다.

```python
# 일반 RDB SQL (JOIN이 느림)
SELECT * FROM equipment e1
JOIN flows_to f ON e1.id = f.source_id
JOIN equipment e2 ON f.target_id = e2.id
WHERE e1.tag = 'GAS-N2-001'

# Neo4j Cypher (관계 탐색이 O(1)에 가까움)
MATCH (e:Equipment {tag: 'GAS-N2-001'})-[:FLOWS_TO]->(next:Equipment)
RETURN next
```

**이 프로젝트에서 쓰는 주요 쿼리:**

```python
# 장비 좌표 조회
"""
MATCH (e:Equipment {tag: $tag})
RETURN e.tag, e.name, e.x, e.y, e.z
"""

# 최대 5홉 하류 장비 조회 (재귀 탐색)
"""
MATCH (src:Equipment {tag: $tag})-[:FLOWS_TO*1..5]->(downstream:Equipment)
RETURN DISTINCT downstream.tag, downstream.name
LIMIT 20
"""
# *1..5 = 1~5단계 연결을 모두 탐색 (RDB에서는 재귀 쿼리 필요)

# 장애물 조회
"""
MATCH (o:Obstacle)
RETURN o.obs_id, o.type, o.x, o.y, o.z, o.radius_m
"""

# AI 설계 결과 저장
"""
MATCH (src:Equipment {tag: $source_tag})
MATCH (dst:Equipment {tag: $target_tag})
MERGE (src)-[r:FLOWS_TO {pipe_id: $pipe_id}]->(dst)
SET r.status = 'AS_DESIGNED',
    r.length_m = $length_m,
    r.created_by = 'AI_AGENT'
"""
# MERGE = 없으면 만들고, 있으면 업데이트 (중복 방지)
```

**Neo4j 브라우저로 직접 확인:**
1. `http://localhost:7474` 접속
2. ID: `neo4j`, PW: `ddworks1234`
3. 쿼리 입력:
```cypher
MATCH (n) RETURN n LIMIT 50
```
→ 장비, 배관, 장애물 노드가 그래프로 시각화됩니다.

---

## 15. 면접/업무에서 이야기할 수 있는 포인트

### "LangGraph를 왜 썼나요?"
> "Multi-step AI 파이프라인에서 각 노드의 상태를 명시적으로 관리하고,
> Reflection 패턴처럼 조건부 분기(재계획 루프)를 선언적으로 표현하기 위해
> 사용했습니다. 노드를 함수 단위로 분리해 독립 테스트가 가능하고,
> StateGraph의 조건부 엣지로 복잡한 워크플로우를 깔끔하게 구조화했습니다."

### "Reflection 패턴이 뭔가요?"
> "LLM이 자신의 출력을 스스로 재검증하는 패턴입니다. Node 3에서 경로를
> 계산한 뒤, Node 4에서 LLM이 UHP 표준 위반 여부를 확인합니다.
> 위반 발견 시 Node 2로 돌아가 재계획합니다. 무한루프 방지를 위해
> 최대 3회로 제한했습니다."

### "A*와 Dijkstra 차이를 설명해보세요."
> "Dijkstra는 출발점에서 모든 방향을 균등하게 탐색하지만,
> A*는 목적지 방향을 추정하는 휴리스틱 함수를 써서 탐색 방향을 유도합니다.
> 유클리드 거리를 휴리스틱으로 쓰면 실제 거리를 절대 과대평가하지 않아
> (허용 가능한 휴리스틱) 최적해가 보장됩니다."

### "GraphRAG가 일반 RAG와 다른 점은?"
> "일반 RAG는 벡터 유사도 검색만 합니다. 배관망처럼 연결성이 중요한
> 도메인에서는 '특정 밸브 차단 시 영향받는 하류 장비'같은 위상(topology)
> 정보를 벡터 검색으로 찾을 수 없습니다. Neo4j Cypher 검색을 추가해
> 관계 정보를 함께 LLM에 제공하면 훨씬 정확한 답변이 가능합니다."

### "LLM과 알고리즘을 왜 분리했나요?"
> "경로 계산(A*)과 최적화(OR-Tools)는 결정론적 알고리즘을 씁니다.
> 동일 입력에 동일 출력이 보장되어 재현성이 있고, LLM보다 훨씬 빠릅니다.
> LLM은 도메인 지식이 필요한 '전략 수립'과 '표준 위반 검증'에만 사용해
> 비용과 응답 시간을 최소화했습니다."
