"""Main entry point for the Letterboxd scraper."""

import logging
import sys

import config
from exporters import JSONExporter
from scrapers import CSVScraper, HTMLScraper

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_scraper():
    """
    Create and return the appropriate scraper based on configuration.

    Returns:
        BaseScraper instance (HTMLScraper or CSVScraper)

    Raises:
        ValueError: If SCRAPER_TYPE is invalid
    """
    scraper_type = config.SCRAPER_TYPE.lower()

    if scraper_type == "html":
        logger.info("Using HTML scraper")
        return HTMLScraper(
            base_url=config.HTML_URL,
            delay_between_requests=config.HTML_DELAY_BETWEEN_REQUESTS,
            timeout=config.HTML_TIMEOUT,
            save_raw_data=config.SAVE_RAW_DATA,
            output_dir=config.OUTPUT_DIR
        )

    elif scraper_type == "csv":
        logger.info("Using CSV scraper")
        return CSVScraper(
            csv_file_path=config.CSV_FILE_PATH,
            save_raw_data=config.SAVE_RAW_DATA,
            output_dir=config.OUTPUT_DIR
        )

    else:
        raise ValueError(
            f"Invalid SCRAPER_TYPE: {config.SCRAPER_TYPE}. "
            f"Must be 'html' or 'csv'"
        )


def display_results(result):
    """
    Display scraping results to the user.

    Args:
        result: ScrapingResult to display
    """
    if not result.success:
        logger.error(f"Scraping failed: {result.error_message}")
        logger.error("Could not fetch films. Check configuration and try again.")
        return

    if result.film_count == 0:
        logger.warning("No films found. The source may be empty or inaccessible.")
        return

    logger.info(f"Successfully scraped {result.film_count} films using {result.source} scraper")

    # Display first 10 films with parsed data
    display_count = min(10, result.film_count)
    logger.info(f"\nFirst {display_count} films:")

    for film in result.films[:display_count]:
        year_str = f" ({film.year})" if film.year else ""
        logger.info(f"  🎬 {film.film_title}{year_str}")
        logger.info(f"     ID: {film.film_id}")

        # Show additional CSV-specific data if available
        if film.date_added:
            logger.info(f"     Added: {film.date_added}")

    # Display statistics
    films_with_year = sum(1 for f in result.films if f.year is not None)
    year_percentage = (films_with_year / result.film_count * 100) if result.film_count > 0 else 0

    logger.info(f"\nStatistics:")
    logger.info(f"  Source: {result.source}")
    logger.info(f"  Total films: {result.film_count}")
    logger.info(f"  Films with year: {films_with_year} ({year_percentage:.1f}%)")

    if result.source == "html":
        logger.info(f"  Pages scraped: {result.total_pages_scraped}")


def main() -> int:
    """
    Main entry point for the scraper.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        logger.info("Starting Letterboxd scraper...")
        logger.info(f"Configuration: SCRAPER_TYPE={config.SCRAPER_TYPE}")

        # Create the appropriate scraper
        with create_scraper() as scraper:
            # Perform the scraping
            result = scraper.scrape()

            # Display results
            display_results(result)

            # Export to JSON if successful
            if result.success and result.film_count > 0:
                output_file = JSONExporter.export_to_default_location(
                    result,
                    config.OUTPUT_DIR
                )
                logger.info(f"\nData saved to: {output_file}")
                return 0
            else:
                logger.error("Scraping completed but no data was collected or errors occurred")
                return 1

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        logger.error("Check that CSV_FILE_PATH is set correctly in config.py")
        return 1

    except KeyboardInterrupt:
        logger.info("\nScraping interrupted by user")
        return 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
