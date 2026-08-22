"""
Route tests.

The point is not that FastAPI works. It is that the grid paginates and sorts in
SQL, that the toggle persists and comes back as a fragment, and that the rules
the plan set - POST-only mutations, docs gated on DEBUG - actually hold.
"""

import pytest

from screenseeker.services.members import create_member
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
        # A direct watch link is shown on its own - the redundant offer-count
        # badge only appears when there is no such link.
        assert "badge--best" in response.text
        assert "Netflix" in response.text
        assert "1 offer" not in response.text

    def test_an_empty_library_with_nobody_in_it_says_who_to_add(self, client):
        """Nothing to sync is the more common first run than nothing synced."""
        response = client.get("/")

        assert response.status_code == 200
        assert "Nobody in the household yet" in response.text

    def test_an_empty_library_with_a_member_says_to_sync(self, client, db):
        create_member(db, "alice", display_name="Alice")
        db.commit()

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

    def test_direction_can_be_flipped(self, client, db):
        make_film(db, title="Old", year=1950, tmdb_id=1)
        make_film(db, title="New", year=2020, tmdb_id=2)

        desc = client.get("/?sort=year&direction=desc").text
        asc = client.get("/?sort=year&direction=asc").text

        assert desc.index("New") < desc.index("Old")
        assert asc.index("Old") < asc.index("New")

    def test_unknown_direction_is_rejected(self, client):
        assert client.get("/?sort=year&direction=sideways").status_code == 422

    def test_the_order_select_reflects_the_resolved_direction(self, client, db):
        """
        An unset direction still has to render as *some* selected option -
        the one `sort` reads naturally in, not an unselected dropdown.
        """
        body = client.get("/?sort=title").text

        assert 'value="asc" selected' in body

    def test_nonsense_pagination_is_rejected(self, client):
        assert client.get("/?page=0").status_code == 422
        assert client.get("/?per_page=100000").status_code == 422

    def test_htmx_gets_the_results_fragment_not_the_page(self, client, db):
        make_film(db, title="The Matrix")

        page = client.get("/")
        fragment = client.get("/", headers=HTMX)

        # Full page carries the form and the doctype; the fragment is the
        # results region alone, so the filter form is never re-rendered.
        assert "<!doctype html>" in page.text.lower()
        assert "<!doctype html>" not in fragment.text.lower()
        assert 'class="filters"' in page.text
        assert 'class="filters"' not in fragment.text
        assert "The Matrix" in fragment.text


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


