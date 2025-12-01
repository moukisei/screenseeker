import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.session import get_database_info, init_db
from logger import get_logger, setup_logger

# Setup logger
setup_logger(level="INFO", log_to_file=False, use_colors=True)
logger = get_logger(__name__)


def main():
    """Initialize the database."""
    logger.info("Starting database initialization...")

    try:
        # Initialize database
        init_db()

        # Show database info
        info = get_database_info()
        logger.info("\nDatabase Information:")
        logger.info(f"  Location: {info['path']}")
        logger.info(f"  Status: {'Exists' if info['exists'] else 'Created'}")

        if info.get("size_mb"):
            logger.info(f"  Size: {info['size_mb']} MB")

        if info.get("film_count") is not None:
            logger.info(f"  Films: {info['film_count']}")
            logger.info(f"  Streaming Offers: {info['offer_count']}")

        logger.info("\nDatabase is ready!")
        return 0

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
