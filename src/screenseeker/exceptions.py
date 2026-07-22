"""
Custom exception types for ScreenSeeker.

Provides specific exception classes for better error handling and user feedback.
"""


class ScreenSeekerError(Exception):
    """Base exception for all ScreenSeeker errors."""

    pass


class ConfigurationError(ScreenSeekerError):
    """Raised when configuration is invalid or missing."""

    pass


class TMDBAPIError(ScreenSeekerError):
    """Raised when TMDB API requests fail."""

    def __init__(self, message: str, status_code: int = None):
        self.status_code = status_code
        super().__init__(message)


class RateLimitError(TMDBAPIError):
    """Raised when TMDB API rate limit is exceeded."""

    def __init__(self, message: str = "TMDB API rate limit exceeded. Please try again later."):
        super().__init__(message, status_code=429)


class TMDBNotFoundError(TMDBAPIError):
    """Raised when a film is not found on TMDB."""

    def __init__(self, title: str, year: int = None):
        self.title = title
        self.year = year
        message = f"Film not found on TMDB: '{title}'"
        if year:
            message += f" ({year})"
        super().__init__(message, status_code=404)


class DatabaseError(ScreenSeekerError):
    """Raised when database operations fail."""

    pass


class FilmNotFoundError(DatabaseError):
    """Raised when a film is not found in the database."""

    def __init__(self, title: str, year: int = None):
        self.title = title
        self.year = year
        message = f"Film not found in database: '{title}'"
        if year:
            message += f" ({year})"
        message += "\n\nTip: Try searching first with 'screenseeker search <title>'"
        super().__init__(message)


class JobAlreadyRunning(ScreenSeekerError):
    """
    Raised when a job of the same kind is already queued or running.

    Not merely an abuse control: two concurrent syncs race get_or_create_film
    and produce duplicate films.
    """

    def __init__(self, kind: str, job_id: int):
        self.kind = kind
        self.job_id = job_id
        super().__init__(f"A {kind} job is already running (job {job_id}).")


class ScraperError(ScreenSeekerError):
    """Raised when scraping operations fail."""

    pass


class InvalidInputError(ScreenSeekerError):
    """Raised when user input is invalid."""

    pass
