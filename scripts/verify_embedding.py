"""한국어 임베딩 모델 검증 스크립트.

Plan Ref: farmos_review_analysis.plan.md §3.1 (1-3)
SC-04: 한국어 의미 검색 Top-5 precision >= 70%

nomic-embed-text의 한국어 리뷰 유사도 검색 정확도를 테스트합니다.
검증 실패 시 llama3.1:8b 임베딩으로 전환을 권장합니다.

실행:
  cd FarmOS
  python scripts/verify_embedding.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# 테스트 케이스: (검색 쿼리, 관련 키워드 — Top-5에 이 키워드가 포함된 리뷰가 있어야 함)
TEST_QUERIES = [
    {
        "query": "포장 관련 불만",
        "relevant_keywords": ["포장", "깨졌", "으깨", "상했", "박스", "파손", "엉망"],
        "description": "포장 관련 부정 리뷰 검색",
    },
    {
        "query": "배송이 느림",
        "relevant_keywords": ["배송", "느렸", "늦었", "걸렸", "도착"],
        "description": "배송 속도 관련 리뷰 검색",
    },
    {
        "query": "맛있는 과일",
        "relevant_keywords": ["맛있", "달", "당도", "신선", "좋아"],
        "description": "긍정적 맛 관련 리뷰 검색",
    },
    {
        "query": "가격이 비싸다",
        "relevant_keywords": ["가격", "비싸", "비싼", "가성비"],
        "description": "가격 관련 리뷰 검색",
    },
    {
        "query": "선물용으로 좋은 상품",
        "relevant_keywords": ["선물", "고급", "포장", "깔끔"],
        "description": "선물용 관련 리뷰 검색",
    },
]


def evaluate_search_results(results: list[dict], relevant_keywords: list[str], top_k: int = 5) -> dict:
    """검색 결과의 관련성을 평가합니다.

    Top-K 결과 중 관련 키워드가 포함된 리뷰의 비율을 계산합니다.

    Returns:
        {"precision": float, "relevant_count": int, "total": int, "details": list}
    """
    top_results = results[:top_k]
    relevant_count = 0
    details = []

    for r in top_results:
        text = r.get("text", "")
        is_relevant = any(kw in text for kw in relevant_keywords)
        if is_relevant:
            relevant_count += 1
        details.append({
            "id": r.get("id", ""),
            "text": text[:80],
            "similarity": r.get("similarity", 0),
            "relevant": is_relevant,
        })

    precision = relevant_count / len(top_results) if top_results else 0.0

    return {
        "precision": round(precision * 100, 1),
        "relevant_count": relevant_count,
        "total": len(top_results),
        "details": details,
    }


def run_verification():
    """임베딩 모델의 한국어 검색 성능을 검증합니다."""
    from app.core.review_rag import ReviewRAG

    rag = ReviewRAG()
    count = rag.get_count()

    print("=" * 60)
    print("한국어 임베딩 모델 검증")
    print("=" * 60)
    print(f"ChromaDB 리뷰 수: {count}건")
    print(f"임베딩 모델: nomic-embed-text (via Ollama)")
    print(f"목표: Top-5 precision >= 70%")
    print()

    if count == 0:
        print("ChromaDB에 리뷰가 없습니다. 먼저 임베딩을 실행하세요:")
        print("  POST /api/v1/reviews/embed")
        return

    total_precision = 0.0
    all_passed = True

    for i, tc in enumerate(TEST_QUERIES, 1):
        print(f"--- 테스트 {i}: {tc['description']} ---")
        print(f"  쿼리: \"{tc['query']}\"")

        results = rag.search(query=tc["query"], top_k=5)
        evaluation = evaluate_search_results(results, tc["relevant_keywords"])

        total_precision += evaluation["precision"]
        passed = evaluation["precision"] >= 70.0

        if not passed:
            all_passed = False

        print(f"  Precision: {evaluation['precision']}% ({evaluation['relevant_count']}/{evaluation['total']})")
        print(f"  통과: {'YES' if passed else 'NO'}")

        for d in evaluation["details"]:
            marker = "O" if d["relevant"] else "X"
            print(f"    [{marker}] sim={d['similarity']:.3f} \"{d['text']}\"")
        print()

    avg_precision = total_precision / len(TEST_QUERIES) if TEST_QUERIES else 0
    print("=" * 60)
    print(f"평균 Precision: {avg_precision:.1f}%")
    print(f"전체 통과: {'YES' if all_passed else 'NO'}")

    if not all_passed:
        print()
        print("권장 조치:")
        print("  1. review_rag.py의 EMBED_MODEL을 'llama3.1:8b'로 변경")
        print("  2. ChromaDB 컬렉션 삭제 후 재임베딩")
        print("  3. 이 스크립트 재실행하여 검증")


if __name__ == "__main__":
    run_verification()
