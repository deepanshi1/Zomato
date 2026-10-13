import json

import pytest

from ingest.build_catalog import (
    EXCERPT_MAX_CHARS,
    build_catalog,
    build_facets,
    make_id,
    parse_cost,
    parse_rating,
    parse_reviews,
    pick_excerpt,
    repair_text,
    split_list,
)


def raw_row(**overrides):
    row = {
        "name": "Jalsa",
        "address": "942, 21st Main Road, Banashankari, Bangalore",
        "location": "Banashankari",
        "listed_in(city)": "Banashankari",
        "cuisines": "North Indian, Mughlai, Chinese",
        "rest_type": "Casual Dining",
        "approx_cost(for two people)": "800",
        "rate": "4.1/5",
        "votes": 775,
        "online_order": "Yes",
        "book_table": "Yes",
        "dish_liked": "Pasta, Lunch Buffet, Masala Papad",
        "reviews_list": "[('Rated 4.0', 'RATED\\n  A beautiful place to dine in.')]",
        "url": "https://www.zomato.com/bangalore/jalsa-banashankari",
        "phone": "080 42297555",
        "menu_item": "[]",
    }
    row.update(overrides)
    return row


# --- rating ---------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ("4.1/5", 4.1),
        (" 4.1 /5 ", 4.1),
        ("4.1", 4.1),
        ("0/5", 0.0),
        ("NEW", None),
        ("-", None),
        ("", None),
        (None, None),
        ("6.0/5", None),
        ("8/10", None),
    ],
)
def test_parse_rating(value, expected):
    assert parse_rating(value) == expected


# --- cost -----------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ("1,000", 1000),
        ("1,00,000", 100000),
        ("450", 450),
        ("450.0", 450),
        (" 300 ", 300),
        ("", None),
        (None, None),
        ("abc", None),
        ("0", None),
        ("-50", None),
    ],
)
def test_parse_cost(value, expected):
    assert parse_cost(value) == expected


# --- lists ----------------------------------------------------------------

def test_cuisines_split_into_list():
    assert split_list("North Indian, Chinese", lower=True) == ["north indian", "chinese"]


def test_list_drops_empty_and_repeated_items():
    assert split_list("Chinese, , chinese, Thai,", lower=True) == ["chinese", "thai"]


def test_list_from_missing_value_is_empty():
    assert split_list(None) == []


def test_dish_liked_is_capped():
    catalog = build_catalog([raw_row(dish_liked=", ".join(f"Dish {i}" for i in range(20)))])
    assert len(catalog[0]["dish_liked"]) == 8


# --- text -----------------------------------------------------------------

def test_mojibake_is_repaired():
    assert repair_text("CafÃ©") == "Café"


def test_clean_text_is_left_alone():
    assert repair_text("Café Coffee Day") == "Café Coffee Day"


def test_name_and_address_are_trimmed():
    row = build_catalog([raw_row(name="  Jalsa  ", address=" 942,  21st Main ")])[0]
    assert row["name"] == "Jalsa"
    assert row["address"] == "942, 21st Main"


# --- rows -----------------------------------------------------------------

def test_missing_name_is_dropped():
    catalog = build_catalog([raw_row(name=None), raw_row(name="   "), raw_row(name="Kept")])
    assert [row["name"] for row in catalog] == ["Kept"]


def test_row_fields_are_typed():
    row = build_catalog([raw_row()])[0]
    assert row["rating"] == 4.1
    assert row["cost_for_two"] == 800
    assert row["votes"] == 775
    assert row["online_order"] is True
    assert row["cuisines"] == ["north indian", "mughlai", "chinese"]
    assert row["rest_type"] == ["Casual Dining"]
    assert row["locality"] == "Banashankari"
    assert row["listed_city"] == "Banashankari"


def test_heavy_fields_are_not_kept():
    row = build_catalog([raw_row()])[0]
    assert "phone" not in row
    assert "menu_item" not in row
    assert "reviews_list" not in row


# --- ids and dedup ----------------------------------------------------------

def test_id_is_stable_and_ignores_case_and_spacing():
    assert make_id("Jalsa", "942, 21st Main") == make_id("  JALSA ", "942 21st  main")
    assert make_id("Jalsa", "942, 21st Main") != make_id("Jalsa", "1 Other Road")


def test_duplicates_collapse_keeping_higher_votes():
    catalog = build_catalog([
        raw_row(votes=100, rate="4.5/5", **{"listed_in(city)": "Banashankari"}),
        raw_row(votes=775, rate="4.1/5", **{"listed_in(city)": "Jayanagar"}),
    ])
    assert len(catalog) == 1
    assert catalog[0]["votes"] == 775
    assert catalog[0]["listed_city"] == "Jayanagar"


def test_vote_tie_keeps_higher_rating():
    catalog = build_catalog([raw_row(votes=50, rate="3.9/5"), raw_row(votes=50, rate="4.2/5")])
    assert catalog[0]["rating"] == 4.2


def test_vote_tie_prefers_real_rating_over_null():
    catalog = build_catalog([raw_row(votes=0, rate="NEW"), raw_row(votes=0, rate="3.5/5")])
    assert catalog[0]["rating"] == 3.5


def test_full_tie_keeps_first_row():
    catalog = build_catalog([
        raw_row(url="https://first.example"),
        raw_row(url="https://second.example"),
    ])
    assert catalog[0]["url"] == "https://first.example"


def test_same_name_different_address_stays_separate():
    catalog = build_catalog([raw_row(), raw_row(address="12, Church Street, Bangalore")])
    assert len(catalog) == 2


# --- review excerpt ---------------------------------------------------------

def test_reviews_list_is_parsed():
    reviews = parse_reviews("[('Rated 4.0', 'RATED\\n  Nice'), ('Rated', 'No score')]")
    assert reviews == [(4.0, "RATED\n  Nice"), (None, "No score")]


def test_unparseable_reviews_give_no_excerpt():
    assert parse_reviews("not a list") == []
    assert build_catalog([raw_row(reviews_list="[]")])[0]["review_excerpt"] is None


def test_excerpt_strips_rated_prefix_and_whitespace():
    row = build_catalog([raw_row()])[0]
    assert row["review_excerpt"] == "A beautiful place to dine in."


def test_excerpt_prefers_review_with_rating():
    excerpt = pick_excerpt([(None, "Unrated first"), (4.0, "Rated second")])
    assert excerpt == "Rated second"


def test_excerpt_falls_back_to_unrated_review():
    assert pick_excerpt([(None, "Only unrated")]) == "Only unrated"


def test_excerpt_is_at_most_400_characters():
    long_review = "word " * 500
    excerpt = pick_excerpt([(4.0, long_review)])
    assert len(excerpt) <= EXCERPT_MAX_CHARS
    assert excerpt.endswith("…")


# --- facets -----------------------------------------------------------------

def test_facets_are_sorted_and_unique():
    catalog = build_catalog([
        raw_row(name="A", location="Jayanagar", cuisines="Italian, Chinese"),
        raw_row(name="B", location="Banashankari", cuisines="chinese"),
        raw_row(name="C", location=None, cuisines="Cafe"),
    ])
    facets = build_facets(catalog)
    assert facets == {
        "localities": ["Banashankari", "Jayanagar"],
        "cuisines": ["cafe", "chinese", "italian"],
    }
    json.dumps(facets)
