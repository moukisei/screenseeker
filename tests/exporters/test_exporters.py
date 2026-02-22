"""
Tests for exporters.
"""

import json

from screenseeker.exporters.json_exporter import JSONExporter
from screenseeker.models import Film, ScrapingResult


class TestJSONExporter:
    """Test JSON exporter functionality."""

    def test_export_creates_file(self, tmp_path):
        """Test that export creates a JSON file."""

        films = [
            Film(
                film_title="Test Movie 1",
                year=2020,
                film_full_title="Test Movie 1 (2020)",
                date_added="2024-01-01",
            ),
            Film(
                film_title="Test Movie 2",
                year=2021,
                film_full_title="Test Movie 2 (2021)",
                date_added="2024-01-02",
            ),
        ]

        result = ScrapingResult(
            success=True, films=films, film_count=2, source="test", error_message=None
        )

        filepath = tmp_path / "test_export.json"

        JSONExporter.export(result, filepath)

        # File should exist
        assert filepath.exists()

        # File should contain valid JSON
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["success"] is True
        assert data["total_films"] == 2
        assert len(data["films"]) == 2
        assert data["films"][0]["film_title"] == "Test Movie 1"

    def test_export_creates_parent_directory(self, tmp_path):
        """Test that export creates parent directories if needed."""
        result = ScrapingResult(
            success=True,
            films=[
                Film(
                    film_title="Test",
                    year=2020,
                    film_full_title="Test (2020)",
                    date_added="2024-01-01",
                )
            ],
            film_count=1,
            source="test",
            error_message=None,
        )

        # Create path with non-existent parent directories
        filepath = tmp_path / "nested" / "directories" / "test.json"

        JSONExporter.export(result, filepath)

        # File should exist
        assert filepath.exists()

    def test_export_to_default_location(self, tmp_path):
        """Test export_to_default_location creates timestamped file."""
        result = ScrapingResult(
            success=True,
            films=[
                Film(
                    film_title="Test",
                    year=2020,
                    film_full_title="Test (2020)",
                    date_added="2024-01-01",
                )
            ],
            film_count=1,
            source="csv",
            error_message=None,
        )

        filepath = JSONExporter.export_to_default_location(result, tmp_path)

        # File should exist
        assert filepath.exists()

        # Filename should contain source
        assert "csv" in filepath.name
        assert filepath.name.startswith("letterboxd_films_")
        assert filepath.name.endswith(".json")

        # File should contain valid JSON
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["total_films"] == 1

    def test_export_with_unicode(self, tmp_path):
        """Test that export handles Unicode characters properly."""
        result = ScrapingResult(
            success=True,
            films=[
                Film(
                    film_title="Le Fabuleux Destin d'Amélie Poulain",
                    year=2001,
                    film_full_title="Le Fabuleux Destin d'Amélie Poulain (2001)",
                    date_added="2024-01-01",
                )
            ],
            film_count=1,
            source="test",
            error_message=None,
        )

        filepath = tmp_path / "unicode_test.json"

        JSONExporter.export(result, filepath)

        # Read and verify Unicode is preserved
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["films"][0]["film_title"] == "Le Fabuleux Destin d'Amélie Poulain"
