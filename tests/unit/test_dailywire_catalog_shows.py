from __future__ import annotations


def test_catalog_shows_pages_the_catalog_collections(monkeypatch) -> None:
    from backend.api.endpoints.dailywire.catalog import service
    from sources.dailywire.api.records import DwCatalogRecord, DwCatalogShowRecord

    catalog = DwCatalogRecord(collections=[
        DwCatalogShowRecord(dw_id="1", slug="the-ben-shapiro-show", title="The Ben Shapiro Show", author_name="Ben Shapiro"),
        DwCatalogShowRecord(dw_id="2", slug="the-matt-walsh-show", title="The Matt Walsh Show", author_name="Matt Walsh"),
        DwCatalogShowRecord(dw_id="3", slug="morning-wire", title="Morning Wire"),
    ])
    monkeypatch.setattr(service, "get_catalog", lambda: catalog)

    by_host = service.get_catalog_shows(offset=0, limit=2, search=None, grouping="host")
    assert [show.slug for show in by_host.items] == ["the-ben-shapiro-show", "the-matt-walsh-show"]
    assert by_host.total == 3
    assert by_host.has_more

    searched = service.get_catalog_shows(offset=0, limit=24, search="walsh", grouping="alphabetical")
    assert [show.slug for show in searched.items] == ["the-matt-walsh-show"]
