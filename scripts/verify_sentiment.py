"""감성분석 정확도 검증 스크립트.

Plan Ref: farmos_review_analysis.plan.md §3.1 (1-5)
SC-05: 감성분석 정확도 80%+ (Ollama llama3.1:8b)

50건 라벨링 데이터셋과 LLM 분석 결과를 비교하여 정확도를 계산합니다.

실행:
  cd FarmOS
  python scripts/verify_sentiment.py
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

# 50건 라벨링 데이터셋 (수동 라벨 = rating 기반 ground truth)
LABELED_REVIEWS = [
    # 긍정 (rating 4-5) — 22건
    {"id": "test-01", "text": "정말 맛있어요! 사과 품질이 최고입니다.", "rating": 5, "expected": "positive"},
    {"id": "test-02", "text": "신선하고 달아요! 포장도 깔끔해요.", "rating": 5, "expected": "positive"},
    {"id": "test-03", "text": "재구매 의사 100%. 아이들이 좋아해요.", "rating": 5, "expected": "positive"},
    {"id": "test-04", "text": "가격 대비 품질이 너무 좋아요. 추천합니다!", "rating": 4, "expected": "positive"},
    {"id": "test-05", "text": "배송도 빠르고 상태 완벽했어요.", "rating": 5, "expected": "positive"},
    {"id": "test-06", "text": "당도가 높아서 설탕 없이도 달아요.", "rating": 5, "expected": "positive"},
    {"id": "test-07", "text": "선물용으로 구매했는데 받는 분이 좋아하셨어요.", "rating": 4, "expected": "positive"},
    {"id": "test-08", "text": "산지 직송이라 신선도가 다릅니다.", "rating": 5, "expected": "positive"},
    {"id": "test-09", "text": "매번 여기서 주문하는데 항상 품질이 일정해요.", "rating": 5, "expected": "positive"},
    {"id": "test-10", "text": "유기농이라 안심하고 먹을 수 있어요.", "rating": 4, "expected": "positive"},
    {"id": "test-11", "text": "한우 등심 마블링이 정말 뛰어납니다.", "rating": 5, "expected": "positive"},
    {"id": "test-12", "text": "제주 감귤 당도 높고 신선해요!", "rating": 5, "expected": "positive"},
    {"id": "test-13", "text": "고구마가 촉촉하고 달콤해요. 최고!", "rating": 5, "expected": "positive"},
    {"id": "test-14", "text": "생연어 신선도 최상급입니다.", "rating": 5, "expected": "positive"},
    {"id": "test-15", "text": "명절 선물로 보냈는데 진짜 고급스러워요.", "rating": 4, "expected": "positive"},
    {"id": "test-16", "text": "통영 생굴 정말 싱싱해요!", "rating": 5, "expected": "positive"},
    {"id": "test-17", "text": "블루베리 항산화 풍부하고 맛도 좋아요.", "rating": 4, "expected": "positive"},
    {"id": "test-18", "text": "방울토마토 당도 높아서 간식으로 딱!", "rating": 5, "expected": "positive"},
    {"id": "test-19", "text": "깻잎 향이 진하고 신선해요. 만족!", "rating": 4, "expected": "positive"},
    {"id": "test-20", "text": "한우 갈비살 부드럽고 맛있어요.", "rating": 5, "expected": "positive"},
    {"id": "test-21", "text": "제주 흑돼지 삼겹살 최고!", "rating": 5, "expected": "positive"},
    {"id": "test-22", "text": "전복 크기 균일하고 싱싱해요.", "rating": 4, "expected": "positive"},

    # 중립 (rating 3) — 23건
    {"id": "test-23", "text": "보통이에요. 가격 대비 무난합니다.", "rating": 3, "expected": "neutral"},
    {"id": "test-24", "text": "기대했던 것보다 평범해요.", "rating": 3, "expected": "neutral"},
    {"id": "test-25", "text": "괜찮긴 한데 특별히 맛있다는 느낌은 없어요.", "rating": 3, "expected": "neutral"},
    {"id": "test-26", "text": "그냥 무난한 사과예요.", "rating": 3, "expected": "neutral"},
    {"id": "test-27", "text": "포장은 잘 되어 있는데 맛은 기대만큼은 아니에요.", "rating": 3, "expected": "neutral"},
    {"id": "test-28", "text": "배송은 빨랐는데 크기가 좀 작아요.", "rating": 3, "expected": "neutral"},
    {"id": "test-29", "text": "그럭저럭 먹을 만해요.", "rating": 3, "expected": "neutral"},
    {"id": "test-30", "text": "나쁘지 않아요. 근데 재구매는 고민 중이에요.", "rating": 3, "expected": "neutral"},
    {"id": "test-31", "text": "사진보다 좀 작아 보여요. 맛은 괜찮아요.", "rating": 3, "expected": "neutral"},
    {"id": "test-32", "text": "가성비는 그저 그래요.", "rating": 3, "expected": "neutral"},
    {"id": "test-33", "text": "다른 데서 사던 것과 크게 차이가 없어요.", "rating": 3, "expected": "neutral"},
    {"id": "test-34", "text": "무난하게 먹기 좋아요. 특별하진 않지만요.", "rating": 3, "expected": "neutral"},
    {"id": "test-35", "text": "신선하긴 한데 기대했던 당도는 아니에요.", "rating": 3, "expected": "neutral"},
    {"id": "test-36", "text": "급하게 필요해서 샀는데 보통 수준이에요.", "rating": 3, "expected": "neutral"},
    {"id": "test-37", "text": "어디서 사나 비슷비슷한 것 같아요.", "rating": 3, "expected": "neutral"},
    {"id": "test-38", "text": "보통이요. 특별한 건 없어요.", "rating": 3, "expected": "neutral"},
    {"id": "test-39", "text": "맛은 있는데 가격이 좀 비싼 감이 있어요.", "rating": 3, "expected": "neutral"},
    {"id": "test-40", "text": "선물로 보내기엔 좀 애매한 크기예요.", "rating": 3, "expected": "neutral"},
    {"id": "test-41", "text": "호불호가 갈릴 수 있을 것 같아요.", "rating": 3, "expected": "neutral"},
    {"id": "test-42", "text": "첫 구매라 잘 모르겠는데 보통인 것 같아요.", "rating": 3, "expected": "neutral"},
    {"id": "test-43", "text": "포장은 깔끔한데 한두 개 상태가 좀 아쉬워요.", "rating": 3, "expected": "neutral"},
    {"id": "test-44", "text": "괜찮아요. 크게 감동은 없지만 불만도 없어요.", "rating": 3, "expected": "neutral"},
    {"id": "test-45", "text": "두 번째 구매인데 처음이랑 맛이 좀 다른 느낌?", "rating": 3, "expected": "neutral"},

    # 부정 (rating 1-2) — 5건
    {"id": "test-46", "text": "포장이 엉망이에요. 배송 중 상했어요.", "rating": 1, "expected": "negative"},
    {"id": "test-47", "text": "사진이랑 너무 다르네요. 크기가 너무 작아요.", "rating": 2, "expected": "negative"},
    {"id": "test-48", "text": "멍 든 사과가 절반이에요. 선별을 제대로 안 한 것 같아요.", "rating": 1, "expected": "negative"},
    {"id": "test-49", "text": "맛도 없고 신선하지도 않고... 실망이에요.", "rating": 2, "expected": "negative"},
    {"id": "test-50", "text": "두 번 다시 안 삽니다. 품질 관리 좀 해주세요.", "rating": 1, "expected": "negative"},
]


def calculate_accuracy(predictions: list[dict], labels: list[dict]) -> dict:
    """예측 결과와 라벨을 비교하여 정확도를 계산합니다.

    Args:
        predictions: [{"id": str, "sentiment": str}]
        labels: LABELED_REVIEWS 형식

    Returns:
        {"accuracy": float, "total": int, "correct": int, "confusion_matrix": dict, "details": list}
    """
    label_map = {r["id"]: r["expected"] for r in labels}
    correct = 0
    total = 0
    details = []

    # confusion matrix
    matrix = {
        "positive": {"positive": 0, "neutral": 0, "negative": 0},
        "neutral": {"positive": 0, "neutral": 0, "negative": 0},
        "negative": {"positive": 0, "neutral": 0, "negative": 0},
    }

    for pred in predictions:
        review_id = pred.get("id", "")
        predicted = pred.get("sentiment", "").lower()
        expected = label_map.get(review_id)

        if expected is None:
            continue

        total += 1
        is_correct = predicted == expected
        if is_correct:
            correct += 1

        if expected in matrix and predicted in matrix[expected]:
            matrix[expected][predicted] += 1

        details.append({
            "id": review_id,
            "expected": expected,
            "predicted": predicted,
            "correct": is_correct,
        })

    accuracy = correct / total if total > 0 else 0.0

    return {
        "accuracy": round(accuracy * 100, 1),
        "total": total,
        "correct": correct,
        "target": 80.0,
        "passed": accuracy >= 0.80,
        "confusion_matrix": matrix,
        "details": details,
    }


async def run_verification():
    """Ollama LLM으로 감성분석을 실행하고 정확도를 검증합니다."""
    from app.core.review_analyzer import ReviewAnalyzer

    analyzer = ReviewAnalyzer()

    reviews_for_analysis = [
        {"id": r["id"], "text": r["text"], "rating": r["rating"], "platform": "", "date": ""}
        for r in LABELED_REVIEWS
    ]

    print("감성분석 실행 중... (Ollama llama3.1:8b)")
    print(f"대상: {len(reviews_for_analysis)}건\n")

    try:
        result = await analyzer.analyze_batch(reviews_for_analysis, batch_size=25)
    except Exception as e:
        print(f"분석 실패: {e}")
        print("Ollama가 실행 중인지 확인하세요: ollama serve")
        return

    sentiments = result.get("sentiments", [])
    if not sentiments:
        print("감성분석 결과가 비어있습니다.")
        return

    predictions = [{"id": s["id"], "sentiment": s["sentiment"]} for s in sentiments]
    report = calculate_accuracy(predictions, LABELED_REVIEWS)

    print("=" * 60)
    print("감성분석 정확도 검증 결과")
    print("=" * 60)
    print(f"정확도: {report['accuracy']}% ({report['correct']}/{report['total']}건)")
    print(f"목표: {report['target']}%")
    print(f"통과: {'YES' if report['passed'] else 'NO'}")
    print()

    print("Confusion Matrix:")
    print(f"{'':>12} | predicted_pos | predicted_neu | predicted_neg")
    print("-" * 60)
    for actual in ["positive", "neutral", "negative"]:
        row = report["confusion_matrix"][actual]
        print(f"actual_{actual[:3]:>4} | {row['positive']:>13} | {row['neutral']:>13} | {row['negative']:>13}")
    print()

    # 오답 목록
    wrong = [d for d in report["details"] if not d["correct"]]
    if wrong:
        print(f"오답 {len(wrong)}건:")
        for w in wrong[:10]:
            text = next((r["text"] for r in LABELED_REVIEWS if r["id"] == w["id"]), "")
            print(f"  {w['id']}: expected={w['expected']}, predicted={w['predicted']}")
            print(f"    \"{text[:50]}...\"")

    # 결과 JSON 저장
    output_path = os.path.join(os.path.dirname(__file__), "sentiment_verification_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_verification())
