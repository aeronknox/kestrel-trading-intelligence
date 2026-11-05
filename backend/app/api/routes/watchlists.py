from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.market_data.service import MarketDataService
from app.models.market import Watchlist, WatchlistItem
from app.schemas.market import WatchlistAddRequest, WatchlistOut

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


async def _default_watchlist(db, user_id: int) -> Watchlist:  # type: ignore[no-untyped-def]
    wl = await db.scalar(select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.id).limit(1))
    if wl is None:
        wl = Watchlist(user_id=user_id, name="Default")
        db.add(wl)
        await db.flush()
        await db.refresh(wl, attribute_names=["items"])
    return wl


@router.get("/default", response_model=WatchlistOut)
async def get_default(user: CurrentUser, db: DbSession) -> object:
    return await _default_watchlist(db, user.id)


@router.post("/default/items", response_model=WatchlistOut, status_code=201)
async def add_item(body: WatchlistAddRequest, user: CurrentUser, db: DbSession) -> object:
    wl = await _default_watchlist(db, user.id)
    asset = await MarketDataService(db).get_asset(body.symbol)
    if any(i.asset_id == asset.id for i in wl.items):
        raise ConflictError(f"{asset.symbol} is already on your watchlist")
    pos = (await db.scalar(select(func.max(WatchlistItem.position)).where(WatchlistItem.watchlist_id == wl.id))) or 0
    db.add(WatchlistItem(watchlist_id=wl.id, asset_id=asset.id, position=pos + 1))
    await db.flush()
    await db.refresh(wl, attribute_names=["items"])
    return wl


@router.delete("/default/items/{symbol}", response_model=WatchlistOut)
async def remove_item(symbol: str, user: CurrentUser, db: DbSession) -> object:
    wl = await _default_watchlist(db, user.id)
    item = next((i for i in wl.items if i.asset.symbol == symbol.upper()), None)
    if item is None:
        raise NotFoundError(f"{symbol.upper()} is not on your watchlist")
    await db.delete(item)
    await db.flush()
    await db.refresh(wl, attribute_names=["items"])
    return wl
