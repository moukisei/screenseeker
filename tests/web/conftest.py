"""
Fixtures for the web layer.

The database is a file in tmp_path rather than :memory: - TestClient runs sync
routes in a worker thread, and an in-memory SQLite engine hands each thread its
own empty database.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from screenseeker.database.models import Base, Film, StreamingOffer
from screenseeker.web.app import create_app
from screenseeker.web.deps import get_db, get_profile


@pytest.fixture
def web_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'web.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def sessions(web_engine):
    return sessionmaker(bind=web_engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(sessions):
    """A session for arranging data. Separate from the one the request uses."""
    session = sessions()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def profile():
    """Netflix, VPN-enabled everywhere, based in FR."""
    return {
        "base_country": "FR",
        "subscriptions": [
            {
                "provider_names": ["Netflix"],
                "vpn_enabled": True,
                "available_countries": "all",
            }
        ],
        "vpn_country_priority": ["US", "GB"],
        "max_vpn_suggestions": 3,
    }


@pytest.fixture
def client(sessions, profile):
    app = create_app()

    def override_db():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_profile] = lambda: profile

    with TestClient(app) as test_client:
        yield test_client


def make_film(
    session,
    title="The Matrix",
    year=1999,
    tmdb_id=603,
    rating=8.7,
    watched=False,
    checked_days_ago=0,
    added_days_ago=0,
    offers=(),
):
    """
    Insert a film. `offers` is a list of (country, provider, offer_type).

    checked_days_ago=None leaves last_checked unset, which is how a film that
    sync added but refresh has never seen looks.
    """
    now = datetime.now(UTC)
    film = Film(
        letterboxd_title=title,
        letterboxd_year=year,
        tmdb_id=tmdb_id,
        tmdb_title=title,
        tmdb_year=year,
        poster_path="/poster.jpg",
        overview=f"{title} is a film.",
        vote_average=rating,
        match_confidence="exact",
        date_added=now - timedelta(days=added_days_ago),
        last_checked=None if checked_days_ago is None else now - timedelta(days=checked_days_ago),
        watched=watched,
    )
    session.add(film)
    session.flush()

    for i, (country, provider, offer_type) in enumerate(offers):
        session.add(
            StreamingOffer(
                film_id=film.id,
                country_code=country,
                country_name={"FR": "France", "US": "United States"}.get(country, country),
                provider_id=8 + i,
                provider_name=provider,
                monetization_type=offer_type,
                streaming_url=f"https://example.test/{provider.lower()}/{film.id}",
                logo_path="/logo.jpg",
                checked_at=now,
            )
        )

    session.commit()
    return film
