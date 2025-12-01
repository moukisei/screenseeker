import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from models import Film, ScrapingResult
from scrapers.base import BaseScraper


class HTMLScraper(BaseScraper):
    """Scraper for extracting film data from Letterboxd profiles via HTML."""

    def __init__(
        self,
        base_url: str,
        delay_between_requests: float = 2.0,
        timeout: int = 10,
        save_raw_data: bool = False,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the HTML scraper.

        Args:
            base_url: Base URL for the Letterboxd profile
            delay_between_requests: Delay in seconds between page requests
            timeout: Request timeout in seconds
            save_raw_data: Whether to save raw HTML responses for analysis
            output_dir: Directory to save outputs (defaults to ./output)
        """
        super().__init__(output_dir=output_dir, save_raw_data=save_raw_data)

        self.base_url = base_url.rstrip("/")
        self.delay = delay_between_requests
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )

        # Create output directory if saving raw HTML
        if self.save_raw_data:
            self.html_dir = self.output_dir / "raw_html" / datetime.now().strftime("%Y%m%d_%H%M%S")
            self.html_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Raw HTML will be saved to {self.html_dir}")

    def scrape(self) -> ScrapingResult:
        """
        Scrape all films from the Letterboxd profile.

        Returns:
            ScrapingResult containing the scraped films and metadata
        """
        self.logger.info("Starting HTML scraping...")
        films: list[Film] = []
        page = 1

        try:
            while True:
                self.logger.debug(f"Scraping page {page}...")

                # Fetch the page
                url = f"{self.base_url}/page/{page}/"
                response = self.session.get(url, timeout=self.timeout)

                if response.status_code != 200:
                    self.logger.warning(
                        f"Received status code {response.status_code} for page {page}"
                    )
                    break

                # Save raw HTML if requested
                if self.save_raw_data:
                    self._save_html_response(response.text, page)

                # Parse the HTML
                soup = BeautifulSoup(response.text, "html.parser")
                grid_items = soup.select(".griditem")

                # If no films found on the page, stop
                if not grid_items:
                    self.logger.info(f"No films found on page {page}. Stopping pagination.")
                    break

                # Extract films from grid items
                page_films = self._extract_films_from_grid(grid_items)
                films.extend(page_films)
                self.logger.info(f"Found {len(page_films)} films on page {page}")

                page += 1
                time.sleep(self.delay)  # Rate limiting

            return ScrapingResult(
                films=films, total_pages_scraped=page - 1, success=True, source="html"
            )

        except requests.RequestException as e:
            self.logger.error(f"Request failed: {e}")
            return ScrapingResult(
                films=films,
                total_pages_scraped=page - 1,
                success=False,
                error_message=f"Request error: {str(e)}",
                source="html",
            )

        except Exception as e:
            self.logger.error(f"Unexpected error during scraping: {e}", exc_info=True)
            return ScrapingResult(
                films=films,
                total_pages_scraped=page - 1,
                success=False,
                error_message=f"Unexpected error: {str(e)}",
                source="html",
            )

    def _save_html_response(self, html_content: str, page_number: int) -> None:
        """
        Save raw HTML response to a file.

        Args:
            html_content: Raw HTML content
            page_number: Page number being saved
        """
        filepath = self.html_dir / f"page_{page_number:04d}.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        self.logger.debug(f"Saved raw HTML for page {page_number} to {filepath}")

    def _extract_films_from_grid(self, grid_items) -> list[Film]:
        """
        Extract film data from grid items.

        Args:
            grid_items: BeautifulSoup result set of grid items

        Returns:
            List of Film objects
        """
        films: list[Film] = []

        for item in grid_items:
            react_component = item.find("div", class_="react-component")

            if not react_component:
                continue

            title = react_component.get("data-item-full-display-name")

            # Skip if missing data
            if not title:
                self.logger.warning("Skipping item with missing title")
                continue

            try:
                # Parse title into components
                film_full_title, film_title, year = Film.parse_title_and_year(title)

                # Create Film object (film_id and date_added will be auto-generated)
                film = Film(
                    film_full_title=film_full_title,
                    film_title=film_title,
                    year=year,
                    # film_id will be auto-generated from title+year
                    # date_added will default to today's date
                )
                films.append(film)
            except ValueError as e:
                self.logger.warning(f"Invalid film data for '{title}': {e}")
                continue

        return films

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close session."""
        self.session.close()
