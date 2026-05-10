"""
Neo4j 컨텍스트 매니저 기반 DB 핸들러

[설계 원칙]
컨텍스트 매니저(with 문)를 사용하는 이유:
- DB 연결은 '자원(Resource)'이므로 반드시 사용 후 반납해야 합니다.
- try-finally 패턴을 캡슐화하여 예외 발생 시에도 연결이 자동으로 닫힙니다.
- 이를 통해 '연결 누수(Connection Leak)'로 인한 DB 과부하를 방지합니다.
"""

import logging
from contextlib import contextmanager

from neo4j import GraphDatabase, Session, Driver

logger = logging.getLogger(__name__)


class Neo4jHandler:
    """
    Neo4j 드라이버를 관리하는 핸들러 클래스.
    싱글톤 패턴으로 사용하여 앱 전체에서 드라이버를 재사용합니다.
    """

    def __init__(self, uri: str, user: str, password: str):
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: Driver | None = None

    def connect(self) -> "Neo4jHandler":
        """드라이버를 생성하고 연결을 초기화합니다."""
        self._driver = GraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        # 연결이 실제로 성공하는지 검증
        self._driver.verify_connectivity()
        logger.info(f"Neo4j 연결 성공: {self._uri}")
        return self

    def close(self) -> None:
        """드라이버를 안전하게 종료합니다. 앱 종료 시 호출하세요."""
        if self._driver:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j 연결 종료")

    @contextmanager
    def session(self):
        """
        세션을 컨텍스트 매니저로 제공합니다.

        사용 예시:
            with neo4j_handler.session() as session:
                result = session.run("MATCH (n) RETURN n LIMIT 5")
        """
        if not self._driver:
            self.connect()

        session: Session = self._driver.session()
        try:
            yield session
        except Exception as e:
            logger.error(f"Neo4j 세션 오류: {e}")
            raise
        finally:
            # 예외 발생 여부와 관계없이 세션을 항상 닫습니다
            session.close()

    def run_query(self, query: str, parameters: dict | None = None) -> list[dict]:
        """읽기 전용 Cypher 쿼리를 실행하고 결과를 딕셔너리 리스트로 반환합니다."""
        with self.session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def run_write(self, query: str, parameters: dict | None = None) -> list[dict]:
        """
        쓰기 트랜잭션으로 Cypher 쿼리를 실행합니다.

        write_transaction을 사용하는 이유:
        - Neo4j의 인과적 일관성(Causal Consistency)을 보장합니다.
        - 실패 시 자동 재시도 로직이 내장되어 있습니다.
        """

        def _run(tx):
            result = tx.run(query, parameters or {})
            return [record.data() for record in result]

        with self.session() as session:
            return session.execute_write(_run)


def create_handler() -> Neo4jHandler:
    """설정값으로 Neo4jHandler 인스턴스를 생성합니다."""
    # 순환 임포트 방지를 위해 함수 내에서 import
    from core.config import settings

    return Neo4jHandler(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )
