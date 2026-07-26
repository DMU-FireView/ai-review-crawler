"""
로컬 수집/테스트용 CLI.

    crawler list                              등록된 collector 목록
    crawler collect                           대화형으로 선택해 상품 수집
    crawler reviews <platform> <product_id>   특정 상품의 리뷰 수집
    crawler serve                             결과 확인용 FastAPI 서버 실행
"""

import asyncio

import questionary
import typer

from review_crawler.core import storage
from review_crawler.core.base import BaseCollector
from review_crawler.core.discovery import discover
from review_crawler.core.exceptions import CollectorError, NotSupportedError
from review_crawler.core.settings import ENV_FILE, env_file_exists

app = typer.Typer(help="커머스 리뷰 수집 도구", no_args_is_help=True)


def _require_env() -> None:
    if not env_file_exists():
        typer.secho(f"\n❌ .env 파일이 없습니다: {ENV_FILE}", fg=typer.colors.RED, bold=True)
        typer.echo("   프로젝트 루트에서 아래 명령을 실행하세요:\n")
        typer.echo("     cp .env.example .env\n")
        raise typer.Exit(1)


def _load_registry() -> dict[str, type[BaseCollector]]:
    registry, failures = discover()
    for failure in failures:
        typer.secho(f"\n⚠️  [{failure.package}] 로드 실패", fg=typer.colors.YELLOW, bold=True)
        typer.echo(failure.traceback_text)
    return registry


@app.command("list")
def list_collectors() -> None:
    """등록된 collector 목록을 출력합니다."""
    _require_env()
    registry = _load_registry()

    if not registry:
        typer.echo("\n등록된 collector 가 없습니다.")
        typer.echo("collectors/_template/collector.py 를 복사해 자기 폴더에 만드세요.\n")
        raise typer.Exit()

    typer.echo("\n등록된 collector:")
    for name, cls in sorted(registry.items()):
        needs = (
            f"  (필요 설정: {', '.join(s.upper() for s in cls.required_settings)})"
            if cls.required_settings
            else ""
        )
        typer.echo(f"  • {name:<12} {cls.label or ''}{needs}")
    typer.echo()


@app.command()
def collect(
    keyword: str = typer.Option(None, "--keyword", "-k", help="검색 키워드"),
    limit: int = typer.Option(20, "--limit", "-n", help="수집 개수"),
    save: bool = typer.Option(True, "--save/--no-save", help="결과를 JSON 으로 저장"),
) -> None:
    """대화형으로 플랫폼을 선택해 상품을 수집합니다."""
    _require_env()
    registry = _load_registry()

    if not registry:
        typer.secho("사용 가능한 collector 가 없습니다.", fg=typer.colors.RED)
        raise typer.Exit(1)

    selected = questionary.checkbox(
        "수집할 플랫폼을 선택하세요 (스페이스: 선택 / 엔터: 확정)",
        choices=sorted(registry.keys()),
    ).ask()

    if not selected:
        typer.echo("선택된 플랫폼이 없습니다.")
        raise typer.Exit()

    if not keyword:
        keyword = questionary.text("검색 키워드를 입력하세요").ask()
    if not keyword:
        typer.echo("키워드가 없습니다.")
        raise typer.Exit()

    asyncio.run(_collect_products(registry, selected, keyword, limit, save))


@app.command()
def reviews(
    platform: str = typer.Argument(help="플랫폼 식별자 (crawler list 로 확인)"),
    product_id: str = typer.Argument(help="해당 플랫폼의 상품 ID"),
    limit: int = typer.Option(50, "--limit", "-n", help="수집 개수"),
    save: bool = typer.Option(True, "--save/--no-save", help="결과를 JSON 으로 저장"),
) -> None:
    """특정 상품의 리뷰를 수집합니다."""
    _require_env()
    registry = _load_registry()

    collector_cls = registry.get(platform)
    if collector_cls is None:
        typer.secho(
            f"'{platform}' collector 가 없습니다. 사용 가능: {sorted(registry)}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    asyncio.run(_collect_reviews(collector_cls, platform, product_id, limit, save))


async def _collect_products(
    registry: dict[str, type[BaseCollector]],
    platforms: list[str],
    keyword: str,
    limit: int,
    do_save: bool,
) -> None:
    for name in platforms:
        typer.secho(f"\n▶ [{name}] 상품 수집", fg=typer.colors.CYAN, bold=True)
        try:
            async with registry[name]() as collector:
                products = await collector.search_products(keyword, limit=limit)
            typer.echo(f"  {len(products)}건 수집")
            if do_save and products:
                path = storage.save(name, "products", products)
                typer.echo(f"  저장: {path}")
        except NotSupportedError as exc:
            typer.secho(f"  건너뜀: {exc}", fg=typer.colors.YELLOW)
        except CollectorError as exc:
            typer.secho(f"  실패: {exc}", fg=typer.colors.RED)
        except Exception as exc:  # noqa: BLE001
            typer.secho(f"  예외: {type(exc).__name__}: {exc}", fg=typer.colors.RED)


async def _collect_reviews(
    collector_cls: type[BaseCollector],
    platform: str,
    product_id: str,
    limit: int,
    do_save: bool,
) -> None:
    typer.secho(f"\n▶ [{platform}] 리뷰 수집 (product_id={product_id})", fg=typer.colors.CYAN)
    try:
        async with collector_cls() as collector:
            items = await collector.get_reviews(product_id, limit=limit)
        typer.echo(f"  {len(items)}건 수집")
        if do_save and items:
            path = storage.save(platform, "reviews", items)
            typer.echo(f"  저장: {path}")
    except NotSupportedError as exc:
        typer.secho(f"  건너뜀: {exc}", fg=typer.colors.YELLOW)
    except CollectorError as exc:
        typer.secho(f"  실패: {exc}", fg=typer.colors.RED)
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"  예외: {type(exc).__name__}: {exc}", fg=typer.colors.RED)


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(True, "--reload/--no-reload"),
) -> None:
    """수집 결과를 확인할 수 있는 FastAPI 서버를 실행합니다."""
    _require_env()
    import uvicorn

    uvicorn.run("review_crawler.api.app:app", host="127.0.0.1", port=port, reload=reload)


if __name__ == "__main__":
    app()