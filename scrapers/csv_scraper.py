import csv
from pathlib import Path
from typing import Optional

from models import Film, ScrapingResult
from scrapers.base import BaseScraper


class CSVScraper(BaseScraper):
    """Parser for Letterboxd CSV export files."""

    def __init__(
        self,
        csv_file_path: str,
        save_raw_data: bool = False,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize the CSV scraper.

        Args:
            csv_file_path: Path to the Letterboxd CSV export file
            save_raw_data: Whether to save raw data for analysis
            output_dir: Directory to save outputs (defaults to ./output)
        """
        super().__init__(output_dir=output_dir, save_raw_data=save_raw_data)
        self.csv_file_path = Path(csv_file_path)

        if not self.csv_file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_file_path}")

        self.logger.info(f"CSV scraper initialized with file: {csv_file_path}")

    def scrape(self) -> ScrapingResult:
        """
        Parse films from the CSV export file.

        Expected CSV columns:
        - Name: Film title without year (required)
        - Year: Release year (optional)
        - Date: Date added to watchlist (optional)

        Returns:
            ScrapingResult containing the parsed films and metadata
        """
        self.logger.info(f"Starting CSV parsing from {self.csv_file_path}")
        films: list[Film] = []

        try:
            with open(self.csv_file_path, "r", encoding="utf-8") as f:
                # Use csv.DictReader to handle column names automatically
                reader = csv.DictReader(f)

                # Validate that required columns exist
                required_columns = {"Name"}
                if not required_columns.issubset(set(reader.fieldnames or [])):
                    missing = required_columns - set(reader.fieldnames or [])
                    error_msg = f"Missing required columns in CSV: {missing}"
                    self.logger.error(error_msg)
                    return ScrapingResult(
                        films=[],
                        total_pages_scraped=0,
                        success=False,
                        error_message=error_msg,
                        source="csv",
                    )

                # Parse each row
                row_count = 0
                for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                    row_count += 1

                    try:
                        # Extract data from row
                        name = row.get("Name", "").strip()
                        year_str = row.get("Year", "").strip()
                        date_added = row.get("Date", "").strip()

                        # Skip empty rows
                        if not name:
                            self.logger.warning(f"Row {row_num}: Missing name, skipping")
                            continue

                        # Parse year
                        year = None
                        if year_str:
                            try:
                                year = int(year_str)
                            except ValueError:
                                self.logger.warning(
                                    f"Row {row_num}: Could not parse year '{year_str}'"
                                )

                        # Build full title
                        film_title = name
                        film_full_title = f"{film_title} ({year})" if year else film_title

                        # Create Film instance
                        film = Film(
                            film_full_title=film_full_title,
                            film_title=film_title,
                            year=year,
                            date_added=date_added if date_added else None,
                            # film_id will be auto-generated
                            # date_added will use CSV date or default to today if not provided
                        )
                        films.append(film)

                    except ValueError as e:
                        self.logger.warning(f"Row {row_num}: Invalid film data - {e}")
                        continue
                    except Exception as e:
                        self.logger.error(f"Row {row_num}: Unexpected error - {e}")
                        continue

                self.logger.info(f"Parsed {len(films)} films from {row_count} rows")

                return ScrapingResult(
                    films=films,
                    total_pages_scraped=1,  # CSV is a single "page"
                    success=True,
                    source="csv",
                )

        except FileNotFoundError as e:
            error_msg = f"CSV file not found: {str(e)}"
            self.logger.error(error_msg)
            return ScrapingResult(
                films=[],
                total_pages_scraped=0,
                success=False,
                error_message=error_msg,
                source="csv",
            )

        except csv.Error as e:
            error_msg = f"CSV parsing error: {str(e)}"
            self.logger.error(error_msg)
            return ScrapingResult(
                films=films,
                total_pages_scraped=0,
                success=False,
                error_message=error_msg,
                source="csv",
            )

        except Exception as e:
            error_msg = f"Unexpected error during CSV parsing: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return ScrapingResult(
                films=films,
                total_pages_scraped=0,
                success=False,
                error_message=error_msg,
                source="csv",
            )
