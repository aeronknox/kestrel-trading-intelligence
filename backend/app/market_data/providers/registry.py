"""Provider registry: one shared instance per provider name."""

from app.core.config import get_settings
from app.market_data.providers.base import MarketDataProvider

_providers: dict[str, MarketDataProvider] = {}


def get_provider(name: str | None = None) -> MarketDataProvider:
    settings = get_settings()
    name = name or settings.market_data_provider
    if name not in _providers:
        if name == "coinbase":
            from app.market_data.providers.coinbase import CoinbaseProvider

            _providers[name] = CoinbaseProvider(base_url=settings.coinbase_base_url)
        elif name == "sample":
            from app.market_data.providers.sample import SampleProvider

            _providers[name] = SampleProvider()
        else:
            raise ValueError(f"Unknown market data provider '{name}'")
    return _providers[name]


def register_provider(provider: MarketDataProvider) -> None:
    """Used by tests to inject a provider."""
    _providers[provider.name] = provider


async def close_providers() -> None:
    for provider in _providers.values():
        await provider.close()
    _providers.clear()
