"""OrderGraph 헬퍼·노드 테스트.

interrupt()를 사용하는 노드는 langgraph.types.interrupt를 패치하여
사용자 입력을 주입합니다. 이를 통해 LangGraph 런타임 없이
노드 로직을 단독으로 검증합니다.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

from ai.agent.order_graph.nodes import (
    _parse_item_selections,
    _parse_order_selection,
    _build_order_summaries,
    _is_flow_abort_intent,
    _is_confirm_intent,
    _is_hard_cancel_intent,
    _parse_reason,
    _parse_refund_method,
    list_orders,
    create_ticket,
    show_summary,
    check_stock,
)
from ai.agent.order_graph.state import OrderState
from ai.agent.supervisor.executor import _fast_route, _detect_order_action


# ── 팩토리 ────────────────────────────────────────────────────────────────────

def make_order_item(item_id=1, order_id=1, product_id=10, quantity=2):
    oi = MagicMock()
    oi.id = item_id
    oi.order_id = order_id
    oi.product_id = product_id
    oi.quantity = quantity
    return oi


def make_product(product_id=10, name="딸기", stock=50):
    p = MagicMock()
    p.id = product_id
    p.name = name
    p.stock = stock
    return p


def make_order(order_id=1, user_id=99, status="delivered"):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    o = MagicMock()
    o.id = order_id
    o.user_id = user_id
    o.status = status
    o.created_at = datetime(2026, 4, 10, tzinfo=ZoneInfo("Asia/Seoul"))
    return o


def make_config(db):
    return {"configurable": {"db": db, "thread_id": "test-thread"}}


def base_state(**overrides) -> OrderState:
    defaults: OrderState = {
        "action": "exchange",
        "user_id": 99,
        "session_id": 1,
        "user_message": "",
        "order_id": 1,
        "order_display": "주문 번호 #1 · 딸기 · 주문일 2026-04-10",
        "selected_items": [],
        "reason": None,
        "refund_method": None,
        "stock_note": "",
        "confirmed": None,
        "abort": False,
        "confirmation_attempts": 0,
        "ticket_id": None,
        "response": "",
        "is_pending": True,
    }
    defaults.update(overrides)
    return defaults


# ── _parse_item_selections ────────────────────────────────────────────────────

class TestParseItemSelections:
    def _make_db(self, products: list):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = products
        return db

    def test_all_keyword_selects_all_items(self):
        products = [make_product(10, "딸기", 50), make_product(11, "사과", 30)]
        items = [make_order_item(1, 1, 10, 2), make_order_item(2, 1, 11, 3)]
        db = self._make_db(products)

        result = _parse_item_selections("전체", items, db)

        assert len(result) == 2
        assert result[0]["name"] == "딸기"
        assert result[1]["name"] == "사과"
        assert result[0]["qty"] == 2
        assert result[1]["qty"] == 3

    def test_numbered_selection_with_quantity(self):
        products = [make_product(10, "딸기", 50), make_product(11, "사과", 30)]
        items = [make_order_item(1, 1, 10, 5), make_order_item(2, 1, 11, 3)]
        db = self._make_db(products)

        result = _parse_item_selections("1번 상품 2개", items, db)

        assert len(result) == 1
        assert result[0]["name"] == "딸기"
        assert result[0]["qty"] == 2

    def test_quantity_capped_at_item_quantity(self):
        """요청 수량이 주문 수량 초과 시 주문 수량으로 제한."""
        products = [make_product(10, "딸기", 50)]
        items = [make_order_item(1, 1, 10, 3)]
        db = self._make_db(products)

        result = _parse_item_selections("1번 상품 99개", items, db)

        assert result[0]["qty"] == 3

    def test_empty_string_returns_empty(self):
        products = [make_product(10, "딸기", 50)]
        items = [make_order_item(1, 1, 10, 2)]
        db = self._make_db(products)

        result = _parse_item_selections("전혀 관련 없는 말", items, db)

        assert result == []

    def test_unknown_product_uses_fallback_name(self):
        """product_id에 해당하는 상품이 없을 때 '상품 #N' 폴백."""
        db = self._make_db([])  # 빈 상품 목록
        items = [make_order_item(1, 1, 10, 2)]

        result = _parse_item_selections("전체", items, db)

        assert result[0]["name"] == "상품 #10"

    def test_single_bulk_query_not_n_plus_one(self):
        """상품 조회가 단 1회 IN 쿼리로 처리되는지 검증."""
        products = [make_product(10, "딸기", 50), make_product(11, "사과", 30)]
        items = [make_order_item(1, 1, 10, 2), make_order_item(2, 1, 11, 1)]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = products

        _parse_item_selections("전체", items, db)

        # db.query(Product)가 단 1번만 호출되어야 함
        assert db.query.call_count == 1


# ── _parse_order_selection ────────────────────────────────────────────────────

class TestParseOrderSelection:
    def test_select_by_index(self):
        orders = [make_order(1), make_order(2), make_order(3)]
        assert _parse_order_selection("2", orders) == 2

    def test_select_by_order_id_directly(self):
        orders = [make_order(100), make_order(200)]
        assert _parse_order_selection("200", orders) == 200

    def test_invalid_input_returns_none(self):
        orders = [make_order(1)]
        assert _parse_order_selection("abc", orders) is None

    def test_out_of_range_index_returns_none(self):
        orders = [make_order(1)]
        assert _parse_order_selection("5", orders) is None


# ── _build_order_summaries ────────────────────────────────────────────────────

class TestBuildOrderSummaries:
    def test_single_item_order(self):
        from app.models.order import OrderItem
        from app.models.product import Product

        order = make_order(1)
        db = MagicMock()

        # OrderItem 쿼리
        oi = make_order_item(item_id=1, order_id=1, product_id=10, quantity=2)
        db.query.return_value.filter.return_value.all.side_effect = [
            [oi],       # OrderItem IN 쿼리
            [make_product(10, "딸기", 50)],  # Product IN 쿼리
        ]

        summaries = _build_order_summaries(db, [order])

        assert summaries[1] == "딸기"

    def test_multi_item_order_shows_suffix(self):
        order = make_order(1)
        db = MagicMock()

        items = [
            make_order_item(1, 1, 10, 2),
            make_order_item(2, 1, 11, 1),
            make_order_item(3, 1, 12, 3),
        ]
        products = [
            make_product(10, "딸기", 50),
            make_product(11, "사과", 30),
            make_product(12, "배", 20),
        ]
        db.query.return_value.filter.return_value.all.side_effect = [items, products]

        summaries = _build_order_summaries(db, [order])

        assert summaries[1] == "딸기 외 2건"

    def test_empty_items_shows_fallback(self):
        order = make_order(1)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [[], []]

        summaries = _build_order_summaries(db, [order])

        assert summaries[1] == "주문 상품"

    def test_bulk_query_count_with_items(self):
        """N+1 없이 IN 쿼리 2회(OrderItem, Product)만 발생하는지 검증.

        items가 있을 때: OrderItem 조회 1회 + Product 조회 1회 = 총 2회.
        items가 없을 때: OrderItem 조회 1회만 (product_ids 공집합 → 스킵).
        """
        orders = [make_order(1), make_order(2)]
        items = [make_order_item(1, 1, 10, 2), make_order_item(2, 2, 11, 1)]
        products = [make_product(10, "딸기", 50), make_product(11, "사과", 30)]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = [items, products]

        _build_order_summaries(db, orders)

        # db.query 호출 횟수 = 2 (OrderItem, Product 각 1번)
        assert db.query.call_count == 2

    def test_bulk_query_skips_product_when_no_items(self):
        """items가 없을 때 Product 쿼리는 생략 — OrderItem 조회만 1회."""
        orders = [make_order(1), make_order(2)]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        _build_order_summaries(db, orders)

        # items가 없으면 product_ids가 공집합 → Product 쿼리 생략
        assert db.query.call_count == 1


# ── 의도 파싱 헬퍼 ────────────────────────────────────────────────────────────

class TestIntentHelpers:
    @pytest.mark.parametrize("text,action,expected", [
        ("그만", "exchange", True),
        ("취소할게요", "exchange", True),
        ("취소할게요", "cancel", False),   # cancel 플로우에서 "취소"는 중단 아님
        # "아니요"/"아니오"는 CANCEL_KEYWORDS에 포함되어 _is_flow_abort_intent=True.
        # show_summary에서는 abort 판단에 _is_hard_cancel_intent를 별도로 사용하므로
        # 최종 abort=False로 처리됨 — 그러나 다른 노드(list_orders 등)에서는 True.
        ("아니요", "exchange", True),
        ("계속할게요", "exchange", False),
    ])
    def test_flow_abort_intent(self, text, action, expected):
        from ai.agent.order_graph.nodes import _is_flow_abort_intent
        assert _is_flow_abort_intent(text, action) == expected

    @pytest.mark.parametrize("text,expected", [
        ("네", True),
        ("응", True),
        ("확인", True),
        ("맞아요", True),
        ("아니요", False),
        ("그만", False),
    ])
    def test_confirm_intent(self, text, expected):
        assert _is_confirm_intent(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("그만", True),
        ("취소할게요", True),
        ("아니요", False),
        ("아니오", False),
    ])
    def test_hard_cancel_intent(self, text, expected):
        assert _is_hard_cancel_intent(text) == expected

    @pytest.mark.parametrize("text,reason_map,expected", [
        ("1", {"1": "단순 변심"}, "단순 변심"),
        ("2", {"2": "상품 불량"}, "상품 불량"),
        ("그냥 마음이 바뀌었어요", {}, "그냥 마음이 바뀌었어요"),
        ("", {}, "기타"),
    ])
    def test_parse_reason(self, text, reason_map, expected):
        assert _parse_reason(text, reason_map) == expected

    @pytest.mark.parametrize("text,expected", [
        ("1", "원결제 수단 환불"),
        ("카드", "원결제 수단 환불"),
        ("2", "적립금으로 환불"),
        ("포인트", "적립금으로 환불"),
        ("모르겠어요", "원결제 수단 환불"),  # 기본값
    ])
    def test_parse_refund_method(self, text, expected):
        result = _parse_refund_method(text)
        assert result == expected


# ── _fast_route (Supervisor) ──────────────────────────────────────────────────

class TestFastRoute:
    @pytest.mark.parametrize("message,expected", [
        ("교환해주세요", "order"),
        ("취소 신청할게요", "order"),
        ("반품하고 싶어요", "order"),
        ("교환 접수해줘", "order"),
        # CS로 라우팅되어야 하는 케이스
        ("반품 정책이 뭐야?", "cs"),          # 정책 문의
        ("교환 방법 알려줘", "cs"),            # 정책 문의 단어 포함
        ("딸기 재고 있어요?", "cs"),           # 주문 키워드 없음
        ("배송 언제 와요?", "cs"),             # 주문 키워드 없음
        ("반품 규정이 어떻게 돼요", "cs"),     # 정책 문의
    ])
    def test_routing(self, message, expected):
        assert _fast_route(message) == expected

    def test_keyword_without_action_verb_routes_to_cs(self):
        """주문 키워드만 있고 동사 없으면 CS."""
        assert _fast_route("교환") == "cs"
        assert _fast_route("반품") == "cs"

    def test_distant_keyword_and_verb_routes_to_cs(self):
        """키워드와 동사 사이 거리가 30자 초과면 CS."""
        long_msg = "교환" + ("이라는 단어가 나왔지만 전혀 관련 없는 긴 문장이 이어집니다. ") + "원해"
        assert _fast_route(long_msg) == "cs"


# ── _detect_order_action ──────────────────────────────────────────────────────

class TestDetectOrderAction:
    def test_exchange_keywords_win(self):
        assert _detect_order_action("교환해줘") == "exchange"

    def test_cancel_keywords_win(self):
        assert _detect_order_action("취소할게요") == "cancel"

    def test_default_is_cancel(self):
        assert _detect_order_action("처리해줘") == "cancel"


# ── create_ticket 멱등성 ──────────────────────────────────────────────────────

class TestCreateTicketIdempotency:
    """기존 티켓이 있으면 새 티켓을 INSERT하지 않고 재사용하는지 검증."""

    @pytest.mark.asyncio
    async def test_returns_existing_ticket_when_found(self):
        from app.models.ticket import ShopTicket
        from app.models.order import Order

        existing_ticket = MagicMock()
        existing_ticket.id = 42

        order = make_order(order_id=1, user_id=99, status="delivered")

        db = MagicMock()

        def query_side_effect(model):
            mock = MagicMock()
            if model is Order:
                mock.filter.return_value.first.return_value = order
            elif model is ShopTicket:
                # 첫 번째 filter 체인 (상태 재검증용 아님) → 멱등성 체크
                mock.filter.return_value.first.return_value = existing_ticket
            return mock

        db.query.side_effect = query_side_effect

        state = base_state(
            action="exchange",
            user_id=99,
            order_id=1,
            selected_items=[{"item_id": 1, "product_id": 10, "name": "딸기", "qty": 1}],
            reason="상품 불량",
        )

        result = await create_ticket(state, make_config(db))

        assert result["ticket_id"] == 42
        db.add.assert_not_called()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_ownership_fails_returns_error(self):
        """주문 소유권 검증 실패 시 에러 메시지 반환."""
        from app.models.ticket import ShopTicket
        from app.models.order import Order

        db = MagicMock()

        def query_side_effect(model):
            mock = MagicMock()
            if model is Order:
                mock.filter.return_value.first.return_value = None  # 소유권 실패
            return mock

        db.query.side_effect = query_side_effect

        state = base_state(user_id=99, order_id=999)
        result = await create_ticket(state, make_config(db))

        assert "확인할 수 없습니다" in result["response"]
        assert result["is_pending"] is False


# ── show_summary 재확인 카운터 ────────────────────────────────────────────────

class TestShowSummaryConfirmationAttempts:
    @pytest.mark.asyncio
    async def test_exceeds_max_attempts_aborts(self):
        """confirmation_attempts가 3 초과 시 강제 중단."""
        state = base_state(
            action="cancel",
            order_display="주문 번호 #1",
            reason="단순 변심",
            refund_method="원결제 수단 환불",
            confirmation_attempts=3,  # 이미 3회 — 이번 호출이 4번째
        )

        result = await show_summary(state, make_config(MagicMock()))

        assert result["abort"] is True
        assert result["is_pending"] is False
        assert "중단" in result["response"]

    @pytest.mark.asyncio
    async def test_confirm_intent_sets_confirmed_true(self):
        """사용자가 확인하면 confirmed=True."""
        state = base_state(
            action="cancel",
            order_display="주문 번호 #1",
            reason="단순 변심",
            refund_method="원결제 수단 환불",
            confirmation_attempts=0,
        )

        with patch("ai.agent.order_graph.nodes.interrupt", return_value="네"):
            result = await show_summary(state, make_config(MagicMock()))

        assert result["confirmed"] is True
        assert result["confirmation_attempts"] == 1

    @pytest.mark.asyncio
    async def test_deny_intent_sets_confirmed_false(self):
        """단순 거절은 confirmed=False, abort는 False 유지."""
        state = base_state(
            action="cancel",
            order_display="주문 번호 #1",
            reason="단순 변심",
            refund_method="원결제 수단 환불",
            confirmation_attempts=1,
        )

        with patch("ai.agent.order_graph.nodes.interrupt", return_value="아니요"):
            result = await show_summary(state, make_config(MagicMock()))

        assert result["confirmed"] is False
        assert result["abort"] is False
        assert result["confirmation_attempts"] == 2

    @pytest.mark.asyncio
    async def test_hard_cancel_sets_abort(self):
        """명시적 중단("그만")은 abort=True."""
        state = base_state(
            action="cancel",
            order_display="주문 번호 #1",
            reason="단순 변심",
            refund_method="원결제 수단 환불",
            confirmation_attempts=0,
        )

        with patch("ai.agent.order_graph.nodes.interrupt", return_value="그만"):
            result = await show_summary(state, make_config(MagicMock()))

        assert result["abort"] is True


# ── check_stock N+1 검증 ──────────────────────────────────────────────────────

class TestCheckStock:
    @pytest.mark.asyncio
    async def test_single_bulk_query(self):
        """상품 재고 조회가 단 1회 IN 쿼리로 처리되는지 검증."""
        products = [make_product(10, "딸기", 100), make_product(11, "사과", 0)]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = products

        state = base_state(selected_items=[
            {"item_id": 1, "product_id": 10, "name": "딸기", "qty": 2},
            {"item_id": 2, "product_id": 11, "name": "사과", "qty": 1},
        ])

        result = await check_stock(state, make_config(db))

        assert db.query.call_count == 1
        assert "사과" in result["stock_note"]
        assert "딸기" not in result["stock_note"]

    @pytest.mark.asyncio
    async def test_sufficient_stock_produces_empty_note(self):
        """재고가 충분하면 stock_note가 빈 문자열."""
        products = [make_product(10, "딸기", 100)]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = products

        state = base_state(selected_items=[
            {"item_id": 1, "product_id": 10, "name": "딸기", "qty": 2},
        ])

        result = await check_stock(state, make_config(db))

        assert result["stock_note"] == ""

    @pytest.mark.asyncio
    async def test_zero_stock_note_message(self):
        """재고 0개 품목은 '현재 재고 없음' 메시지 포함."""
        products = [make_product(10, "딸기", 0)]
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = products

        state = base_state(selected_items=[
            {"item_id": 1, "product_id": 10, "name": "딸기", "qty": 2},
        ])

        result = await check_stock(state, make_config(db))

        assert "재고 없음" in result["stock_note"]
