# LLM Agent 구현 완전 가이드

> 이 프로젝트의 AI 핵심 엔진이 어떻게 동작하는지 처음부터 끝까지 설명합니다.

---

## 1. LLM Agent가 뭔가요?

### 일반 LLM (ChatGPT 같은 것)
```
사용자: "N2 배관 어떻게 연결해?"
LLM:    "이렇게 하면 됩니다~" (그냥 텍스트 답변)
```
- 질문 하나 → 답변 하나
- 실제로 뭔가를 "실행"하지는 않음

### LLM Agent (이 프로젝트)
```
사용자: "GAS-N2-001에서 CHAMBER-A까지 배관 연결해줘"
Agent:  1. DB에서 장비 위치 실제로 조회
        2. 경로 계산 알고리즘 실제로 실행
        3. LLM한테 전략 물어봄
        4. 결과 DB에 실제로 저장
        5. "검증 실패" → 스스로 재계획 결정
        → 최종 설계 결과 반환
```
- 여러 단계를 순서대로 실행
- 도구(DB, 알고리즘)를 실제로 사용
- 결과를 스스로 검증하고 재시도

**핵심 차이: LLM이 "말"만 하는 게 아니라 "행동"합니다.**

---

## 2. 이 프로젝트에서 LLM Agent가 어디에 있나?

```
dinnoMiniProject/
└── agent-service/                    ← LLM Agent가 사는 서비스 (포트 8001)
    ├── main.py                       ← FastAPI 서버 진입점
    ├── graph_agent/
    │   ├── state.py                  ← 공유 메모리 정의
    │   ├── pipeline.py               ← 5개 노드를 연결하는 파이프라인
    │   └── nodes.py                  ← 노드 5개 함수 구현 (핵심 코드)
    ├── tools/
    │   ├── neo4j_tool.py             ← Neo4j DB 조회 도구
    │   ├── pathfinding.py            ← A* 경로 탐색 알고리즘
    │   └── optimizer.py              ← OR-Tools 최적화
    ├── services/
    │   └── graphrag.py               ← 하이브리드 검색 (벡터 + 그래프)
    └── routers/
        └── agent.py                  ← HTTP 엔드포인트 (외부에서 호출하는 문)
```

---

## 3. 요청부터 응답까지 전체 흐름

```
[사용자가 Swagger에서 버튼 클릭]
         │
         │  POST /api/v1/agent/hookup-design
         ▼
┌─────────────────────────┐
│   main-service :8000    │  ← 문지기 역할. 요청 검증 후 전달
│   routers/agent.py      │
└────────────┬────────────┘
             │
             │  POST /internal/run-hookup-agent (내부 HTTP 호출)
             ▼
┌─────────────────────────────────────────────────┐
│   agent-service :8001                           │
│   routers/agent.py → run_hookup_agent()         │
│                                                 │
│   1. AgentState 초기화 (빈 공유 메모리 생성)    │
│   2. pipeline.invoke(initial_state) 호출        │
│                                                 │
│   ┌─────────────────────────────────────────┐   │
│   │  LangGraph 파이프라인 실행              │   │
│   │                                         │   │
│   │  Node 1: retrieve_node()                │   │
│   │    → Neo4j에서 장비 좌표, 장애물 조회   │   │
│   │    → state에 좌표 저장                  │   │
│   │         ↓                               │   │
│   │  Node 2: plan_node()                    │   │
│   │    → ChromaDB 벡터 검색                 │   │
│   │    → Gemini API 호출 (전략 수립)        │   │
│   │    → state에 전략 저장                  │   │
│   │         ↓                               │   │
│   │  Node 3: execute_node()                 │   │
│   │    → A* 알고리즘 경로 계산              │   │
│   │    → OR-Tools 최적화                    │   │
│   │    → Neo4j에 결과 저장                  │   │
│   │    → state에 경로 저장                  │   │
│   │         ↓                               │   │
│   │  Node 4: reflect_validate_node()        │   │
│   │    → 규칙 검증 (꺾임 횟수 등)           │   │
│   │    → Gemini API 호출 (UHP 표준 검증)    │   │
│   │    → state에 검증 결과 저장             │   │
│   │         ↓                               │   │
│   │  [분기] should_replan()                 │   │
│   │    검증 실패 AND 재계획 3회 미만?        │   │
│   │    → YES: Node 2로 돌아감 (재계획)      │   │
│   │    → NO:  Node 5로 진행                 │   │
│   │         ↓                               │   │
│   │  Node 5: human_in_loop_node()           │   │
│   │    → 최종 결과를 JSON으로 포맷팅        │   │
│   │    → state에 final_design 저장          │   │
│   └─────────────────────────────────────────┘   │
│                                                 │
│   3. final_state 반환                           │
└─────────────────┬───────────────────────────────┘
                  │
                  │  JSON 응답
                  ▼
         [사용자 화면에 결과 표시]
```

