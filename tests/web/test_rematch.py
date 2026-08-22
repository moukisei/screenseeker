"""
The "wrong TMDB match" correction flow on the film detail page.

Only the TMDB client is faked - everything else (the route, the service
layer, the DB write) is real.
"""

import pytest

from screenseeker.enrichers.enrichment_models import EnrichmentResult
from screenseeker.enrichers.enrichment_models import StreamingOffer as Offer
from screenseeker.enrichers.enrichment_models import TMDBMovieInfo
from tests.web.conftest import make_film

FAKE_CFG = {"tmdb": {"api_key": "not-a-real-key", "rate_limit": 5.0, "language": "en-US"}}


class FakeEnricher:
    """
    Stands in for TMDBEnricher, for just the two calls the correction flow
    makes: search for candidates, then fetch one by id.
    """

    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def search_candidates(self, title, year=None, limit=6):
        self.calls.append(("search", title, year))
        return [
            TMDBMovieInfo(tmdb_id=101, title="The Matrix", year=1999, poster_path="/a.jpg"),
            TMDBMovieInfo(
                tmdb_id=102, title="The Matrix Reloaded", year=2003, poster_path="/b.jpg"
            ),
        ]

    def enrich_by_id(self, tmdb_id):
        self.calls.append(("enrich_by_id", tmdb_id))
        if tmdb_id == 999:
            return EnrichmentResult(
                query_title="999",
                match_confidence="none",
                success=False,
                error_message="TMDB has no movie with id 999.",
            )
        return EnrichmentResult(
            query_title="The Matrix Reloaded",
            query_year=2003,
            tmdb_movie=TMDBMovieInfo(
                tmdb_id=tmdb_id,
                title="The Matrix Reloaded",
                year=2003,
                release_date="2003-05-15",
                overview="Neo goes further down the rabbit hole.",
                poster_path="/reloaded.jpg",
                vote_average=7.2,
            ),
            match_confidence="exact",
            streaming_offers=[
                Offer(
                    country_code="FR",
                    country_name="France",
                    provider_id=9,
                    provider_name="Max",
                    offer_type="flatrate",
                    logo_path="/max.jpg",
                )
            ],
            success=True,
        )


@pytest.fixture
def fake_tmdb(monkeypatch):
    enricher = FakeEnricher()
    monkeypatch.setattr("screenseeker.user_config.load_config", lambda: FAKE_CFG)
    monkeypatch.setattr("screenseeker.web.routes.build_enricher", lambda cfg: enricher)
    return enricher


class TestSearch:
    def test_returns_candidates(self, client, db, fake_tmdb):
        film = make_film(db, title="The Matrix", year=1999)

        response = client.get(
            f"/film/{film.id}/rematch", params={"query": "The Matrix", "year": 1999}
        )

        assert response.status_code == 200
        assert "The Matrix Reloaded" in response.text
        assert "(2003)" in response.text
        assert fake_tmdb.calls == [("search", "The Matrix", 1999)]

    def test_no_configured_tmdb_shows_a_message_not_a_500(self, client, db, monkeypatch):
        film = make_film(db)
        monkeypatch.setattr("screenseeker.user_config.load_config", lambda: {})

        response = client.get(f"/film/{film.id}/rematch", params={"query": "The Matrix"})

        assert response.status_code == 200
        assert "not configured" in response.text


class TestApply:
    def test_points_the_film_at_the_chosen_match(self, client, db, fake_tmdb):
        film = make_film(db, title="The Matrix", year=1999, tmdb_id=603)

        response = client.post(
            f"/film/{film.id}/rematch", data={"tmdb_id": 102}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/film/{film.id}?rematched=1"

        # The Letterboxd title stays put - it's what `sync` matches this row
        # against on the real watchlist, and changing it would desync the
        # next scrape. What corrects is everything TMDB supplies: poster,
        # overview, runtime and offers.
        detail = client.get(f"/film/{film.id}")
        assert "The Matrix" in detail.text
        assert "reloaded.jpg" in detail.text
        assert "Neo goes further down the rabbit hole." in detail.text
        assert "Max" in detail.text

        db.refresh(film)
        assert film.tmdb_id == 102
        assert film.letterboxd_title == "The Matrix"

    def test_unknown_tmdb_id_redirects_with_an_error_and_leaves_the_film_alone(
        self, client, db, fake_tmdb
    ):
        film = make_film(db, title="The Matrix", year=1999, tmdb_id=603)

        response = client.post(
            f"/film/{film.id}/rematch", data={"tmdb_id": 999}, follow_redirects=False
        )

        assert response.status_code == 303
        assert "rematch_error" in response.headers["location"]

        detail = client.get(f"/film/{film.id}")
        assert "The Matrix" in detail.text
        assert "The Matrix Reloaded" not in detail.text

    def test_unknown_film_404s(self, client, fake_tmdb):
        response = client.post("/film/999999/rematch", data={"tmdb_id": 102})

        assert response.status_code == 404
