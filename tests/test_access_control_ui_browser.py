from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json

import pytest
from playwright.sync_api import sync_playwright


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


@pytest.fixture(scope="module")
def static_server():
    handler = partial(QuietStaticHandler, directory=str(STATIC_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def json_response(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
    )


def permission(code, name, resource, action, allowed=False, scope="OWN"):
    return {
        "code": code,
        "name": name,
        "resource_code": resource,
        "action_code": action,
        "is_allowed": allowed,
        "data_scope": scope,
    }


def test_role_editor_toggles_scope_and_saves_permission_grants(static_server):
    company = {"id": "company-1", "name": "測試銀樓", "code": "MAIN"}
    custom_role = {
        "id": "role-stock-viewer",
        "company_id": company["id"],
        "code": "STOCK_VIEWER",
        "name": "庫存檢視",
        "description": "測試角色",
        "is_system": False,
        "is_active": True,
        "permissions": [
            permission("products.view", "商品－查看", "products", "view"),
            permission("products.create", "商品－新增", "products", "create"),
        ],
    }
    system_role = {
        "id": "role-owner",
        "company_id": company["id"],
        "code": "OWNER",
        "name": "負責人",
        "description": "",
        "is_system": True,
        "is_active": True,
        "permissions": custom_role["permissions"],
    }
    saved_payloads = []

    def handle_api(route):
        request = route.request
        path = request.url.split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
        if request.method == "GET" and path == "admin/api/companies":
            json_response(route, [company])
        elif request.method == "GET" and path == f"admin/api/companies/{company['id']}/roles":
            json_response(route, [system_role, custom_role])
        elif request.method == "PUT" and path == "admin/api/roles/role-stock-viewer/permissions":
            payload = request.post_data_json
            saved_payloads.append(payload)
            by_code = {item["code"]: item for item in payload["permissions"]}
            custom_role["permissions"] = [
                permission(
                    "products.view", "商品－查看", "products", "view",
                    by_code["products.view"]["is_allowed"],
                    by_code["products.view"]["data_scope"],
                ),
                permission(
                    "products.create", "商品－新增", "products", "create",
                    by_code["products.create"]["is_allowed"],
                    by_code["products.create"]["data_scope"],
                ),
            ]
            json_response(route, custom_role)
        else:
            raise AssertionError(f"Unexpected role editor API request: {request.method} {path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/admin/api/**", handle_api)
        page.goto(f"{static_server}/role_management.html", wait_until="domcontentloaded")

        page.locator("#company option[value='company-1']").wait_for(state="attached")
        page.locator("#role").select_option("role-stock-viewer")
        view_checkbox = page.get_by_role("checkbox", name="商品－查看授權")
        scope_select = page.locator('select[aria-label="商品－查看資料範圍"]')

        assert scope_select.is_disabled()
        view_checkbox.check()
        assert scope_select.is_enabled()
        scope_select.select_option("ALL")
        page.get_by_role("button", name="儲存權限").click()
        page.get_by_text("權限設定已儲存。").wait_for()

        assert len(saved_payloads) == 1
        grants = {item["code"]: item for item in saved_payloads[0]["permissions"]}
        assert grants["products.view"] == {
            "code": "products.view",
            "is_allowed": True,
            "data_scope": "ALL",
        }
        assert grants["products.create"]["is_allowed"] is False
        assert not page_errors, page_errors
        browser.close()


def test_member_editor_assigns_multiple_company_roles(static_server):
    company = {"id": "company-1", "name": "測試銀樓", "code": "MAIN"}
    available_roles = [
        {
            "id": "role-staff", "company_id": company["id"], "code": "STAFF",
            "name": "一般成員", "description": "", "is_system": True, "is_active": True,
            "permissions": [],
        },
        {
            "id": "role-stock-viewer", "company_id": company["id"], "code": "STOCK_VIEWER",
            "name": "庫存檢視", "description": "", "is_system": False, "is_active": True,
            "permissions": [],
        },
        {
            "id": "role-manager", "company_id": company["id"], "code": "MANAGER",
            "name": "管理者", "description": "", "is_system": True, "is_active": True,
            "permissions": [],
        },
    ]
    assigned_role_ids = ["role-staff"]

    def members_payload():
        selected = [role for role in available_roles if role["id"] in assigned_role_ids]
        return [{
            "id": "user-1",
            "display_name": "測試店員",
            "email": "employee@example.com",
            "is_active": True,
            "created_at": "2026-11-25T00:00:00+00:00",
            "identities": [],
            "memberships": [{
                "id": "membership-1",
                "company_id": company["id"],
                "company_name": company["name"],
                "status": "ACTIVE",
                "role": "STAFF",
                "roles": [
                    {"id": role["id"], "code": role["code"], "name": role["name"]}
                    for role in selected
                ],
                "created_at": "2026-11-25T00:00:00+00:00",
            }],
        }]

    def handle_api(route):
        request = route.request
        path = request.url.split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
        if request.method == "GET" and path == "admin/api/members":
            json_response(route, members_payload())
        elif request.method == "GET" and path == "admin/api/companies":
            json_response(route, [company])
        elif request.method == "GET" and path == f"admin/api/companies/{company['id']}/roles":
            json_response(route, available_roles)
        elif request.method == "PUT" and path == "admin/api/memberships/membership-1/roles":
            payload = request.post_data_json
            assert len(payload["role_ids"]) == 2
            assert "role-staff" in payload["role_ids"]
            assert "role-stock-viewer" in payload["role_ids"]
            assigned_role_ids[:] = payload["role_ids"]
            json_response(route, {"role_ids": assigned_role_ids})
        else:
            raise AssertionError(f"Unexpected member editor API request: {request.method} {path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/admin/api/**", handle_api)
        page.goto(f"{static_server}/member_management.html", wait_until="domcontentloaded")

        page.get_by_role("button", name="編輯角色").wait_for()
        page.get_by_role("button", name="編輯角色").click()
        custom_role = page.locator(".role-editor label").filter(has_text="庫存檢視（自訂）")
        custom_role.locator("input[type=checkbox]").check()
        page.get_by_role("button", name="儲存角色").click()
        page.get_by_text("角色：一般成員、庫存檢視").wait_for()

        assert set(assigned_role_ids) == {"role-staff", "role-stock-viewer"}
        assert not page_errors, page_errors
        browser.close()