---

## 4. LangGraph란? (State Machine 개념)

LangGraph는 **"여러 단계를 순서대로 실행하는 그래프"** 라이브러리입니다.

### State Machine이란?
자동판매기를 생각해보세요:
```
[대기중] → 돈 투입 → [돈 받음] → 버튼 클릭 → [음료 나옴] → [대기중]
```
각 상태에서 특정 조건이 되면 다음 상태로 이동합니다.

이 프로젝트도 똑같습니다:
```
[retrieve] → [plan] → [execute] → [reflect] → 검증 실패? → [plan] (반복)
                                             → 검증 성공? → [human_loop] → 종료
```

### 핵심 파일: `agent-service/graph_agent/pipeline.py`

```python
workflow = StateGraph(AgentState)   # 그래프 생성

# 노드 등록 (이름 → 함수 연결)
workflow.add_node("retrieve", retrieve_node)
workflow.add_node("plan", plan_node)
workflow.add_node("execute", execute_node)
workflow.add_node("reflect", reflect_validate_node)
workflow.add_node("human_loop", human_in_loop_node)

# 고정 경로 (항상 이 순서)
workflow.add_edge("retrieve", "plan")
workflow.add_edge("plan", "execute")
workflow.add_edge("execute", "reflect")
workflow.add_edge("human_loop", END)

# 조건부 경로 (reflect 결과에 따라 갈림)
workflow.add_conditional_edges(
    "reflect",        # reflect 노드 실행 후
    should_replan,    # 이 함수의 결과에 따라
    {
        "replan":  "plan",       # "replan" 반환 → plan으로 되돌아감
        "approve": "human_loop", # "approve" 반환 → human_loop로 진행
    }
)

app = workflow.compile()  # 파이프라인 완성
```

---

## 5. AgentState — 노드들이 공유하는 메모리

### 파일: `agent-service/graph_agent/state.py`

모든 노드가 하나의 딕셔너리(State)를 공유합니다.
노드는 자기가 채울 필드만 반환하면 LangGraph가 자동으로 병합합니다.

```python
class AgentState(TypedDict):
    # 사용자가 처음에 입력하는 값
    user_request: str       # "N2 가스를 챔버A까지 연결해줘"
    source_tag: str         # "GAS-N2-001"
    target_tag: str         # "CHAMBER-A"
    pipe_spec: str          # "UHP_N2"

    # Node 1이 채우는 값
    source_coords: dict     # {"x": 0, "y": 0, "z": 2.5}
    target_coords: dict     # {"x": 14, "y": 0, "z": 0}
    obstacles: list[dict]   # [{"obs_id": "COL-001", ...}]
    graph_context: str      # "GAS-N2-001은 HDR-MAIN-001에 연결됨..."

    # Node 2가 채우는 값
    routing_strategy: str   # "X축 우선 이동 후 장애물 회피..."
    required_fittings: list # ["VCR 피팅 x4", "90도 엘보 x2"]

    # Node 3이 채우는 값
    path_waypoints: list    # [{x:0,y:0,z:2.5}, {x:0.5,y:0,z:2.5}, ...]
    optimized_segments: list # SEG-001~009 세그먼트 정보

    # Node 4가 채우는 값
    is_valid: bool          # True / False
    validation_errors: list # ["꺾임 과다: 8회 (허용 3회)"]
    reflection_count: int   # 0 → 1 → 2 → 3 (최대)

    # Node 5가 채우는 값
    final_design: dict      # 최종 결과 전체
```

