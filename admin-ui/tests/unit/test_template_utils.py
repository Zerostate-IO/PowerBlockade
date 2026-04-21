from __future__ import annotations

from starlette.requests import Request

from app.template_utils import PowerBlockadeTemplates


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


def test_template_response_accepts_legacy_signature(tmp_path):
    (tmp_path / "hello.html").write_text("Hello {{ name }}", encoding="utf-8")
    templates = PowerBlockadeTemplates(directory=str(tmp_path))

    response = templates.TemplateResponse(
        "hello.html",
        {"request": _request(), "name": "PowerBlockade"},
        status_code=202,
    )

    assert response.status_code == 202
    assert bytes(response.body).decode() == "Hello PowerBlockade"


def test_template_response_accepts_new_signature(tmp_path):
    (tmp_path / "hello.html").write_text("Hello {{ name }}", encoding="utf-8")
    templates = PowerBlockadeTemplates(directory=str(tmp_path))
    request = _request()

    response = templates.TemplateResponse(
        request,
        "hello.html",
        {"request": request, "name": "PowerBlockade"},
        status_code=201,
    )

    assert response.status_code == 201
    assert bytes(response.body).decode() == "Hello PowerBlockade"
