import time
from typing import Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from enrichers.base import BaseEnricher
from enrichers.enrichment_models import EnrichmentResult, StreamingOffer, TMDBMovieInfo


class TMDBEnricher(BaseEnricher):
    """Enricher using TMDB API for streaming availability."""

    # Country code to name mapping (ISO 3166-1 alpha-2)
    COUNTRY_NAMES = {
        "US": "United States",
        "GB": "United Kingdom",
        "CA": "Canada",
        "FR": "France",
        "DE": "Germany",
        "IT": "Italy",
        "ES": "Spain",
        "BR": "Brazil",
        "MX": "Mexico",
        "AR": "Argentina",
        "AU": "Australia",
        "NZ": "New Zealand",
        "JP": "Japan",
        "KR": "South Korea",
        "IN": "India",
        "NL": "Netherlands",
        "BE": "Belgium",
        "CH": "Switzerland",
        "AT": "Austria",
        "SE": "Sweden",
        "NO": "Norway",
        "DK": "Denmark",
        "FI": "Finland",
        "PL": "Poland",
        "CZ": "Czech Republic",
        "PT": "Portugal",
        "IE": "Ireland",
        "ZA": "South Africa",
        "SG": "Singapore",
        "HK": "Hong Kong",
        "TW": "Taiwan",
        "TH": "Thailand",
        "ID": "Indonesia",
        "MY": "Malaysia",
        "PH": "Philippines",
        "VN": "Vietnam",
    }

    # Offer type mapping
    OFFER_TYPE_NAMES = {
        "flatrate": "Streaming (Subscription)",
        "rent": "Rent",
        "buy": "Buy",
        "free": "Free",
        "ads": "Free with Ads",
    }

    def __init__(self, api_key: str, rate_limit_per_second: float = 5.0, language: str = "en-US"):
        """
        Initialize TMDB enricher.

        Args:
            api_key: TMDB API key
            rate_limit_per_second: Maximum requests per second (default: 5)
            language: TMDB API language for metadata (default: en-US)
        """
        super().__init__()

        if not api_key:
            raise ValueError("TMDB API key is required")

        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.language = language
        self.rate_limit_delay = 1.0 / rate_limit_per_second  # Convert to delay between requests
        self.last_request_time = 0.0

        self.session = requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": "ScreenSeeker/1.0"}
        )

        self.logger.info(f"TMDB enricher initialized (rate limit: {rate_limit_per_second} req/s)")

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - elapsed
            self.logger.debug(f"Rate limiting: sleeping {sleep_time:.3f}s")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    @retry(
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _make_request(self, endpoint: str, params: dict = None) -> dict:
        """
        Make a request to TMDB API with rate limiting and retries.

        Args:
            endpoint: API endpoint (e.g., "/search/movie")
            params: Query parameters

        Returns:
            JSON response as dictionary

        Raises:
            requests.RequestException: On API errors
        """
        self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        params = params or {}
        params["api_key"] = self.api_key

        self.logger.debug(f"TMDB API request: {endpoint}")

        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()

        return response.json()

    def _search_movie(self, title: str, year: Optional[int] = None) -> Optional[dict]:
        """
        Search for a movie on TMDB.

        Args:
            title: Movie title
            year: Optional release year

        Returns:
            Best matching movie result or None
        """
        params = {"query": title, "language": self.language, "include_adult": "false"}

        if year:
            params["year"] = str(year)
            params["primary_release_year"] = str(year)

        try:
            data = self._make_request("/search/movie", params)

            results = data.get("results", [])
            if not results:
                self.logger.warning(f"No TMDB results for '{title}' ({year})")
                return None

            # Return first result (TMDB sorts by relevance)
            best_match = results[0]
            self.logger.info(
                f"Found TMDB match: '{best_match.get('title')}' "
                f"({best_match.get('release_date', 'N/A')[:4]}) "
                f"[ID: {best_match.get('id')}]"
            )
            return best_match

        except requests.RequestException as e:
            self.logger.error(f"TMDB search failed for '{title}': {e}")
            return None

    def _search_movie_fuzzy_year(self, title: str, year: Optional[int] = None) -> Optional[dict]:
        """
        Search for a movie on TMDB with fuzzy year matching (±1 year).

        Handles year mismatches between Letterboxd and TMDB by trying:
        1. Exact year match
        2. Year + 1 (TMDB often has later release dates)
        3. Year - 1 (TMDB might have earlier premiere dates)
        4. No year constraint (as fallback)

        Args:
            title: Movie title
            year: Optional release year from Letterboxd

        Returns:
            Best matching movie result or None
        """
        # Try exact year first
        if year:
            result = self._search_movie(title, year)
            if result:
                return result

            # Try year + 1 (most common mismatch)
            self.logger.debug(f"No exact match, trying year+1: {year + 1}")
            result = self._search_movie(title, year + 1)
            if result:
                self.logger.info(f"Found match with year+1: {year + 1} instead of {year}")
                return result

            # Try year - 1 (less common but happens with festival premieres)
            self.logger.debug(f"No match with year+1, trying year-1: {year - 1}")
            result = self._search_movie(title, year - 1)
            if result:
                self.logger.info(f"Found match with year-1: {year - 1} instead of {year}")
                return result

            # Fall back to search without year
            self.logger.debug("No match with year±1, trying without year constraint")

        # Search without year constraint
        result = self._search_movie(title, None)
        if result and year:
            tmdb_year_str = result.get("release_date", "")[:4]
            if tmdb_year_str:
                tmdb_year = int(tmdb_year_str)
                year_diff = abs(tmdb_year - year)
                if year_diff > 1:
                    self.logger.warning(f"Year mismatch > 1: Letterboxd={year}, TMDB={tmdb_year}")

        return result

    def _get_watch_providers(self, movie_id: int) -> dict:
        """
        Get streaming providers for a movie across all countries.

        Args:
            movie_id: TMDB movie ID

        Returns:
            Watch providers data by country
        """
        try:
            data = self._make_request(f"/movie/{movie_id}/watch/providers")
            return data.get("results", {})

        except requests.RequestException as e:
            self.logger.error(f"Failed to get watch providers for movie {movie_id}: {e}")
            return {}

    def _calculate_match_confidence(
        self,
        query_title: str,
        query_year: Optional[int],
        result_title: str,
        result_year: Optional[int],
    ) -> str:
        """
        Calculate confidence level of the match.

        Args:
            query_title: Queried title
            query_year: Queried year
            result_title: Result title
            result_year: Result year from release_date

        Returns:
            Confidence level: 'exact', 'high', 'medium', 'low'
        """
        # Normalize for comparison
        q_title = query_title.lower().strip()
        r_title = result_title.lower().strip()

        title_match = q_title == r_title
        year_match = query_year is None or query_year == result_year

        if title_match and year_match:
            return "exact"
        elif title_match:
            return "high"
        elif query_year and year_match and q_title in r_title:
            return "high"
        elif q_title in r_title or r_title in q_title:
            return "medium"
        else:
            return "low"

    def _parse_tmdb_movie(self, movie_data: dict) -> TMDBMovieInfo:
        """Parse TMDB movie data into TMDBMovieInfo model."""
        release_date = movie_data.get("release_date") or ""
        year = int(release_date[:4]) if release_date and len(release_date) >= 4 else None

        return TMDBMovieInfo(
            tmdb_id=movie_data["id"],
            title=movie_data.get("title", ""),
            original_title=movie_data.get("original_title", ""),
            release_date=release_date or None,
            year=year,
            overview=movie_data.get("overview"),
            original_language=movie_data.get("original_language", "unknown"),
            poster_path=movie_data.get("poster_path"),
            backdrop_path=movie_data.get("backdrop_path"),
            vote_average=movie_data.get("vote_average"),
            popularity=movie_data.get("popularity"),
        )

    def _parse_streaming_offers(self, providers_by_country: dict) -> list[StreamingOffer]:
        """
        Parse TMDB watch providers data into StreamingOffer objects.

        Args:
            providers_by_country: TMDB providers data keyed by country code

        Returns:
            List of StreamingOffer objects
        """
        offers = []

        for country_code, country_data in providers_by_country.items():
            country_name = self.COUNTRY_NAMES.get(country_code, country_code)

            # TMDB provides: flatrate, rent, buy, free, ads
            for offer_type in ["flatrate", "rent", "buy", "free", "ads"]:
                providers = country_data.get(offer_type, [])

                for provider in providers:
                    offer = StreamingOffer(
                        country_code=country_code,
                        country_name=country_name,
                        provider_id=provider["provider_id"],
                        provider_name=provider["provider_name"],
                        offer_type=offer_type,
                        logo_path=provider.get("logo_path"),
                        display_priority=provider.get("display_priority"),
                    )
                    offers.append(offer)

        self.logger.info(
            f"Parsed {len(offers)} streaming offers across {len(providers_by_country)} countries"
        )
        return offers

    def enrich(
        self, title: str, year: Optional[int] = None, fuzzy_year: bool = True
    ) -> EnrichmentResult:
        """
        Enrich a film with TMDB streaming availability data.

        Args:
            title: Film title
            year: Optional release year
            fuzzy_year: Whether to use fuzzy year matching (±1 year)

        Returns:
            EnrichmentResult with streaming data
        """
        self.logger.info(f"Enriching: '{title}' ({year or 'no year'})")

        try:
            # Search for movie (with fuzzy year matching by default)
            if fuzzy_year:
                movie_data = self._search_movie_fuzzy_year(title, year)
            else:
                movie_data = self._search_movie(title, year)

            if not movie_data:
                return EnrichmentResult(
                    query_title=title,
                    query_year=year,
                    match_confidence="none",
                    success=False,
                    error_message=f"No TMDB match found for '{title}'",
                )

            # Parse movie info
            tmdb_movie = self._parse_tmdb_movie(movie_data)

            # Calculate match confidence
            confidence = self._calculate_match_confidence(
                title, year, tmdb_movie.title, tmdb_movie.year
            )

            # Get streaming providers
            providers_data = self._get_watch_providers(tmdb_movie.tmdb_id)
            streaming_offers = self._parse_streaming_offers(providers_data)

            # Calculate statistics
            unique_countries = len({offer.country_code for offer in streaming_offers})
            unique_providers = len({offer.provider_name for offer in streaming_offers})

            result = EnrichmentResult(
                query_title=title,
                query_year=year,
                tmdb_movie=tmdb_movie,
                match_confidence=confidence,
                streaming_offers=streaming_offers,
                total_countries=unique_countries,
                total_providers=unique_providers,
                success=True,
            )

            self.logger.info(
                f"Enrichment complete: {unique_countries} countries, "
                f"{unique_providers} providers, {len(streaming_offers)} total offers"
            )

            return result

        except Exception as e:
            self.logger.error(f"Enrichment failed for '{title}': {e}", exc_info=True)
            return EnrichmentResult(
                query_title=title,
                query_year=year,
                match_confidence="none",
                success=False,
                error_message=str(e),
            )

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close session on exit."""
        self.session.close()