**비유:** 릴레이 달리기의 바통. 각 주자(노드)가 바통(state)을 받아서 자기 내용을 추가하고 다음 주자에게 넘깁니다.

---

## 6. 5개 노드 상세 설명

### 파일: `agent-service/graph_agent/nodes.py`

---

### Node 1: retrieve_node — 정보 수집

**역할:** 사용자 요청에서 필요한 정보를 Neo4j에서 꺼냅니다.

**LLM 사용:** ❌ (순수 DB 조회)

```python
def retrieve_node(state: dict) -> dict:
    tool = Neo4jPipingTool()  # Neo4j 연결 도구 생성

    # Neo4j에서 GAS-N2-001 좌표 조회
    source_info = tool.get_equipment_info("GAS-N2-001")
    # 결과: {"x": 0, "y": 0, "z": 2.5, "type": "GAS_SUPPLY"}

    # Neo4j에서 CHAMBER-A 좌표 조회
    target_info = tool.get_equipment_info("CHAMBER-A")
    # 결과: {"x": 14, "y": 0, "z": 0, "type": "PROCESS_CHAMBER"}

    # 배관망 위상 정보 조회 (두 장비 사이 경로 텍스트)
    graph_context = tool.get_piping_topology_context("GAS-N2-001", "CHAMBER-A")

    # 장애물(기둥, 보) 목록 조회
    obstacles = tool.get_all_obstacles()
    # 결과: [{"obs_id": "COL-001", "x": 4, "y": 0, "z": 0, ...}, ...]

    return {
        "source_coords": {"x": 0, "y": 0, "z": 2.5},
        "target_coords": {"x": 14, "y": 0, "z": 0},
        "graph_context": "GAS-N2-001 → HDR-MAIN-001 → ...",
        "obstacles": [...]
    }
```

**Neo4j 쿼리 코드:** `agent-service/tools/neo4j_tool.py`

---

### Node 2: plan_node — 전략 수립 (LLM 첫 번째 호출)

**역할:** LLM에게 "어떤 경로로 배관을 연결할지" 전략을 물어봅니다.

**LLM 사용:** ✅ Gemini API 호출

```python
def plan_node(state: dict) -> dict:
    # ChromaDB에서 UHP 배관 관련 스펙 문서 검색
    graph_rag = GraphRAGService()
    spec_context = graph_rag.vector_search("UHP 배관 연결 규정 재질 표준")
    # 결과: "UHP 가스 배관은 316L SUS 재질을 사용해야 하며..."

    # 재계획 시 이전 실패 이유를 프롬프트에 포함
    error_context = ""
    if state["validation_errors"]:
        error_context = "이전 실패 원인: 꺾임 횟수 초과. 더 직선적인 경로 필요"

    # LLM에게 전략 수립 요청
    prompt = f"""
    출발: GAS-N2-001 (좌표: 0,0,2.5)
    목적지: CHAMBER-A (좌표: 14,0,0)
    배관망 현황: {state['graph_context']}
    UHP 규정: {spec_context}
    장애물: {state['obstacles']}
    {error_context}

    JSON으로 라우팅 전략을 알려주세요.
    """

    llm = _get_llm()  # Gemini 인스턴스 가져오기
    response = llm.invoke([HumanMessage(content=prompt)])

    # LLM 응답에서 JSON 파싱
    parsed = _parse_json_from_llm(response.content)

    return {
        "routing_strategy": parsed["routing_strategy"],
        "required_fittings": parsed["required_fittings"]
    }
```

**GraphRAG 코드:** `agent-service/services/graphrag.py`

---

### Node 3: execute_node — 실제 계산 실행

**역할:** LLM의 전략을 바탕으로 실제 수학적 계산을 합니다.

