from difflib import SequenceMatcher
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from screenseeker.logger import get_logger

from ..enrichers.enrichment_models import EnrichmentResult, StreamingOffer

logger = get_logger(__name__)


class WatchOption(BaseModel):
    """Represents a single way to watch a film."""

    model_config = ConfigDict(frozen=True)

    provider: str = Field(..., description="Provider name")
    country_code: str = Field(..., description="Country code (e.g., 'US')")
    country_name: str = Field(..., description="Country name")
    vpn_required: bool = Field(..., description="Whether VPN is needed")
    offer_type: str = Field(..., description="Offer type: flatrate, rent, buy, etc.")
    priority_score: int = Field(..., description="Priority score (lower is better)")
    via_bundle: Optional[str] = Field(None, description="If accessed via bundle (e.g., 'Canal+')")


class WatchStrategy(BaseModel):
    """Complete watch strategy for a film."""

    # Best option (no VPN needed in base country)
    best_option: Optional[WatchOption] = Field(None, description="Best option (no VPN)")

    # VPN options on owned subscriptions
    vpn_options: list[WatchOption] = Field(default_factory=list, description="VPN options")

    # Other options in base country (rent/buy)
    base_country_alternatives: list[WatchOption] = Field(
        default_factory=list, description="Rent/buy in base country"
    )

    # All owned subscriptions options (for reference)
    all_owned_options: list[WatchOption] = Field(
        default_factory=list, description="All options on owned subscriptions"
    )

    # Not available on subscriptions
    not_owned_options: list[StreamingOffer] = Field(
        default_factory=list, description="Available but not owned"
    )

    def has_any_option(self) -> bool:
        """Check if any watching option is available."""
        return bool(self.best_option or self.vpn_options or self.base_country_alternatives)


