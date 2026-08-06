"""11번가 collector 단위 테스트 (네트워크 없이 파싱/변환 로직만 검증)."""

from datetime import datetime

from bs4 import BeautifulSoup

from review_crawler.collectors.elevenst.collector import ElevenstCollector, _to_int

# 실제 응답에서 축약한 리뷰 한 건 조각
REVIEW_LI = """
<li class="review_list_element" data-productno="123" data-contmapno="999888">
  <span class="c_product_reviewer">테스터01</span>
  <div class="c_product_review_cont">
    <div class="option">선택 옵션 색상:블루,사이즈:L</div>
    <span>평점 별 5점 중 4</span>
  </div>
  <div class="cont_review_hide">생각보다 튼튼하고 좋아요</div>
  <div class="c_product_review_thumbnail2">
    <button style="background-image:url('https://cdn.011st.com/a.jpg');"></button>
    <button style="background-image:url('https://cdn.011st.com/b.jpg');"></button>
  </div>
  <span class="date">2026.07.15</span>
  <button class="review-kkuk">꾹 7</button>
</li>
"""

# JSON-LD 가 포함된 최소 상세 페이지
DETAIL_HTML = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"테스트 텀블러","image":"https://x/t.jpg",
 "brand":{"name":"브랜드A","@type":"Brand"},"productID":"123",
 "category":"주방>물병","offers":{"price":9900,"@type":"Offer"}}
</script>
</head><body></body></html>
"""

SEARCH_ITEM = {
    "id": "555",
    "title": "샘플 상품",
    "finalPrc": 12000,
    "imageUrl": "https://x/img.jpg",
    "linkUrl": "https://action.adoffice.11st.co.kr/track?to=555",
    "brandEngNm": "브랜드B",
    "sellerNickName": "판매자B",
    "reviewCountText": "1,234",
    "satisfactionScore": "4.5",
}


def _collector() -> ElevenstCollector:
    return ElevenstCollector()


def test_to_int_handles_comma_and_empty():
    assert _to_int("1,234") == 1234
    assert _to_int("리뷰 없음") is None
    assert _to_int(None) is None


def test_parse_search_item_uses_canonical_url():
    product = _collector()._parse_search_item(SEARCH_ITEM)
    assert product.product_id == "555"
    assert product.name == "샘플 상품"
    assert product.price == 12000
    assert product.brand == "브랜드B"
    assert product.seller == "판매자B"
    assert product.review_count == 1234
    assert product.rating == 4.5
    # 광고 추적 linkUrl 대신 표준 상품 URL 로 정규화되어야 한다.
    assert product.url == "https://www.11st.co.kr/products/555"


def test_parse_search_item_skips_without_id_or_name():
    assert _collector()._parse_search_item({"title": "이름만"}) is None
    assert _collector()._parse_search_item({"id": "1"}) is None


def test_parse_review_extracts_all_fields():
    element = BeautifulSoup(REVIEW_LI, "lxml").select_one("li.review_list_element")
    review = _collector()._parse_review("123", element)
    assert review.review_id == "999888"
    assert review.author == "테스터01"
    assert review.content == "생각보다 튼튼하고 좋아요"
    assert review.rating == 4.0
    assert review.written_at == datetime(2026, 7, 15)
    assert review.option == "색상:블루,사이즈:L"
    assert review.images == ["https://cdn.011st.com/a.jpg", "https://cdn.011st.com/b.jpg"]
    assert review.helpful_count == 7


def test_extract_ld_json():
    data = _collector()._extract_ld_json(DETAIL_HTML)
    assert data["name"] == "테스트 텀블러"
    assert data["offers"]["price"] == 9900
    assert data["brand"]["name"] == "브랜드A"


async def test_search_empty_keyword_returns_empty():
    # 빈 키워드는 네트워크 호출 없이 즉시 빈 목록.
    assert await _collector().search_products("", limit=10) == []


async def test_reviews_limit_zero_returns_empty():
    assert await _collector().get_reviews("123", limit=0) == []
