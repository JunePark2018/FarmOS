"""공익직불사업 (정부 지원금) 매칭 서비스.

Phase 1 (현재): 결정적 엔드포인트 (/subsidy/match, /subsidy/ask)
Phase 2 (예정): LangChain deep agent 기반 대화형 인터페이스

핵심 원칙:
    - 모든 기능은 독립적 tool 함수로 구현 (tools.py)
    - REST 엔드포인트는 tool 함수의 얇은 래퍼
    - Phase 2 전환 시 동일 tool을 deep agent에 주입만 하면 됨

구성:
    models/subsidy.py      SQLAlchemy 모델 (규칙 기반 필터 대상)
    schemas/subsidy.py     Pydantic 타입 (tool/API 공통)
    services/subsidy/
      seed_data.py         3가지 지원금 프로그램 시드
      pdf_ingest.py        시행지침 PDF → Markdown (Upstage Parse)
      chunker.py           조 단위 분할 + 장/절 메타데이터 + contextual
      gov_rag.py           Solar embedding + 리랭커 + 조항 부스트
      matcher.py           프로그램별 자격 규칙
      tools.py             5개 tool 함수 (deep agent 호환)
      prompts.py           시스템 프롬프트 (Phase 1/2 공통)
"""
