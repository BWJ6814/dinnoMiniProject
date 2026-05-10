# DDWorks-Mini 프로젝트 진행 가이드

> 반도체 FAB 스마트 HookUp 배관 설계 플랫폼 **DDWorks**의 미니 버전.
> 화요일 입사 전 회사 소프트웨어 핵심 기술을 직접 구현해보는 프로젝트입니다.

---

## 프로젝트 구조

```
ddworks-mini/
├── core/                       # 두 서비스가 공유하는 핵심 모듈
│   ├── config.py               # 환경 변수 설정 (pydantic-settings)
│   ├── neo4j_handler.py        # Neo4j 컨텍스트 매니저 DB 핸들러
│   └── seed_data.py            # 반도체 FAB 샘플 데이터 시더
│
├── agent-service/              # AI 에이전트 서비스 (포트 8001)
│   ├── main.py                 # FastAPI 앱 진입점
│   ├── graph_agent/
│   │   ├── state.py            # LangGraph AgentState TypedDict
│   │   ├── nodes.py            # 5개 노드 함수 구현
│   │   └── pipeline.py         # StateGraph 컴파일 (5-노드 파이프라인)
│   ├── tools/
│   │   ├── neo4j_tool.py       # Cypher 쿼리 도구
│   │   ├── pathfinding.py      # A* 알고리즘 (NetworkX)
│   │   └── optimizer.py        # OR-Tools 배관 최적화
│   ├── services/
│   │   └── graphrag.py         # Hybrid Search (Vector + GraphCypher)
│   └── routers/
│       └── agent.py            # /internal/* 내부 API 엔드포인트
│
├── main-service/               # API Gateway (포트 8000)
│   ├── main.py                 # FastAPI 앱 진입점
│   ├── routers/
│   │   ├── agent.py            # POST /api/v1/agent/hookup-design
│   │   ├── verify.py           # POST /api/v1/verify/consistency
│   │   └── graph.py            # GET/POST /api/v1/graph/*
│   └── services/
│       ├── consistency.py      # Open3D ICP 정합성 검증
│       └── agent_client.py     # httpx 비동기 HTTP 클라이언트
│
├── docker-compose.yml          # Neo4j + 두 서비스 통합 실행
├── requirements.txt
├── .env.example
└── PROGRESS.md                 # ← 이 파일
```

---

## Step 0. 환경 설정

### 0-1. Python 환경 생성

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate
```

### 0-2. 패키지 설치

```bash
pip install -r requirements.txt
```

> **주의:** `open3d`는 Python 3.11 이하에서만 설치됩니다.
> `ortools`는 설치 실패 시 그리디 폴백 로직이 자동으로 사용됩니다.

### 0-3. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 열어 아래 값을 반드시 설정하세요:

```env
# Anthropic Claude API Key (https://console.anthropic.com/)
ANTHROPIC_API_KEY=sk-ant-your-key-here

# 또는 OpenAI 사용 시
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
OPENAI_API_KEY=sk-your-key-here
```

---

## Step 1. Neo4j 실행 (Docker 사용)

### 방법 A: Docker Compose로 전체 실행 (권장)

```bash
docker-compose up -d
```

서비스 상태 확인:
```bash
docker-compose ps
docker-compose logs -f agent-service
```

### 방법 B: Neo4j만 Docker로 실행 (로컬 개발)

```bash
docker run -d \
  --name ddworks-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/ddworks1234 \
  neo4j:5.25-community
```

Neo4j 브라우저: http://localhost:7474
- ID: `neo4j`
- PW: `ddworks1234`

---

## Step 2. 샘플 데이터 삽입

### 방법 A: API 호출 (서비스 실행 후)

```bash
curl -X POST http://localhost:8000/api/v1/graph/seed
```

### 방법 B: Python 직접 실행

```bash
cd ddworks-mini
python core/seed_data.py
```

삽입 데이터:
- 장비 10개: GAS-N2-001, GAS-AR-001, HDR-MAIN-001, VLV-001~003, CHAMBER-A/B, PUMP-EXH-001, CCSS-001
- 배관 9개 (AS_DESIGNED 상태)
- 장애물 4개: COL-001~003 (기둥), BEAM-001 (보)

---

## Step 3. 두 서비스 로컬 실행

터미널 1 - Agent Service (포트 8001):
```bash
cd ddworks-mini/agent-service
python main.py
```

터미널 2 - Main Service (포트 8000):
```bash
cd ddworks-mini
python -m main_service.main
# 또는
cd ddworks-mini/main-service
python main.py
```

---

## Step 4. API 테스트

### Swagger UI 접속

- **Main Service**: http://localhost:8000/docs
- **Agent Service**: http://localhost:8001/docs

---

### Feature A: Smart HookUp 배관 자동 설계

**요청:**
```bash
curl -X POST http://localhost:8000/api/v1/agent/hookup-design \
  -H "Content-Type: application/json" \
  -d '{
    "natural_language_request": "N2 가스 공급 장치에서 웨이퍼 챔버 A까지 최단 거리로 배관을 연결해줘. 기둥을 회피해야 해.",
    "source_tag": "GAS-N2-001",
    "target_tag": "CHAMBER-A",
    "pipe_spec": "UHP_N2"
  }'
