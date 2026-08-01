"""
Route tests for the household.

Members are watchlist sources, not logins, so what is worth checking is that
adding and removing them behaves, that the grid's member filter survives a URL
round-trip (both spellings), and that the chips appear only when there is more
than one person to tell apart.
"""

from screenseeker.database.models import Film, Member
from screenseeker.services.library import record_entry
from screenseeker.services.members import create_member
from tests.web.conftest import make_film

HTMX = {"HX-Request": "true"}


def add_member(db, username, display_name="", films=()):
    """A member plus the films on their watchlist."""
    member = create_member(db, username, display_name=display_name)
    for film in films:
        record_entry(db, member.id, film)
    db.commit()
    return member


class TestMemberEditor:
    def test_the_profile_page_lists_the_household(self, client, db):
        add_member(db, "alice", "Alice")
        add_member(db, "bob", "Bob")

        response = client.get("/profile")

        assert response.status_code == 200
        assert "Alice" in response.text
        assert "letterboxd.com/bob/" in response.text

    def test_adding_a_member(self, client, db):
        response = client.post("/members", data={"username": "alice", "display_name": "Alice"})

        assert response.status_code == 200  # after the redirect
        assert db.query(Member).count() == 1
        assert db.query(Member).one().display_name == "Alice"

    def test_a_pasted_profile_url_works(self, client, db):
        client.post("/members", data={"username": "https://letterboxd.com/alice/watchlist/"})

        assert db.query(Member).one().letterboxd_username == "alice"

    def test_a_bad_username_comes_back_as_a_message(self, client, db):
        """Not a 422: the profile page should say what is wrong and stay usable."""
        response = client.post("/members", data={"username": "not a username"})

        assert response.status_code == 200
        assert "not a Letterboxd username" in response.text
        assert db.query(Member).count() == 0

    def test_a_duplicate_account_is_refused(self, client, db):
        add_member(db, "alice")

        response = client.post("/members", data={"username": "alice"})

        assert "already in the household" in response.text
        assert db.query(Member).count() == 1

    def test_renaming_and_pausing(self, client, db):
        alice = add_member(db, "alice", "Alice")

        client.post(f"/members/{alice.id}", data={"display_name": "Alice B", "color": "#123456"})

        db.expire_all()
        stored = db.query(Member).one()
        assert stored.display_name == "Alice B"
        assert stored.color == "#123456"
        # The checkbox submitted nothing, which means paused.
        assert stored.active is False

    def test_the_sync_checkbox_keeps_a_member_active(self, client, db):
        alice = add_member(db, "alice", "Alice")

        client.post(f"/members/{alice.id}", data={"display_name": "Alice", "active": "on"})

        db.expire_all()
        assert db.query(Member).one().active is True

    def test_removing_a_member_takes_their_orphaned_films(self, client, db):
        film = make_film(db, title="Solaris", tmdb_id=1)
        alice = add_member(db, "alice", films=[film])

        client.post(f"/members/{alice.id}/delete")

        assert db.query(Member).count() == 0
        assert db.query(Film).count() == 0

    def test_removing_a_member_keeps_films_someone_else_wants(self, client, db):
        film = make_film(db, title="Heat", tmdb_id=2)
        alice = add_member(db, "alice", films=[film])
        add_member(db, "bob", films=[film])

        client.post(f"/members/{alice.id}/delete")

        assert db.query(Film).count() == 1

    def test_editing_an_unknown_member_is_a_404(self, client):
        assert client.post("/members/999", data={"display_name": "Ghost"}).status_code == 404
        assert client.post("/members/999/delete").status_code == 404


