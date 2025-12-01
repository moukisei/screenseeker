import json
import sys
from typing import Optional

import config
from enrichers import TMDBEnricher, WatchStrategyAnalyzer
from logger import get_logger, setup_logger

# Set up logging
setup_logger(level=config.LOG_LEVEL, log_to_file=config.LOG_TO_FILE, use_colors=True)
logger = get_logger(__name__)


def parse_title_year(input_string: str) -> tuple[str, Optional[int]]:
    """
    Parse a string like 'The Matrix (1999)' into title and year.

    Args:
        input_string: String with optional year in parentheses

    Returns:
        Tuple of (title, year)
    """
    import re

    # Try to match "Title (YYYY)" pattern
    match = re.match(r"^(.+?)\s*\((\d{4})\)$", input_string.strip())

    if match:
        title = match.group(1).strip()
        year = int(match.group(2))
        return title, year
    else:
        # No year found
        return input_string.strip(), None


def display_watch_strategy(result, strategy):
    """Display personalized watch strategy based on user's subscriptions."""

    logger.info("\n" + "=" * 80)
    logger.info("HOW TO WATCH")
    logger.info("=" * 80)

    # Query info
    logger.info(f"\n📽️  '{result.query_title}' ({result.query_year or 'no year'})")

    # Match status
    if not result.success:
        logger.error(f"\n❌ Enrichment failed: {result.error_message}")
        return

    if result.match_confidence == "none":
        logger.warning("\n⚠️  No match found on TMDB")
        return

    # TMDB match
    movie = result.tmdb_movie
    confidence_emoji = {"exact": "🎯", "high": "✅", "medium": "⚠️", "low": "❓"}.get(
        result.match_confidence, "❓"
    )

    logger.info(
        f"{confidence_emoji} TMDB Match: {movie.title} ({movie.year or 'N/A'}) - Confidence: {result.match_confidence}"
    )
    if movie.vote_average:
        logger.info(f"   ⭐ Rating: {movie.vote_average}/10")

    # Check if any watching options available
    if not strategy.has_any_option():
        logger.warning("\n❌ NOT AVAILABLE on your subscriptions")
        logger.info(
            f"   Available globally in {result.total_countries} countries on {result.total_providers} providers"
        )
        logger.info("   But not on Netflix, Prime Video, or Canal+ bundle")
        logger.info("\n" + "=" * 80)
        return

    # Best option (no VPN needed)
    if strategy.best_option:
        logger.info("\n✅ WATCH NOW (No VPN needed):")
        opt = strategy.best_option
        if opt.via_bundle:
            logger.info(f"   🇫🇷 {opt.provider} (via {opt.via_bundle}) - {opt.country_name}")
        else:
            logger.info(f"   🇫🇷 {opt.provider} - {opt.country_name}")

    # VPN options
    if strategy.vpn_options:
        logger.info("\n🌍 VPN OPTIONS (Use NordVPN):")
        for opt in strategy.vpn_options:
            # Country flag emoji mapping for common countries
            country_flags = {
                "US": "🇺🇸",
                "GB": "🇬🇧",
                "CA": "🇨🇦",
                "AU": "🇦🇺",
                "FR": "🇫🇷",
                "DE": "🇩🇪",
                "ES": "🇪🇸",
                "IT": "🇮🇹",
                "JP": "🇯🇵",
                "BR": "🇧🇷",
                "MX": "🇲🇽",
                "NL": "🇳🇱",
                "IN": "🇮🇳",
                "KR": "🇰🇷",
                "NZ": "🇳🇿",
                "IE": "🇮🇪",
                "SE": "🇸🇪",
                "NO": "🇳🇴",
                "DK": "🇩🇰",
                "FI": "🇫🇮",
            }
            flag = country_flags.get(opt.country_code, "🌎")

            if opt.via_bundle:
                logger.info(
                    f"   {flag} {opt.provider} (via {opt.via_bundle}) - Connect to {opt.country_name}"
                )
            else:
                logger.info(f"   {flag} {opt.provider} - Connect to {opt.country_name}")

    # Rent/Buy alternatives
    if strategy.base_country_alternatives:
        logger.info("\n💰 RENT/BUY IN FRANCE:")
        # Group by offer type
        rent_providers = [
            opt.provider for opt in strategy.base_country_alternatives if opt.offer_type == "rent"
        ]
        buy_providers = [
            opt.provider for opt in strategy.base_country_alternatives if opt.offer_type == "buy"
        ]

        if rent_providers:
            logger.info(f"   Rent: {', '.join(rent_providers)}")
        if buy_providers:
            logger.info(f"   Buy: {', '.join(buy_providers)}")

    # Summary
    logger.info("\n📊 Summary:")
    logger.info(
        f"   Total global availability: {result.total_countries} countries, {result.total_providers} providers"
    )
    logger.info(
        f"   Your options: {len(strategy.all_owned_options)} streaming options across your subscriptions"
    )

    logger.info("\n" + "=" * 80)


def save_result_to_json(result, filename: str = "enrichment_result.json"):
    """Save enrichment result to JSON file."""
    output_path = config.OUTPUT_DIR / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

    logger.info(f"\n💾 Result saved to: {output_path}")


def main():
    """Main CLI entry point."""

    # Check if TMDB API key is configured
    if not config.TMDB_API_KEY or config.TMDB_API_KEY == "your_tmdb_api_key_here":
        logger.error("❌ TMDB API key not configured!")
        logger.error("Please set TMDB_API_KEY in config.py")
        logger.error("Get your free API key at: https://www.themoviedb.org/settings/api")
        return 1

    # Get input from user
    if len(sys.argv) < 2:
        logger.info("Usage: python enrich.py 'Movie Title (Year)'")
        logger.info("Example: python enrich.py 'The Matrix (1999)'")
        logger.info("\nInteractive mode:")

        try:
            user_input = input("\nEnter movie title (with optional year): ").strip()
            if not user_input:
                logger.error("No input provided")
                return 1
        except (KeyboardInterrupt, EOFError):
            logger.info("\nCancelled by user")
            return 0
    else:
        user_input = " ".join(sys.argv[1:])

    # Parse input
    title, year = parse_title_year(user_input)

    logger.info(f"🔍 Searching for: '{title}' ({year or 'no year specified'})")

    # Create enricher and enrich
    try:
        with TMDBEnricher(
            api_key=config.TMDB_API_KEY,
            rate_limit_per_second=config.TMDB_RATE_LIMIT,
            language=config.TMDB_LANGUAGE,
        ) as enricher:
            result = enricher.enrich(title, year)

            # Analyze with watch strategy
            analyzer = WatchStrategyAnalyzer(config.SUBSCRIPTION_PROFILE)
            strategy = analyzer.analyze(result)

            # Display personalized watch strategy
            display_watch_strategy(result, strategy)

            # Save to JSON
            if result.success:
                save_result_to_json(result)

            return 0 if result.success else 1

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user")
        return 0

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
