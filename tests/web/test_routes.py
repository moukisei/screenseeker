"""
Route tests.

The point is not that FastAPI works. It is that the grid paginates and sorts in
SQL, that the toggle persists and comes back as a fragment, and that the rules
the plan set - POST-only mutations, docs gated on DEBUG - actually hold.
"""

import pytest

from screenseeker.web.app import create_app
from tests.web.conftest import make_film

HTMX = {"HX-Request": "true"}


class TestGrid:
    def test_renders_films_with_posters(self, client, db):
        make_film(db, title="The Matrix", year=1999, offers=[("FR", "Netflix", "flatrate")])

        response = client.get("/")

        assert response.status_code == 200
        assert "The Matrix" in response.text
        assert "image.tmdb.org" in response.text
        assert "1 offer" in response.text

    def test_empty_library_says_so(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert "Your library is empty" in response.text

    def test_pagination_slices_the_library(self, client, db):
        for i in range(5):
            make_film(db, title=f"Film {i}", tmdb_id=100 + i, added_days_ago=i)

        first = client.get("/?per_page=2&page=1")
        second = client.get("/?per_page=2&page=2")
        third = client.get("/?per_page=2&page=3")

        # date_added descending: Film 0 is newest.
        assert "Film 0" in first.text and "Film 1" in first.text
        assert "Film 2" in second.text and "Film 0" not in second.text
        assert "Film 4" in third.text
        assert "5 films" in first.text
        assert "page 1 of 3" in first.text

    def test_sort_by_year_puts_newest_first(self, client, db):
        make_film(db, title="Old", year=1950, tmdb_id=1)
        make_film(db, title="New", year=2020, tmdb_id=2)

        body = client.get("/?sort=year").text

        assert body.index("New") < body.index("Old")

    def test_unknown_sort_key_is_rejected(self, client):
        assert client.get("/?sort=; DROP TABLE films").status_code == 422

    def test_nonsense_pagination_is_rejected(self, client):
        assert client.get("/?page=0").status_code == 422
        assert client.get("/?per_page=100000").status_code == 422

    def test_htmx_gets_the_fragment_not_the_page(self, client, db):
        make_film(db)

        page = client.get("/")
        fragment = client.get("/", headers=HTMX)

        assert "<!doctype html>" in page.text.lower()
        assert "<!doctype html>" not in fragment.text.lower()
        assert 'id="library"' in fragment.text


class TestDetail:
    def test_shows_the_best_option_in_the_base_country(self, client, db):
        film = make_film(db, offers=[("FR", "Netflix", "flatrate")])

        response = client.get(f"/film/{film.id}")

        assert response.status_code == 200
        assert "Best option" in response.text
        assert "Netflix" in response.text
        # The deep link comes off the persisted offer, not the ranked option.
        assert f"https://example.test/netflix/{film.id}" in response.text

    def test_offer_outside_the_base_country_needs_a_vpn(self, client, db):
        film = make_film(db, offers=[("US", "Netflix", "flatrate")])

        body = client.get(f"/film/{film.id}").text

        assert "Best option" not in body
        assert "VPN needed" in body

    def test_provider_you_do_not_pay_for_is_separated(self, client, db):
        film = make_film(db, offers=[("FR", "Disney Plus", "flatrate")])

        body = client.get(f"/film/{film.id}").text

        assert "not on a subscription you hold" in body
        assert "Nothing on anything you pay for" in body

    def test_missing_film_renders_a_404_page(self, client):
        response = client.get("/film/9999")

        assert response.status_code == 404
        assert "not in your library" in response.text
        assert "text/html" in response.headers["content-type"]


class TestWatchedToggle:
    def test_htmx_toggle_persists_and_returns_the_card(self, client, db):
        film = make_film(db, title="The Matrix")

        response = client.post(f"/film/{film.id}/watched", data={"watched": "true"}, headers=HTMX)

        assert response.status_code == 200
        assert f'id="film-card-{film.id}"' in response.text
        assert "card--watched" in response.text
        # The returned fragment offers the inverse action.
        assert 'value="false"' in response.text

        db.expire_all()
        assert db.get(type(film), film.id).watched is True

    def test_toggle_is_idempotent(self, client, db):
        film = make_film(db, watched=True)

        client.post(f"/film/{film.id}/watched", data={"watched": "true"}, headers=HTMX)

        db.expire_all()
        assert db.get(type(film), film.id).watched is True

    def test_unmarking_clears_the_timestamp(self, client, db):
        film = make_film(db, watched=True)

        client.post(f"/film/{film.id}/watched", data={"watched": "false"}, headers=HTMX)

        db.expire_all()
        refreshed = db.get(type(film), film.id)
        assert refreshed.watched is False
        assert refreshed.watched_at is None

    def test_without_htmx_it_redirects(self, client, db):
        film = make_film(db)

        response = client.post(
            f"/film/{film.id}/watched", data={"watched": "true"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/film/{film.id}"

    def test_get_cannot_mutate(self, client, db):
        film = make_film(db)

        assert client.get(f"/film/{film.id}/watched?watched=true").status_code == 405

        db.expire_all()
        assert db.get(type(film), film.id).watched is False

    def test_missing_film_is_404(self, client):
        response = client.post("/film/9999/watched", data={"watched": "true"}, headers=HTMX)
        assert response.status_code == 404


class TestAppConfiguration:
    @pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
    def test_docs_are_off_unless_debug(self, monkeypatch, path):
        monkeypatch.setattr("screenseeker.settings.DEBUG", False)
        from fastapi.testclient import TestClient

        with TestClient(create_app()) as client:
            assert client.get(path).status_code == 404

    def test_docs_appear_under_debug(self, monkeypatch):
        monkeypatch.setattr("screenseeker.settings.DEBUG", True)
        from fastapi.testclient import TestClient

        with TestClient(create_app()) as client:
            assert client.get("/openapi.json").status_code == 200

    def test_every_mutating_route_requires_a_user(self):
        """
        The auth seam is only worth having if nothing skips it.

        require_user is a no-op, so this asserts the wiring, not a behaviour -
        it fails the day someone adds a POST without the dependency.
        """
        from screenseeker.web.deps import require_user

        app = create_app()
        unguarded = []

        # POST /login cannot require a logged-in user - it is how you log in.
        exempt = {"/login"}

        for route in app.routes:
            methods = getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
            if not methods or route.path in exempt:
                continue
            deps = [d.call for d in getattr(route, "dependant", None).dependencies]
            if require_user not in deps:
                unguarded.append(f"{sorted(methods)} {route.path}")

        assert not unguarded, f"mutating routes without require_user: {unguarded}"


class TestFilters:
    """
    The filters are the URL. A view you cannot link to is not bookmarkable,
    which is the whole point of putting them in query parameters.
    """

    def stock(self, db):
        make_film(db, title="Wanted", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])
        make_film(db, title="Seen", tmdb_id=2, watched=True, offers=[("FR", "Netflix", "flatrate")])
        make_film(db, title="American", tmdb_id=3, offers=[("US", "Netflix", "flatrate")])
        make_film(db, title="Mouse", tmdb_id=4, offers=[("FR", "Disney Plus", "flatrate")])

    def test_the_worked_example_is_one_url(self, client, db):
        self.stock(db)

        body = client.get("/?watched=false&provider=Netflix&country=FR&offer_type=flatrate").text

        assert "Wanted" in body
        assert "Seen" not in body
        assert "American" not in body
        assert "Mouse" not in body
        assert "1 film" in body

    def test_the_form_reflects_the_url_it_was_loaded_from(self, client, db):
        self.stock(db)

        body = client.get("/?provider=Netflix&country=FR&watched=false").text

        assert 'value="Netflix"' in body
        assert '<option value="FR" selected>' in body
        assert 'value="false" selected' in body
        assert "Clear" in body

    def test_no_filters_means_no_clear_link(self, client, db):
        self.stock(db)

        assert ">Clear<" not in client.get("/").text

    def test_pagination_links_keep_the_filters(self, client, db):
        for i in range(6):
            make_film(db, title=f"Film {i}", tmdb_id=10 + i, offers=[("FR", "Netflix", "flatrate")])

        body = client.get("/?provider=Netflix&country=FR&per_page=2").text

        # Losing a filter on page two would silently widen the result set.
        assert "provider=Netflix" in body
        assert "country=FR" in body
        assert "page=2" in body

    def test_a_filter_that_matches_nothing_says_so(self, client, db):
        self.stock(db)

        body = client.get("/?provider=Mubi").text

        assert "Nothing matches" in body
        assert "0 films" in body

    def test_an_invalid_offer_type_is_rejected(self, client):
        assert client.get("/?offer_type=free_beer").status_code == 422

    def test_an_invalid_country_code_is_rejected(self, client):
        assert client.get("/?country=FRANCE").status_code == 422

    def test_confidence_is_a_sort_the_ui_offers(self, client, db):
        self.stock(db)

        assert client.get("/?sort=confidence").status_code == 200


class TestDetailScoping:
    def test_only_reachable_countries_are_loaded(self, client, db):
        """
        TMDB reports 139 countries. The profile reaches FR, US and GB, so the
        other offers are weight on every render for no information.
        """
        film = make_film(
            db,
            offers=[
                ("FR", "Netflix", "flatrate"),
                ("US", "Netflix", "flatrate"),
                ("JP", "Netflix", "flatrate"),
                ("BR", "Netflix", "flatrate"),
            ],
        )

        body = client.get(f"/film/{film.id}").text

        assert "Best option" in body
        assert "Japan" not in body and ">JP<" not in body
        # And the page admits it is showing a subset.
        assert "Showing 2 of 4 offers" in body

    def test_a_film_within_reach_says_nothing_about_scoping(self, client, db):
        film = make_film(db, offers=[("FR", "Netflix", "flatrate")])

        assert "Showing" not in client.get(f"/film/{film.id}").text
