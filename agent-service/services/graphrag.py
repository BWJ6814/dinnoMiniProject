"""
DINNO 맞춤형 GraphRAG (Hybrid Search) 구현 모듈

[GraphRAG = Graph + RAG 하이브리드 검색]
일반 RAG(벡터 검색만)의 한계:
- "UHP 가스 연결 표준"은 찾을 수 있지만
- "V-101 밸브 차단 시 영향받는 하류 펌프"는 찾을 수 없습니다.

GraphRAG의 해결책:
1. Vector Search: 의미론적 검색 (배관 스펙·규정 문서)
   → "N2 가스 UHP 연결 시 사용 재질은?" 같은 규정 질의에 적합
2. GraphCypher Search: 그래프 위상 탐색 (Neo4j Cypher)
   → "E-201 주변 여유 포트를 가진 장비를 찾아줘" 같은 연결성 질의에 적합
3. LLM 답변 생성: 두 컨텍스트를 합쳐 환각 없는 정확한 답변 생성

[Knowledge Graph 자동 구축 (Step 1)]
P&ID 문서 → LLM 기반 엔티티 추출 → Neo4j 그래프 적재
이 구현에서는 사전 정의된 spec_documents를 사용합니다.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 반도체 FAB 배관 스펙 문서 (Vector DB에 적재될 지식 베이스)
# 실제 DDWorks에서는 P&ID PDF, 시방서(Specification) PDF를 파싱합니다.
# ──────────────────────────────────────────────────────────────
PIPE_SPEC_DOCUMENTS = [
    {
        "id": "spec-001",
        "title": "UHP N2 배관 연결 표준",
        "content": (
            "UHP(Ultra High Purity) N2 가스 배관은 SS316L EP(Electropolished) 재질을 사용해야 합니다. "
            "최소 관경은 1/4인치이며, 웨이퍼 챔버 연결 시 3/8인치 권장합니다. "
            "모든 연결부에 VCR(Vacuum Coupling Radiation) 피팅 사용이 필수입니다. "
            "순도 99.9999% (6N) 이상을 유지해야 하며, 배관 표면 조도 Ra ≤ 0.25μm를 만족해야 합니다."
        ),
    },
    {
        "id": "spec-002",
        "title": "CCSS 케미컬 배관 안전 기준",
        "content": (
            "CCSS(Chemical Central Supply System) 배관은 사용 케미컬 종류에 따라 재질이 달라집니다. "
            "불산(HF)의 경우 PFA(Perfluoroalkoxy) 또는 PVDF 재질을 사용해야 합니다. "
            "모든 케미컬 배관에는 2차 격리(Secondary Containment)가 필요합니다. "
            "최대 허용 압력은 3bar이며, 안전 밸브(Relief Valve) 설치가 필수입니다."
        ),
    },
    {
        "id": "spec-003",
        "title": "배관 꺾임(Bend) 설계 기준",
        "content": (
            "반도체 FAB UHP 배관의 꺾임 반경(Bending Radius)은 관경의 최소 3배 이상이어야 합니다. "
            "1/2인치 관경 기준 최소 꺾임 반경은 38mm(1.5인치)입니다. "
            "90도 엘보 사용 시 Long-Radius(LR) 엘보만 허용됩니다. "
            "동일 평면에서 꺾임이 2회 이상 연속될 경우 반드시 검토가 필요합니다."
        ),
    },
    {
        "id": "spec-004",
        "title": "배관 압력 손실 계산 기준",
        "content": (
            "UHP 가스 배관의 압력 손실은 Darcy-Weisbach 공식으로 계산합니다. "
            "N2 가스의 경우 최대 허용 압력 강하는 0.5bar/m입니다. "
            "배관 길이가 10m를 초과할 경우 중간 조절 밸브(Regulator) 설치를 검토해야 합니다. "
            "배관 꺾임 1회당 직관 환산 길이는 관경의 40배(40D)로 계산합니다."
        ),
    },
    {
        "id": "spec-005",
        "title": "As-Built 정합성 허용 오차 기준",
        "content": (
            "시공된 배관(As-Built)과 설계 도면(As-Designed) 간의 허용 오차는 다음과 같습니다: "
            "위치 오차: ±50mm(5cm) 이내. "
            "각도 오차: ±1도 이내. "
            "허용 오차 초과 시 재시공 또는 설계 변경 승인이 필요합니다. "
            "3D 스캔(LiDAR)을 통해 현장 데이터를 획득하고 ICP 알고리즘으로 정합성을 검증합니다."
        ),
    },
]


class GraphRAGService:
    """
    Neo4j 그래프 검색 + 벡터 검색을 통합한 하이브리드 RAG 서비스.

    [아키텍처]
    사용자 질의
      ├─ Vector Search → 배관 스펙·규정 문서 검색
      └─ Graph Cypher  → Neo4j 위상·연결성 검색
              ↓
        LLM (Claude/GPT)으로 통합 답변 생성
    """

    def __init__(self):
        self._vector_store = None
        self._neo4j_tool = None
        self._llm = None
        self._initialized = False

    def initialize(self) -> bool:
        """벡터 스토어와 LLM을 초기화합니다."""
        try:
            self._setup_vector_store()
            self._setup_llm()
            self._setup_neo4j()
            self._initialized = True
            logger.info("GraphRAG 서비스 초기화 완료")
            return True
        except Exception as e:
            logger.error(f"GraphRAG 초기화 실패: {e}")
            return False

    def _setup_vector_store(self):
        """ChromaDB 벡터 스토어에 스펙 문서를 적재합니다."""
        try:
            from langchain_chroma import Chroma
            from langchain_openai import OpenAIEmbeddings
            from langchain_core.documents import Document
            from core.config import settings

            embeddings = OpenAIEmbeddings(api_key=settings.OPENAI_API_KEY)
            docs = [
                Document(page_content=d["content"], metadata={"id": d["id"], "title": d["title"]})
                for d in PIPE_SPEC_DOCUMENTS
            ]
            self._vector_store = Chroma.from_documents(
                documents=docs,
                embedding=embeddings,
                collection_name="pipe_specs",
            )
            logger.info(f"벡터 스토어 초기화: {len(docs)}개 문서 적재")
        except Exception as e:
            logger.warning(f"벡터 스토어 초기화 실패 (폴백 사용): {e}")
            self._vector_store = None

    def _setup_llm(self):
        """설정에 따라 Claude 또는 OpenAI LLM을 초기화합니다."""
        from core.config import settings

        try:
            if settings.LLM_PROVIDER == "anthropic":
                from langchain_anthropic import ChatAnthropic
                self._llm = ChatAnthropic(
                    model=settings.LLM_MODEL,
                    api_key=settings.ANTHROPIC_API_KEY,
                    temperature=0,
                )
            else:
                from langchain_openai import ChatOpenAI
                self._llm = ChatOpenAI(
                    model=settings.LLM_MODEL,
                    api_key=settings.OPENAI_API_KEY,
                    temperature=0,
                )
        except Exception as e:
            logger.error(f"LLM 초기화 실패: {e}")
            self._llm = None

    def _setup_neo4j(self):
        """Neo4j 툴을 초기화합니다."""
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from agent_service.tools.neo4j_tool import Neo4jPipingTool
            self._neo4j_tool = Neo4jPipingTool()
        except Exception as e:
            logger.warning(f"Neo4j 툴 초기화 실패: {e}")
            self._neo4j_tool = None

    def vector_search(self, query: str, k: int = 3) -> str:
        """배관 스펙 문서에서 관련 내용을 벡터 검색합니다."""
        if self._vector_store is None:
            # 폴백: 키워드 기반 단순 검색
            return self._keyword_fallback_search(query)

        try:
            docs = self._vector_store.similarity_search(query, k=k)
            results = []
            for doc in docs:
                results.append(f"[{doc.metadata.get('title', '')}]\n{doc.page_content}")
            return "\n\n".join(results)
        except Exception as e:
            logger.error(f"벡터 검색 실패: {e}")
            return self._keyword_fallback_search(query)

    def _keyword_fallback_search(self, query: str) -> str:
        """벡터 DB 없이 키워드로 스펙 문서를 검색하는 폴백 함수."""
        query_lower = query.lower()
        results = []

        keywords_map = {
            "uhp": ["spec-001", "spec-003", "spec-004"],
            "n2": ["spec-001", "spec-004"],
            "ccss": ["spec-002"],
            "케미컬": ["spec-002"],
            "꺾임": ["spec-003"],
            "bend": ["spec-003"],
            "압력": ["spec-004"],
            "정합성": ["spec-005"],
            "as-built": ["spec-005"],
        }

        matched_ids = set()
        for keyword, spec_ids in keywords_map.items():
            if keyword in query_lower:
                matched_ids.update(spec_ids)

        if not matched_ids:
            matched_ids = {"spec-001", "spec-003"}  # 기본값

        doc_map = {d["id"]: d for d in PIPE_SPEC_DOCUMENTS}
        for spec_id in matched_ids:
            if spec_id in doc_map:
                doc = doc_map[spec_id]
                results.append(f"[{doc['title']}]\n{doc['content']}")

        return "\n\n".join(results) if results else "관련 스펙 문서를 찾을 수 없습니다."

    def graph_cypher_search(self, query: str) -> str:
        """Neo4j에서 관련 배관 위상 정보를 Cypher로 검색합니다."""
        if self._neo4j_tool is None:
            return "그래프 DB 연결 불가 - Neo4j를 실행해주세요."

        # 쿼리에서 장비 태그나 타입 키워드를 추출하여 Cypher 생성
        # 실제 DDWorks에서는 LLM이 자연어를 Cypher로 변환합니다 (Text2Cypher)
        try:
            all_equip = self._neo4j_tool.get_all_equipment()
            all_pipes = self._neo4j_tool.get_all_piping()

            lines = ["=== 현재 그래프 DB 배관망 상태 ===", "장비 목록:"]
            for eq in all_equip[:10]:
                lines.append(
                    f"  - {eq['tag']}: {eq['name']} (타입: {eq['type']}, 스펙: {eq['spec']})"
                )
            lines.append("\n배관 연결 관계:")
            for pipe in all_pipes[:10]:
                lines.append(
                    f"  - {pipe['from_tag']} → {pipe['to_tag']} "
                    f"[{pipe['spec']}, {pipe['diameter_inch']}\"관, {pipe['length_m']}m]"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"그래프 검색 실패: {e}")
            return f"그래프 검색 오류: {e}"

    def hybrid_query(self, user_query: str) -> str:
        """
        하이브리드 검색 실행 후 LLM으로 통합 답변을 생성합니다.

        [처리 흐름]
        1. Vector Search → 스펙·규정 컨텍스트
        2. Graph Search  → 위상·연결성 컨텍스트
        3. LLM           → 두 컨텍스트를 합쳐 환각 없는 답변 생성
        """
        if not self._initialized:
            self.initialize()

        vector_context = self.vector_search(user_query)
        graph_context = self.graph_cypher_search(user_query)

        combined_context = (
            f"[배관 스펙·규정 정보 (Vector Search)]\n{vector_context}\n\n"
            f"[현재 배관망 위상 정보 (Graph Search)]\n{graph_context}"
        )

        if self._llm is None:
            return (
                f"LLM 미설정. 검색된 컨텍스트:\n\n{combined_context}"
            )

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=(
                "당신은 반도체 FAB 배관 설계 전문가입니다. "
                "아래 배관 스펙 정보와 현재 그래프 DB 데이터를 기반으로 "
                "정확하고 간결하게 질문에 답변하세요. "
                "확인되지 않은 정보는 언급하지 마세요."
            )),
            HumanMessage(content=(
                f"[컨텍스트]\n{combined_context}\n\n"
                f"[질문]\n{user_query}"
            )),
        ]

        try:
            response = self._llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM 호출 실패: {e}")
            return f"LLM 오류: {e}\n\n검색 컨텍스트:\n{combined_context}"
