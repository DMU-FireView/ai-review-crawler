# ai-review-crawler

커머스 플랫폼의 상품·리뷰를 수집해 표준 스키마(JSON)로 저장하는 모듈입니다.

로컬 수집·검증 단계이며, 완성된 `core/` + `collectors/` 는 나중에 본 서버(FastAPI)에 그대로 이식됩니다.

## 담당

| 담당자 | 플랫폼 | 폴더 |
|---|---|---|
| 김동환 | 에이블리, 오늘의집 | `collectors/ably`, `collectors/ohouse` |
| 김하연 | 마켓컬리, G마켓 | `collectors/kurly`, `collectors/gmarket` |
| 남정현 | 옥션, 무신사 | `collectors/auction`, `collectors/musinsa` |
| 정빈 | 11번가, 올리브영 | `collectors/elevenst`, `collectors/oliveyoung` |

## 시작하기

```bash
git clone https://github.com/DMU-FireView/ai-review-crawler.git
cd ai-review-crawler

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -e ".[dev]"
playwright install chromium     # 최초 1회, 몇 분 걸립니다
cp .env.example .env

crawler list                     # 등록된 collector 확인
```

## 명령어

```bash
crawler list                              # 등록된 collector 목록
crawler collect                           # 대화형으로 플랫폼 선택 후 상품 수집
crawler collect -k 텀블러 -n 30            # 키워드/개수 직접 지정
crawler reviews elevenst 123456 -n 100    # 특정 상품의 리뷰 수집
crawler serve                             # 결과 확인용 API 서버 (localhost:8000/docs)
```

수집 결과는 `data/{platform}/{products|reviews}_{타임스탬프}.json` 에 저장됩니다.

## collector 만들기

자기 폴더의 `collector.py` 를 채우면 됩니다. **등록 절차는 없습니다** — `collectors/` 아래 폴더를 자동으로 스캔하므로, 공용 파일을 건드릴 일이 없고 머지 충돌도 나지 않습니다.

지켜야 할 것은 세 가지뿐입니다.

1. `BaseCollector`(또는 `BrowserCollector`) 상속
2. `platform` 값 = **폴더명과 동일하게** (다르면 실행 시 에러로 알려줍니다)
3. 메서드 3개 시그니처 유지

이 외에는 자유입니다. 파일을 몇 개로 나누든, 파서를 분리하든, 상수를 어디에 두든 상관없습니다.

### 최소 예시

```python
from review_crawler.core.base import BaseCollector
from review_crawler.core.exceptions import NotSupportedError
from review_crawler.core.models import Product, Review


class KurlyCollector(BaseCollector):
    platform = "kurly"      # 폴더명과 동일해야 합니다
    label = "마켓컬리"        # CLI 목록에 표시될 이름

    # 인증 정보가 필요한 경우에만 (Settings 의 속성명)
    # required_settings = ("kurly_api_key",)

    async def search_products(self, keyword: str, limit: int = 20) -> list[Product]:
        response = await self.client.get(
            "https://api.example.com/search",
            params={"q": keyword, "limit": limit},
        )
        response.raise_for_status()

        return [
            Product(
                platform=self.platform,
                product_id=str(item["no"]),
                name=item["name"],
                url=item["link"],
                price=item.get("price"),
            )
            for item in response.json()["items"]
        ]

    async def get_product(self, product_id: str) -> Product:
        raise NotSupportedError(f"{self.platform}: 미구현")

    async def get_reviews(self, product_id: str, limit: int = 50) -> list[Review]:
        raise NotSupportedError(f"{self.platform}: 미구현")
```

### JS 렌더링이 필요한 경우

`BrowserCollector` 를 상속하면 Playwright 를 쓸 수 있습니다. `self.client`(httpx)도 그대로 사용 가능하므로, 상품은 API·리뷰는 렌더링 같은 혼합 방식도 됩니다.

```python
from review_crawler.core.browser import BrowserCollector


class MusinsaCollector(BrowserCollector):
    platform = "musinsa"
    label = "무신사"

    async def get_reviews(self, product_id: str, limit: int = 50) -> list[Review]:
        async with self.page() as page:
            await page.goto(f"https://www.musinsa.com/products/{product_id}")
            await page.wait_for_selector(".review-list")
            html = await page.content()
        ...
```

브라우저는 collector 당 1개만