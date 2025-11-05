import json
from pathlib import Path

from logger import get_logger
from models import ScrapingResult

logger = get_logger(__name__)


class JSONExporter:
    """Handles exporting scraping results to JSON format."""

    @staticmethod
    def export(result: ScrapingResult, filepath: Path) -> None:
        """
        Export the scraping result to a JSON file.

        Args:
            result: ScrapingResult to export
            filepath: Path to save the JSON file
        """
        # Create parent directory if it doesn't exist
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Convert result to dictionary
        data = result.to_dict()

        # Write to file
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Exported {result.film_count} films to {filepath}")

    @staticmethod
    def export_to_default_location(result: ScrapingResult, output_dir: Path) -> Path:
        """
        Export to a timestamped file in the output directory.

        Args:
            result: ScrapingResult to export
            output_dir: Base output directory

        Returns:
            Path to the created file
        """
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"letterboxd_films_{result.source}_{timestamp}.json"
        filepath = output_dir / filename

        JSONExporter.export(result, filepath)
        return filepath
