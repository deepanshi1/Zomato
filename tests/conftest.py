import json

import pytest

from app.catalog import Catalog


def restaurant(id, name, *, locality="Banashankari", cuisines=("italian",), cost=600,
               rating=4.2, votes=100, rest_type=("Casual Dining",)):
    return {
        "id": id,
        "name": name,
        "address": f"{name} Road, {locality}",
        "locality": locality,
        "listed_city": locality,
        "cuisines": list(cuisines),
        "rest_type": list(rest_type),
        "cost_for_two": cost,
        "rating": rating,
        "votes": votes,
        "online_order": True,
        "book_table": False,
        "dish_liked": ["Pasta"],
        "review_excerpt": f"Good food at {name}.",
        "url": f"https://www.zomato.com/bangalore/{id}",
    }


FIXTURE_ROWS = [
    # Banashankari, Italian, medium budget
    restaurant("it-best", "Onesta", rating=4.6, votes=2600, cuisines=("pizza", "cafe", "italian")),
    restaurant("it-tie-more-votes", "Pasta Street", rating=4.3, votes=900),
    restaurant("it-tie-fewer-votes", "Little Italy", rating=4.3, votes=150),
    restaurant("it-exact-min", "Roma", rating=4.0, votes=40),
    restaurant("it-below-min", "Trattoria", rating=3.9, votes=500),
    restaurant("it-null-rating", "New Pizzeria", rating=None, votes=0),
    restaurant("it-null-cost", "Mystery Pizza", cost=None, rating=4.8, votes=300),
    # Budget boundaries, Banashankari Italian
    restaurant("it-cost-400", "Slice 400", cost=400, rating=4.1),
    restaurant("it-cost-401", "Slice 401", cost=401, rating=4.1),
    restaurant("it-cost-800", "Slice 800", cost=800, rating=4.1),
    restaurant("it-cost-801", "Slice 801", cost=801, rating=4.1),
    # Other cuisines in Banashankari
    restaurant("ni", "Jalsa", cuisines=("north indian", "mughlai", "chinese"), rating=4.1, votes=775),
    restaurant("si", "Udupi Upahar", cuisines=("south indian",), cost=200, rating=4.4, votes=300),
    # Other localities
    restaurant("jn-it", "Jayanagar Italian", locality="Jayanagar", rating=4.9, votes=5000),
]


class FakeModel:
    """Stand-in for app.llm.complete. Never touches the network.

    With `replies`, returns them in order. Without, ranks every candidate in the
    order given, up to max_recommendations, with a short explanation each.
    """

    def __init__(self, replies=None, error=None):
        self.replies = list(replies) if replies is not None else None
        self.error = error
        self.calls = []

    def __call__(self, system, user):
        self.calls.append((system, user))
        if self.error is not None:
            raise self.error
        if self.replies is not None:
            return self.replies.pop(0)
        message = json.loads(user)
        picks = message["candidates"][: message["max_recommendations"]]
        return json.dumps({
            "summary": f"{len(picks)} picks.",
            "recommendations": [
                {"id": c["id"], "rank": i, "explanation": f"{c['name']} fits the request."}
                for i, c in enumerate(picks, start=1)
            ],
        })


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr("app.llm.complete", model)
    return model


@pytest.fixture
def rows():
    return [dict(row) for row in FIXTURE_ROWS]


@pytest.fixture
def catalog(rows):
    return Catalog(rows)