**LLM 사용:** ❌ (순수 알고리즘)

```python
def execute_node(state: dict) -> dict:
    # A* 알고리즘으로 3D 공간에서 최단 경로 탐색
    # - 격자 간격: 0.5m
    # - 장애물 격자는 통과 불가
    # - 꺾임 발생 시 0.8m 패널티 추가 (직선 경로 선호)
    result = find_shortest_path_astar(
        source={"x": 0, "y": 0, "z": 2.5},
        target={"x": 14, "y": 0, "z": 0},
        obstacles=[{"x": 4, "y": 0, "z": 0, ...}]
    )
    waypoints, path_cost = result
    # waypoints = [{x:0,y:0,z:2.5}, {x:0.5,y:0,z:2.5}, ..., {x:14,y:0,z:0}]

    # OR-Tools로 배관 세그먼트 최적화
    # - 연속된 같은 방향 포인트를 하나의 세그먼트로 묶음
    # - 총 꺾임 횟수 최소화
    opt_result = optimize_pipe_routing(waypoints, "UHP_N2")
    # opt_result.selected_segments = [SEG-001(직선 11.5m), SEG-002(꺾임), ...]

    # Neo4j에 설계 결과 저장 (AS_DESIGNED 상태로)
    tool.save_designed_pipe(
        source_tag="GAS-N2-001",
        target_tag="CHAMBER-A",
        pipe_id="AI-PIPE-GAS-N2-001-CHAMBER-A",
        path_waypoints=waypoints
    )

    return {
        "path_waypoints": waypoints,
        "optimized_segments": opt_result.selected_segments,
        "path_cost": 22.9
    }
```

**A* 코드:** `agent-service/tools/pathfinding.py`
**OR-Tools 코드:** `agent-service/tools/optimizer.py`

---

### Node 4: reflect_validate_node — 자가 검증 (LLM 두 번째 호출)

**역할:** 계산 결과가 UHP 표준을 지키는지 검증합니다.

**LLM 사용:** ✅ Gemini API 호출 (도메인 전문가 역할)

```python
def reflect_validate_node(state: dict) -> dict:
    reflection_count = state["reflection_count"] + 1

    # ── 1단계: 규칙 기반 검증 (LLM 없이, 빠름) ──
    errors = []
    total_length = 16.5  # 세그먼트 길이 합산
    total_bends = 8      # 꺾임 횟수 합산

    if total_length > 50:
        errors.append("배관 길이 초과")

    max_bends = max(3, int(total_length / 10) * 3)  # = 3
    if total_bends > max_bends:
        errors.append(f"꺾임 과다: {total_bends}회 (허용 {max_bends}회)")
    # → errors = ["꺾임 과다: 8회 (허용 3회)"]

    # ── 2단계: LLM 검증 (도메인 지식 적용, 느림) ──
    prompt = f"""
    배관 총 길이: 16.5m, 꺾임: 8회
    규칙 검증 결과: {errors}

    UHP 반도체 배관 표준 기준으로 추가 위반 사항이 있나요?
    JSON으로 답변해주세요.
    """
    response = llm.invoke(messages)
    # LLM 응답: {"is_valid": false, "llm_violations": ["압력강하 과다 우려"]}

    return {
        "validation_errors": errors + llm_violations,
        "is_valid": False,
        "reflection_count": 3   # 1 → 2 → 3 으로 증가
    }
```

---

### 조건부 분기: should_replan()

**Node 4 이후 어디로 갈지 결정하는 함수**

```python
def should_replan(state: dict) -> str:
    is_valid = state["is_valid"]           # False
    reflection_count = state["reflection_count"]  # 3

    if not is_valid and reflection_count < 3:
        return "replan"   # → Node 2 (plan)으로 돌아감

    # 3회 초과 or 검증 통과
    return "approve"  # → Node 5 (human_loop)으로 진행
```

**실제 실행에서 일어난 일:**
```
1회차: reflect → is_valid=False, count=1 → replan → plan → execute → reflect
2회차: reflect → is_valid=False, count=2 → replan → plan → execute → reflect
3회차: reflect → is_valid=False, count=3 → approve (최대 횟수 초과) → human_loop
```