class WatchStrategyAnalyzer:
    """Analyzes enrichment results against user's subscription profile."""

    def __init__(self, subscription_profile: dict):
        """
        Initialize analyzer with subscription profile.

        Args:
            subscription_profile: Configuration dict with subscriptions and preferences
        """
        self.profile = subscription_profile
        self.base_country = subscription_profile["base_country"]
        self.subscriptions = subscription_profile["subscriptions"]
        self.vpn_priority = subscription_profile.get("vpn_country_priority", [])
        self.max_vpn_suggestions = subscription_profile.get("max_vpn_suggestions", 3)

        # Build provider name mappings
        self._build_provider_mappings()

        logger.info(
            f"Watch strategy analyzer initialized for {self.base_country} "
            f"with {len(self.subscriptions)} subscriptions"
        )

    def _build_provider_mappings(self):
        """Build provider name mappings for fuzzy matching."""
        self.owned_providers = {}  # normalized_name -> subscription_info

        for sub in self.subscriptions:
            for provider_name in sub["provider_names"]:
                normalized = provider_name.lower().strip()
                self.owned_providers[normalized] = sub

            # Add bundle providers if applicable
            if "bundle_includes" in sub:
                for bundle_provider in sub["bundle_includes"]:
                    normalized = bundle_provider.lower().strip()
                    # Mark as bundle with parent info
                    self.owned_providers[normalized] = {
                        **sub,
                        "is_bundle": True,
                        "bundle_parent": sub["provider_names"][0],
                    }

    def _fuzzy_match_provider(self, tmdb_provider: str) -> Optional[dict]:
        """
        Fuzzy match TMDB provider name to owned subscription.

        Args:
            tmdb_provider: Provider name from TMDB

        Returns:
            Subscription info dict or None
        """
        tmdb_normalized = tmdb_provider.lower().strip()

        # Try exact match first
        if tmdb_normalized in self.owned_providers:
            return self.owned_providers[tmdb_normalized]

        # Try fuzzy matching with threshold
        best_match = None
        best_score = 0.0
        threshold = 0.8  # 80% similarity required

        for owned_name, sub_info in self.owned_providers.items():
            similarity = SequenceMatcher(None, tmdb_normalized, owned_name).ratio()

            if similarity > best_score and similarity >= threshold:
                best_score = similarity
                best_match = sub_info

        if best_match:
            logger.debug(
                f"Fuzzy matched '{tmdb_provider}' to subscription (score: {best_score:.2f})"
            )

        return best_match

    def _is_available_in_country(self, subscription: dict, country_code: str) -> bool:
        """Check if subscription is available in a country."""
        available = subscription.get("available_countries", [])

        if available == "all":
            return True

        return country_code in available

    def _get_country_priority_score(self, country_code: str) -> int:
        """
        Get priority score for a country (lower is better).

        Args:
            country_code: ISO country code

        Returns:
            Priority score (0 = highest priority)
        """
        try:
            return self.vpn_priority.index(country_code)
        except ValueError:
            # Not in priority list, assign low priority
            return len(self.vpn_priority) + 1000

    def _create_watch_option(
        self,
        offer: StreamingOffer,
        subscription: dict,
        vpn_required: bool,
        priority_score: int,
    ) -> WatchOption:
        """Create a WatchOption from a StreamingOffer."""
        via_bundle = None
        if subscription.get("is_bundle"):
            via_bundle = subscription.get("bundle_parent")

        return WatchOption(
            provider=offer.provider_name,
            country_code=offer.country_code,
            country_name=offer.country_name,
            vpn_required=vpn_required,
            offer_type=offer.offer_type,
            priority_score=priority_score,
            via_bundle=via_bundle,
        )

    def analyze(self, enrichment_result: EnrichmentResult) -> WatchStrategy:
        """
        Analyze enrichment result and generate personalized watch strategy.

        Args:
            enrichment_result: Result from TMDB enricher

        Returns:
            WatchStrategy with prioritized options
        """
        if not enrichment_result.success or enrichment_result.match_confidence == "none":
            logger.warning("Cannot analyze: enrichment failed or no match")
            return WatchStrategy()

        logger.info(
            f"Analyzing watch strategy for {len(enrichment_result.streaming_offers)} offers"
        )

        # Classify all offers
        owned_flatrate_offers = []  # Subscription streaming
        not_owned_offers = []

        for offer in enrichment_result.streaming_offers:
            # Only consider flatrate (subscription) for owned providers
            if offer.offer_type != "flatrate":
                continue

            # Try to match to owned subscription
            subscription = self._fuzzy_match_provider(offer.provider_name)

            if subscription:
                # Check if available in this country
                if self._is_available_in_country(subscription, offer.country_code):
                    owned_flatrate_offers.append((offer, subscription))
                else:
                    # Owned but not available in this country (e.g., Canal+ outside France)
                    not_owned_offers.append(offer)
            else:
                not_owned_offers.append(offer)

        # Separate base country vs VPN options
        best_option = None
        vpn_options = []
        all_owned = []

        for offer, subscription in owned_flatrate_offers:
            vpn_enabled = subscription.get("vpn_enabled", False)
            in_base_country = offer.country_code == self.base_country

            # Calculate priority score
            if in_base_country:
                priority_score = 0  # Highest priority
            else:
                priority_score = self._get_country_priority_score(offer.country_code) + 1

            vpn_required = not in_base_country and vpn_enabled

            watch_option = self._create_watch_option(
                offer, subscription, vpn_required, priority_score
            )

            all_owned.append(watch_option)

            # Categorize
            if in_base_country and not best_option:
                # First option in base country is best
                best_option = watch_option
            elif in_base_country:
                # Additional options in base country (tie)
                if best_option.priority_score == priority_score:
                    vpn_options.append(watch_option)  # Show as alternative
            elif vpn_enabled:
                # VPN option
                vpn_options.append(watch_option)

        # Sort VPN options by priority and limit to max suggestions
        vpn_options.sort(key=lambda x: x.priority_score)
        vpn_options = vpn_options[: self.max_vpn_suggestions]

        # Get rent/buy alternatives in base country
        base_country_alternatives = []
        for offer in enrichment_result.streaming_offers:
            if offer.country_code == self.base_country and offer.offer_type in [
                "rent",
                "buy",
            ]:
                watch_option = WatchOption(
                    provider=offer.provider_name,
                    country_code=offer.country_code,
                    country_name=offer.country_name,
                    vpn_required=False,
                    offer_type=offer.offer_type,
                    priority_score=1000,  # Low priority
                    via_bundle=None,
                )
                base_country_alternatives.append(watch_option)

        strategy = WatchStrategy(
            best_option=best_option,
            vpn_options=vpn_options,
            base_country_alternatives=base_country_alternatives,
            all_owned_options=all_owned,
            not_owned_options=not_owned_offers,
        )

        logger.info(
            f"Strategy: best={bool(best_option)}, vpn={len(vpn_options)}, "
            f"rent/buy={len(base_country_alternatives)}"
        )

        return strategy