```

**LangGraph 5-노드 처리 흐름:**
```
Node 1 (Retrieve)  → Neo4j에서 GAS-N2-001, CHAMBER-A 3D 좌표 + 기둥 위치 로드
Node 2 (Plan)      → LLM + GraphRAG로 라우팅 전략 수립
Node 3 (Execute)   → A* 알고리즘으로 기둥 COL-001, COL-002 회피 경로 계산
                     OR-Tools로 꺾임 횟수 최소화 최적화
                     Neo4j에 AS_DESIGNED 배관으로 저장
Node 4 (Reflect)   → LLM이 UHP 표준 위반 여부 자가 검증
                     위반 발견 시 Node 2로 재계획 (최대 3회)
Node 5 (HumanLoop) → 엔지니어 검토용 최종 설계 포맷팅
```

---

### Feature B: As-Built vs As-Designed 정합성 검증

**요청:**
```bash
curl -X POST http://localhost:8000/api/v1/verify/consistency \
  -H "Content-Type: application/json" \
  -d '{
    "designed_points": [
      [0.0, 0.0, 2.5],
      [5.0, 0.0, 2.5],
      [5.0, 1.5, 2.5],
      [14.0, 0.0, 0.0]
    ],
    "built_points": [
      [0.02, 0.01, 2.52],
      [5.03, -0.01, 2.49],
      [5.01, 1.52, 2.51],
      [14.04, 0.01, 0.02]
    ],
    "tolerance_m": 0.05,
    "pipe_id": "PIPE-006"
  }'
```

**예상 응답:**
```json
{
  "pipe_id": "PIPE-006",
  "status": "PASS",
  "is_within_tolerance": true,
  "rmse_cm": 2.3,
  "tolerance_cm": 5.0,
  "message": "정합성 검증 통과. RMSE=2.3cm (허용: 5cm)"
}
```

---

### GraphRAG 자연어 질의

```bash
curl -X POST http://localhost:8000/api/v1/graph/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "N2 가스 라인을 CHAMBER-A 장비에 연결하기 위한 UHP 규정과 현재 여유 포트를 찾아줘"
  }'
```

**GraphRAG 처리:**
1. Vector Search → "UHP N2 배관 연결 표준" 문서 검색
2. GraphCypher Search → Neo4j에서 CHAMBER-A 주변 배관 위상 조회
3. LLM → 두 컨텍스트를 합쳐 환각 없는 답변 생성

---

### 배관망 현황 조회

```bash
curl http://localhost:8000/api/v1/graph/equipment
```

---

## Step 5. 구현 핵심 기술 설명

### 1. LangGraph State 관리

`AgentState` (TypedDict)는 모든 노드가 공유하는 전역 메모리입니다.
각 노드는 변경할 필드만 담은 딕셔너리를 반환하면 LangGraph가 자동으로 병합합니다.

### 2. A* 알고리즘 (pathfinding.py)

3D 공간을 0.5m 격자로 분할하여 탐색합니다.
휴리스틱: 유클리드 거리 (허용 가능한 추정 → 최적해 보장)
꺾임 패널티: 방향 변화마다 0.8m 추가 비용 (꺾임 최소화 유도)

### 3. GraphRAG 하이브리드 검색 (graphrag.py)

```
사용자 질의
  ├─ Vector Search → ChromaDB → 배관 스펙 문서
  └─ Cypher Search → Neo4j → 배관망 위상 정보
          ↓
      Claude LLM → 통합 답변 (환각 최소화)
```

### 4. Reflection 패턴 (nodes.py Node 4)

Node 3 결과를 LLM이 다시 검토합니다.
UHP 표준 위반 발견 시 → Node 2로 회귀 (최대 3회)
이 패턴으로 '단순 오차'와 '치명적 위반'을 자동으로 1차 분류합니다.

### 5. ICP 알고리즘 (consistency.py)

Open3D를 사용하여 As-Built Point Cloud를 As-Designed에 정렬합니다.
최종 RMSE가 5cm를 초과하면 경고 알람을 반환합니다.
Open3D 미설치 시 NumPy 기반 최근접 거리 계산으로 자동 대체됩니다.

---

## 트러블슈팅

### Neo4j 연결 오류
```
ConnectionError: Unable to connect to bolt://localhost:7687
```
→ Docker가 실행 중인지 확인: `docker ps | grep neo4j`

### LLM API 오류
```
AuthenticationError: 401
```
→ `.env`의 API 키 확인

### OR-Tools 임포트 오류
→ optimizer.py의 그리디 폴백 로직이 자동 실행됩니다. 정상입니다.

### open3d 임포트 오류
→ consistency.py의 NumPy 폴백 로직이 자동 실행됩니다. 정상입니다.

---

## 회사 기술 스택과의 연결

| DDWorks-Mini 구현 | 실제 DDWorks 기술 |
|---|---|
| LangGraph 5-노드 파이프라인 | Smart HookUp AI Agent |
| NetworkX A* | 3D 공간 탐색 엔진 |
| OR-Tools CP-SAT | 배관 최적화 MILP |
| Open3D ICP | 특허 KR102037332B1 |
| Neo4j + GraphRAG | 다차원공간정보엔진 |
| ChromaDB Vector Search | 배관 스펙 시방서 검색 |
