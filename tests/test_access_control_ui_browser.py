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


def test_employee_workspace_shows_company_roles_permissions_and_logout(static_server):
    workspace = {
        "authenticated": True,
        "user": {"id": "user-1", "display_name": "測試店員", "email": "employee@example.com"},
        "status": "ACTIVE",
        "memberships": [{
            "id": "membership-1",
            "company_id": "company-1",
            "company_name": "測試銀樓",
            "company_code": "MAIN",
            "company_is_active": True,
            "status": "ACTIVE",
            "roles": [
                {"code": "STAFF", "name": "一般成員"},
                {"code": "STOCK_VIEWER", "name": "庫存檢視"},
            ],
            "permissions": [
                permission("products.view", "商品－查看", "products", "view", True, "ALL"),
                permission("inventory.view", "庫存－查看", "inventory", "view", True, "OWN"),
                permission("products.create", "商品－新增", "products", "create", True, "OWN"),
            ],
        }],
    }
    logout_requests = []

    def handle_logout(route):
        logout_requests.append(route.request.method)
        json_response(route, {"authenticated": False})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/auth/google/workspace", lambda route: json_response(route, workspace))
        page.route("**/auth/google/logout", handle_logout)
        page.route("**/login", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<h1>登入</h1>"
        ))
        page.goto(f"{static_server}/employee.html", wait_until="domcontentloaded")

        page.get_by_text("測試店員").wait_for()
        page.get_by_text("測試銀樓").wait_for()
        page.get_by_text("一般成員").wait_for()
        page.get_by_text("庫存檢視").wait_for()
        page.get_by_text("查看（全公司資料）").wait_for()
        page.get_by_text("新增（僅本人建立的資料）").wait_for()
        page.get_by_text("查看（僅本人建立的資料）").wait_for()
        product_link=page.get_by_role("link",name="商品查詢")
        product_link.wait_for()
        assert "/employee/catalog?company_id=company-1&view=products" in product_link.get_attribute("href")
        # Inventory is not offered because the grant is OWN-scoped, not a usable ALL grant.
        assert page.get_by_role("link",name="庫存查詢").count()==0

        page.get_by_role("button", name="登出").click()
        page.wait_for_url("**/login")
        assert logout_requests == ["POST"]
        assert not page_errors, page_errors
        browser.close()