---

### Node 5: human_in_loop_node — 최종 포맷팅

**역할:** 최종 결과를 엔지니어가 읽기 좋은 형태로 정리합니다.

**LLM 사용:** ❌

```python
def human_in_loop_node(state: dict) -> dict:
    final_design = {
        "design_id": "HOOKUP-GAS-N2-001-CHAMBER-A",
        "status": "PENDING_APPROVAL",   # 엔지니어 승인 대기
        "summary": {
            "total_length_m": 16.5,
            "total_bends": 8,
        },
        "routing_strategy": state["routing_strategy"],
        "required_fittings": state["required_fittings"],
        "path_waypoints": state["path_waypoints"],
        "segments": state["optimized_segments"],
        "validation": {
            "is_valid": False,
            "errors": ["꺾임 과다: 8회 (허용 3회)"],
            "reflection_rounds": 3
        },
        "message": "검증 실패. 수동 검토가 필요합니다."
    }
    return {"final_design": final_design}
```

---

## 7. LLM이 실제로 어떻게 호출되나?

### 파일: `agent-service/graph_agent/nodes.py` 상단

```python
def _get_llm():
    """설정에 따라 LLM 인스턴스를 반환합니다."""
    from core.config import settings

    if settings.LLM_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key="AIza...",
            temperature=0,   # 0 = 창의성 없음, 항상 동일한 답변 (재현성 중요)
        )
```

```python
# 실제 호출 방법
llm = _get_llm()
response = llm.invoke([HumanMessage(content=prompt)])
print(response.content)  # LLM의 텍스트 응답
```

**LangChain을 쓰는 이유:**
- `ChatGoogleGenerativeAI`, `ChatAnthropic`, `ChatOpenAI` 모두 같은 `.invoke()` 인터페이스
- `.env`에서 `LLM_PROVIDER=google` 한 줄만 바꾸면 어떤 LLM으로도 교체 가능

---

## 8. 코드 파일 위치 한눈에 보기

| 무엇을 보고 싶을 때 | 파일 |
|---|---|
| 전체 파이프라인 구조 | `agent-service/graph_agent/pipeline.py` |
| 공유 메모리 구조 | `agent-service/graph_agent/state.py` |
| 5개 노드 구현 | `agent-service/graph_agent/nodes.py` |
| Neo4j Cypher 쿼리 | `agent-service/tools/neo4j_tool.py` |
| A* 경로 알고리즘 | `agent-service/tools/pathfinding.py` |
| OR-Tools 최적화 | `agent-service/tools/optimizer.py` |
| 벡터 + 그래프 검색 | `agent-service/services/graphrag.py` |
| HTTP 엔드포인트 | `agent-service/routers/agent.py` |
| 환경 설정 | `core/config.py` |

---

## 9. 면접/업무에서 이야기할 수 있는 포인트

1. **LangGraph StateGraph 패턴**
   - "State Machine으로 AI 파이프라인을 구현했습니다. 각 노드는 독립적으로 테스트 가능하고, 상태는 TypedDict로 명시적으로 관리됩니다."

2. **Reflection 패턴**
   - "Node 4에서 LLM이 자신의 출력을 재검증하고, 실패 시 Node 2로 회귀하는 Self-Reflection 패턴을 구현했습니다. 최대 3회 재시도로 무한루프를 방지합니다."

3. **GraphRAG Hybrid Search**
   - "단순 벡터 검색만으로는 배관망 위상(토폴로지) 정보를 얻을 수 없습니다. Neo4j Cypher 검색과 ChromaDB 벡터 검색을 결합해 LLM에 더 정확한 컨텍스트를 제공합니다."

4. **결정론적 도구 + LLM 분리**
   - "경로 계산(A*)과 최적화(OR-Tools)는 결정론적 알고리즘으로 처리하고, LLM은 전략 수립과 도메인 검증에만 사용합니다. 이 분리로 재현성과 성능을 확보합니다."
