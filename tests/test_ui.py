import re

from tests.test_api import client  # noqa: F401  (reuse the API fixture)


def test_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    for field in ('id="locality"', 'id="cuisine"', 'name="budget"', 'id="min_rating"', 'id="preferences"'):
        assert field in html
    assert 'min="0" max="5" step="0.1"' in html
    assert 'maxlength="300"' in html
    assert "family-friendly, quick service" in html
    assert [v for v in re.findall(r'name="budget" value="(\w+)"', html)] == ["low", "medium", "high"]


def test_static_assets_are_served(client):
    for path, kind in (("/static/app.js", "javascript"), ("/static/styles.css", "css")):
        response = client.get(path)
        assert response.status_code == 200
        assert kind in response.headers["content-type"]


def test_card_fields_are_in_problem_statement_order(client):
    html = client.get("/").text
    template = html[html.index('<template id="card-template">'):]
    order = [template.index(cls) for cls in ('class="name"', 'class="cuisines"', 'class="rating"',
                                             'class="cost"', 'class="explanation"')]
    assert order == sorted(order)


def test_script_never_uses_inner_html(client):
    script = client.get("/static/app.js").text
    assert "innerHTML" not in script.replace("never innerHTML", "")
    assert "insertAdjacentHTML" not in script