def test_employee_workspace_explains_pending_approval_without_showing_permissions(static_server):
    workspace = {
        "authenticated": True,
        "user": {"id": "user-2", "display_name": "待核准店員", "email": "pending@example.com"},
        "status": "PENDING_APPROVAL",
        "memberships": [{
            "id": "membership-2",
            "company_id": "company-2",
            "company_name": "待核准銀樓",
            "company_code": "PENDING",
            "company_is_active": True,
            "status": "PENDING",
            "roles": [{"code": "STAFF", "name": "一般成員"}],
            "permissions": [],
        }],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/auth/google/workspace", lambda route: json_response(route, workspace))
        page.goto(f"{static_server}/employee.html", wait_until="domcontentloaded")

        page.get_by_text("待核准店員").wait_for()
        page.get_by_text("等待核准").wait_for()
        page.get_by_text("正在等待公司管理者核准").wait_for()
        page.get_by_text("核准前無法查看或修改公司營運資料").wait_for()
        assert page.locator(".permission").count() == 0
        assert not page_errors, page_errors
        browser.close()



def test_employee_catalog_loads_authorized_product_and_inventory_views(static_server):
    workspace = {
        "authenticated": True,
        "user": {"id": "user-3", "display_name": "查詢員工", "email": "catalog@example.com"},
        "status": "ACTIVE",
        "memberships": [{
            "id": "membership-3",
            "company_id": "company-3",
            "company_name": "查詢測試銀樓",
            "company_code": "CATALOG",
            "company_is_active": True,
            "status": "ACTIVE",
            "roles": [{"code": "STAFF", "name": "一般成員"}],
            "permissions": [
                permission("products.view", "商品－查看", "products", "view", True, "ALL"),
                permission("inventory.view", "庫存－查看", "inventory", "view", True, "ALL"),
            ],
        }],
    }
    requests = []

    def handle_company_api(route):
        request_url = route.request.url
        path = request_url.split("?", 1)[0]
        requests.append(request_url)
        if path.endswith("/products"):
            json_response(route, [{
                "id": "product-1",
                "company_id": "company-3",
                "category_id": None,
                "product_code": "G00E-22618",
                "barcode": "150702001",
                "name": "黃金耳環",
                "material_code": "GOLD",
                "gross_weight": "2.5000",
                "net_weight": "2.3000",
                "weight_unit_code": "QIAN",
                "labor_fee": "300.00",
                "chain_length": None,
                "style_code": "E",
                "note": None,
                "is_active": True,
                "created_at": "2026-11-25T00:00:00+00:00",
                "updated_at": "2026-11-25T00:00:00+00:00",
            }])
        elif path.endswith("/inventory/stock"):
            json_response(route, [{
                "company_id": "company-3",
                "site_id": "site-1",
                "site_name": "本店",
                "product_id": "product-1",
                "product_code": "G00E-22618",
                "barcode": "150702001",
                "product_name": "黃金耳環",
                "location_id": "location-1",
                "location_code": "A01",
                "location_name": "一樓展示櫃",
                "quantity": "3.000",
            }])
        else:
            raise AssertionError(f"Unexpected employee company API path: {path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/auth/google/workspace", lambda route: json_response(route, workspace))
        page.route("**/companies/company-3/**", handle_company_api)
        page.goto(
            f"{static_server}/employee_catalog.html?company_id=company-3&view=products",
            wait_until="domcontentloaded",
        )

        page.get_by_text("查詢測試銀樓").wait_for()
        page.get_by_text("G00E-22618").wait_for()
        page.get_by_text("黃金耳環").wait_for()
        assert page.locator("#productsTab").is_visible()
        assert page.locator("#inventoryTab").is_visible()
        assert len(requests) == 1 and "/products?limit=200" in requests[0]

        page.get_by_role("button", name="庫存查詢").click()
        page.get_by_text("一樓展示櫃").wait_for()
        page.get_by_text("庫存 3").wait_for()
        assert any("/inventory/stock" in url for url in requests)

        page.get_by_role("button", name="商品查詢").click()
        page.get_by_role("searchbox", name="搜尋商品").fill("耳環")
        page.get_by_role("button", name="搜尋").click()
        page.get_by_text("黃金耳環").wait_for()
        assert any("/products?" in url and "q=" in url for url in requests)
        assert not page_errors, page_errors
        browser.close()


def test_employee_catalog_hides_own_scope_shared_data_features(static_server):
    workspace = {
        "authenticated": True,
        "user": {"id": "user-4", "display_name": "受限員工", "email": "limited@example.com"},
        "status": "ACTIVE",
        "memberships": [{
            "id": "membership-4",
            "company_id": "company-4",
            "company_name": "受限測試銀樓",
            "company_code": "LIMITED",
            "company_is_active": True,
            "status": "ACTIVE",
            "roles": [{"code": "STAFF", "name": "一般成員"}],
            "permissions": [
                permission("products.view", "商品－查看", "products", "view", True, "ALL"),
                permission("inventory.view", "庫存－查看", "inventory", "view", True, "OWN"),
            ],
        }],
    }
    company_requests = []

    def handle_company_api(route):
        path = route.request.url.split("?", 1)[0]
        company_requests.append(path)
        if path.endswith("/products"):
            json_response(route, [])
        else:
            raise AssertionError(f"Unauthorized feature was requested: {path}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/auth/google/workspace", lambda route: json_response(route, workspace))
        page.route("**/companies/company-4/**", handle_company_api)
        page.goto(
            f"{static_server}/employee_catalog.html?company_id=company-4&view=inventory",
            wait_until="domcontentloaded",
        )

        page.get_by_text("受限測試銀樓").wait_for()
        page.locator("#productsTab").wait_for(state="visible")
        assert page.locator("#inventoryTab").is_hidden()
        assert page.locator("#pageTitle").inner_text() == "商品查詢"
        assert len(company_requests) == 1 and company_requests[0].endswith("/products")
        assert not page_errors, page_errors
        browser.close()