class TestWatchedIsGone:
    """
    The watched flag was a second source of truth for what Letterboxd already
    records. Logging a film there takes it off the watchlist, the next sync
    retires the entry, and the film leaves the library on its own.
    """

    def test_the_toggle_route_no_longer_exists(self, client, db):
        film = make_film(db)

        assert client.post(f"/film/{film.id}/watched", data={"watched": "true"}).status_code == 404

    def test_the_grid_offers_no_watched_filter(self, client, db):
        make_film(db, title="The Matrix")

        body = client.get("/").text

        assert 'name="watched"' not in body
        assert "Mark watched" not in body

    def test_an_old_bookmark_carrying_the_filter_still_loads(self, client, db):
        """
        FastAPI ignores query parameters it does not declare, so a saved
        `?watched=false` URL renders the grid rather than 422-ing. Widening
        silently beats a dead link for a bookmark somebody kept.
        """
        make_film(db, title="The Matrix")

        response = client.get("/?watched=false")

        assert response.status_code == 200
        assert "The Matrix" in response.text


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
        make_film(db, title="Dropped", tmdb_id=2, owners=(), offers=[("FR", "Netflix", "flatrate")])
        make_film(db, title="American", tmdb_id=3, offers=[("US", "Netflix", "flatrate")])
        make_film(db, title="Mouse", tmdb_id=4, offers=[("FR", "Disney Plus", "flatrate")])

    def test_the_worked_example_is_one_url(self, client, db):
        self.stock(db)

        body = client.get("/?provider=Netflix&country=FR&offer_type=flatrate").text

        assert "Wanted" in body
        # Matches every filter, but nobody lists it any more.
        assert "Dropped" not in body
        assert "American" not in body
        assert "Mouse" not in body
        assert "1 film" in body

    def test_the_form_reflects_the_url_it_was_loaded_from(self, client, db):
        self.stock(db)

        body = client.get("/?provider=Netflix&country=FR&offer_type=flatrate").text

        assert 'value="Netflix"' in body
        assert '<option value="FR" selected>' in body
        assert '<option value="flatrate" selected>' in body
        assert "Clear" in body

    def test_no_filters_means_no_clear_link(self, client, db):
        self.stock(db)

        assert ">Clear<" not in client.get("/").text

    def test_more_filters_is_collapsed_with_neither_set(self, client, db):
        self.stock(db)

        body = client.get("/").text

        assert '<details class="filters__more" >' in body

    def test_more_filters_opens_when_country_or_offer_came_from_the_url(self, client, db):
        """
        A bookmarked or shared link that filtered by country should not look
        like it silently stopped filtering just because the control is
        tucked away by default.
        """
        self.stock(db)

        by_country = client.get("/?country=FR").text
        by_offer = client.get("/?offer_type=flatrate").text

        assert '<details class="filters__more" open>' in by_country
        assert '<details class="filters__more" open>' in by_offer

    def test_provider_picker_splits_owned_from_other(self, client, db):
        """
        The default `profile` fixture holds only Netflix. Disney Plus shows
        up in the library (someone's watchlist has it), but the household
        does not pay for it, so it belongs in the "other" group, after and
        separate from what they actually own.
        """
        self.stock(db)

        body = client.get("/").text
        suggestions = body[body.index("data-provider-list") : body.index("</ul>")]

        assert "Your subscriptions" in suggestions
        assert "Other providers" in suggestions
        assert suggestions.index("Your subscriptions") < suggestions.index("Netflix")
        assert suggestions.index("Netflix") < suggestions.index("Other providers")
        assert suggestions.index("Other providers") < suggestions.index("Disney Plus")

    def test_provider_picker_has_one_group_when_nothing_is_owned(
        self, client, db, sessions, profile
    ):
        """A profile with no subscriptions has nothing to call "yours"."""
        make_film(db, title="Mouse", tmdb_id=1, offers=[("FR", "Disney Plus", "flatrate")])
        profile["subscriptions"] = []

        body = client.get("/").text
        suggestions = body[body.index("data-provider-list") : body.index("</ul>")]

        assert "Your subscriptions" not in suggestions
        assert "Other providers" not in suggestions
        assert "Disney Plus" in suggestions

    def test_search_narrows_by_title(self, client, db):
        make_film(db, title="The Matrix", tmdb_id=1)
        make_film(db, title="Casino", tmdb_id=2)

        body = client.get("/?query=matrix").text

        assert "The Matrix" in body
        assert "Casino" not in body
        # The box keeps what was searched, so the URL and the field agree.
        assert 'value="matrix"' in body

    def test_the_form_serialises_every_empty_field_without_a_422(self, client, db):
        # The grid form sends every control on each keystroke, so its empty
        # selects arrive as country=&offer_type=&member_match=. min_length and
        # the enums each reject "", which 422'd the whole form and made the
        # search box look dead. A blank field must read as "no filter".
        make_film(db, title="The Matrix", tmdb_id=1)

        r = client.get(
            "/?per_page=48&query=matr&provider=&country=&offer_type=&member_match=&sort=added",
            headers={"HX-Request": "true"},
        )

        assert r.status_code == 200
        assert "The Matrix" in r.text

    def test_search_composes_with_a_filter_in_the_url(self, client, db):
        make_film(db, title="The Matrix", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])
        make_film(db, title="The Matrix Revisited", tmdb_id=2)

        body = client.get("/?query=matrix&provider=Netflix").text

        assert "The Matrix<" in body or "The Matrix</a>" in body
        assert "Revisited" not in body

    def test_blank_search_is_not_a_filter(self, client, db):
        make_film(db, title="Heat", tmdb_id=1)

        # A submitted-but-empty box must not read as an active filter.
        body = client.get("/?query=").text
        assert "Heat" in body
        assert ">Clear<" not in body

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