class TestMemberFilter:
    def test_the_control_is_hidden_for_a_one_person_household(self, client, db):
        """It could only narrow to what is already on screen."""
        add_member(db, "alice", "Alice", films=[make_film(db, title="Heat", tmdb_id=1)])

        response = client.get("/")

        assert "Wanted by" not in response.text

    def test_filtering_by_one_member(self, client, db):
        hers = make_film(db, title="Solaris", tmdb_id=1)
        his = make_film(db, title="Heat", tmdb_id=2)
        alice = add_member(db, "alice", "Alice", films=[hers])
        add_member(db, "bob", "Bob", films=[his])

        response = client.get(f"/?members={alice.id}")

        assert "Solaris" in response.text
        assert "Heat" not in response.text

    def test_repeated_and_comma_joined_spellings_agree(self, client, db):
        """
        The form submits `members=1&members=2`; pager links carry `members=1,2`.
        A view that changed when you paged would be the bug.
        """
        shared = make_film(db, title="Casino", tmdb_id=1)
        alice = add_member(db, "alice", "Alice", films=[shared])
        bob = add_member(db, "bob", "Bob", films=[shared])

        repeated = client.get(f"/?members={alice.id}&members={bob.id}&member_match=all")
        joined = client.get(f"/?members={alice.id},{bob.id}&member_match=all")

        assert "Casino" in repeated.text
        assert "Casino" in joined.text

    def test_all_of_them_is_the_intersection(self, client, db):
        shared = make_film(db, title="Casino", tmdb_id=1)
        hers = make_film(db, title="Solaris", tmdb_id=2)
        alice = add_member(db, "alice", "Alice", films=[shared, hers])
        bob = add_member(db, "bob", "Bob", films=[shared])

        response = client.get(f"/?members={alice.id},{bob.id}&member_match=all")

        assert "Casino" in response.text
        assert "Solaris" not in response.text

    def test_a_stale_bookmark_still_renders(self, client, db):
        """
        A member who has left the household should not turn every saved link
        into a 422.
        """
        add_member(db, "alice", "Alice", films=[make_film(db, title="Heat", tmdb_id=1)])

        response = client.get("/?members=abc")

        assert response.status_code == 200
        assert "Heat" in response.text

    def test_the_filter_survives_paging(self, client, db):
        alice = add_member(db, "alice", "Alice")
        for i in range(3):
            record_entry(db, alice.id, make_film(db, title=f"Hers {i}", tmdb_id=100 + i))
        add_member(db, "bob", "Bob", films=[make_film(db, title="His", tmdb_id=200)])
        db.commit()

        page_two = client.get(f"/?members={alice.id}&per_page=2&page=2")

        assert page_two.status_code == 200
        assert "His" not in page_two.text

    def test_most_wanted_sorts_consensus_first(self, client, db):
        alone = make_film(db, title="Solaris", tmdb_id=1, rating=9.9)
        together = make_film(db, title="Casino", tmdb_id=2, rating=1.0)
        add_member(db, "alice", "Alice", films=[alone, together])
        add_member(db, "bob", "Bob", films=[together])

        response = client.get("/?sort=wanted")

        assert response.text.index("Casino") < response.text.index("Solaris")


class TestChips:
    def test_cards_show_who_wants_the_film(self, client, db):
        film = make_film(db, title="Casino", tmdb_id=1)
        add_member(db, "alice", "Alice", films=[film])
        add_member(db, "bob", "Bob Smith", films=[film])

        response = client.get("/")

        assert "Wanted by Alice, Bob Smith" in response.text

    def test_no_chips_when_there_is_only_one_person(self, client, db):
        """The same chip on every card carries no information."""
        add_member(db, "alice", "Alice", films=[make_film(db, title="Casino", tmdb_id=1)])

        response = client.get("/")

        assert "Wanted by" not in response.text

    def test_the_watched_toggle_returns_a_card_with_its_chips(self, client, db):
        film = make_film(db, title="Casino", tmdb_id=1)
        add_member(db, "alice", "Alice", films=[film])
        add_member(db, "bob", "Bob", films=[film])

        response = client.post(f"/film/{film.id}/watched", data={"watched": "true"}, headers=HTMX)

        assert response.status_code == 200
        assert "Wanted by Alice, Bob" in response.text

    def test_the_detail_page_names_the_owners(self, client, db):
        film = make_film(db, title="Casino", tmdb_id=1)
        add_member(db, "alice", "Alice", films=[film])

        response = client.get(f"/film/{film.id}")

        assert "On the watchlist of" in response.text
        assert "Alice" in response.text