class TestCardExtras:
    def test_library_card_shows_a_deep_linked_tonight_badge(self, client, db):
        # The default `profile` fixture is Netflix, VPN everywhere, base FR.
        film = make_film(db, title="Watchable", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])

        body = client.get("/").text

        assert "badge--best" in body
        assert "Netflix" in body
        assert f"https://example.test/netflix/{film.id}" in body

    def test_a_film_you_cannot_watch_tonight_has_no_badge(self, client, db):
        make_film(db, title="Abroad", tmdb_id=1, offers=[("US", "Netflix", "flatrate")])

        assert "badge--best" not in client.get("/").text

    def test_a_watchable_card_is_tinted_the_providers_own_colour(self, client, db):
        """
        --fill is set once on the card article and inherited by the badge and
        its logo fallback - a card with a direct watch link should carry the
        card--marked class and the provider's colour as that custom property,
        not just show it on the small badge.
        """
        make_film(db, title="Watchable", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])

        body = client.get("/").text

        assert "card--marked" in body
        assert "--fill: #E50914" in body  # Netflix's mapped colour.

    def test_an_unwatchable_card_is_not_tinted(self, client, db):
        make_film(db, title="Abroad", tmdb_id=1, offers=[("US", "Netflix", "flatrate")])

        assert "card--marked" not in client.get("/").text

    def test_badge_shows_the_provider_logo_when_tmdb_has_one(self, client, db):
        make_film(db, title="Watchable", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])

        body = client.get("/").text

        assert '<img class="badge__logo"' in body
        assert "logo.jpg" in body

    def test_badge_falls_back_to_an_initial_letter_when_tmdb_has_no_logo(self, client, db):
        """
        TMDB does not supply a logo for every provider. Two providers whose
        colour happens to collide (Canal+ and Apple TV+ are both black) are
        still told apart by the letter inside this fallback chip, not by
        colour alone.
        """
        from datetime import UTC, datetime

        from screenseeker.database.models import StreamingOffer

        film = make_film(db, title="Watchable", tmdb_id=1, offers=())
        db.add(
            StreamingOffer(
                film_id=film.id,
                country_code="FR",
                country_name="France",
                provider_id=8,
                provider_name="Netflix",
                monetization_type="flatrate",
                streaming_url=f"https://example.test/netflix/{film.id}",
                logo_path=None,
                checked_at=datetime.now(UTC),
            )
        )
        db.commit()

        body = client.get("/").text

        assert '<img class="badge__logo"' not in body
        assert "badge__logo--blank" in body
        assert "--fill:" in body

    def test_a_card_shows_the_runtime_when_known(self, client, db):
        make_film(db, title="Long", tmdb_id=1, runtime=125)

        assert "2h 5m" in client.get("/").text

    def test_a_card_omits_the_runtime_when_unknown(self, client, db):
        # A film not yet enriched has no runtime; the "2h" unit never appears.
        make_film(db, title="Fresh", tmdb_id=1, rating=None, runtime=None)

        body = client.get("/").text
        assert "Fresh" in body
        assert "h " not in body[body.index("Fresh") : body.index("Fresh") + 100]

    def test_a_watchable_card_carries_the_tonight_badge(self, client, db):
        make_film(db, title="Watchable", tmdb_id=1, offers=[("FR", "Netflix", "flatrate")])

        body = client.get("/").text
        assert "badge--best" in body
        assert "Netflix" in body


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
