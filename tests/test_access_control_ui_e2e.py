import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID, uuid4

import pytest
from playwright.sync_api import sync_playwright
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    AuthIdentity,
    Company,
    CompanyMembership,
    CompanyMembershipRole,
    CompanyRole,
    CompanyRolePermission,
    Permission,
    User,
)
from app.services.access_control import ensure_company_system_roles


def seed_browser_test_company_and_member():
    suffix = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        company = Company(
            code=f"E2E{suffix}",
            name=f"瀏覽器測試銀樓 {suffix}",
            is_active=True,
        )
        user = User(
            display_name="瀏覽器測試店員",
            email=f"browser-{suffix.lower()}@example.com",
            is_active=True,
        )
        db.add_all([company, user])
        db.flush()

        db.add(AuthIdentity(
            user_id=user.id,
            provider="GOOGLE",
            provider_subject=f"browser-test-{suffix}",
            provider_email=user.email,
            email_verified=True,
        ))
        roles = ensure_company_system_roles(db, company.id)
        membership = CompanyMembership(
            company_id=company.id,
            user_id=user.id,
            status="ACTIVE",
            role="STAFF",
        )
        db.add(membership)
        db.flush()
        db.add(CompanyMembershipRole(
            membership_id=membership.id,
            role_id=roles["STAFF"].id,
        ))
        db.commit()
        return {
            "company_id": str(company.id),
            "user_id": str(user.id),
            "membership_id": str(membership.id),
            "email": user.email,
            "staff_role_id": str(roles["STAFF"].id),
        }


def start_application():
    if not settings.auth_configured:
        pytest.fail("CI owner login credentials are not configured for the browser E2E test.")
    if not settings.database_url.startswith("postgresql"):
        pytest.fail("The authenticated browser E2E test must use the disposable PostgreSQL CI database.")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    log_file = tempfile.TemporaryFile(mode="w+b")
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log_file.seek(0)
                raise RuntimeError(
                    "FastAPI stopped before becoming ready:\n"
                    + log_file.read().decode("utf-8", errors="replace")
                )
            try:
                with urlopen(f"{base_url}/health", timeout=2) as response:
                    if response.status == 200:
                        return base_url, process, log_file
            except (OSError, URLError, TimeoutError):
                time.sleep(0.25)
        log_file.seek(0)
        raise RuntimeError(
            "FastAPI did not become ready within 45 seconds:\n"
            + log_file.read().decode("utf-8", errors="replace")
        )
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        log_file.close()
        raise


def stop_application(process, log_file):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    log_file.close()


def permission_card(page, code):
    card = page.locator("#permissions .permission").filter(has_text=code)
    card.first.wait_for(state="visible")
    assert card.count() == 1, f"Expected one permission card for {code}; found {card.count()}"
    return card


def test_owner_login_can_manage_real_roles_and_member_assignments():
    assert settings.environment.lower() == "production"
    assert settings.session_cookie_secure is False

    seeded = seed_browser_test_company_and_member()
    base_url, process, log_file = start_application()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            # The role editor may serve its static shell to guests, but no
            # administrator data is available until the owner session is valid.
            guest = browser.new_page()
            guest_response = guest.goto(
                f"{base_url}/role-management",
                wait_until="domcontentloaded",
            )
            assert guest_response is not None and guest_response.status == 200
            assert "角色與權限管理" in guest.locator("body").inner_text()
            denied_role_api = guest.request.get(f"{base_url}/admin/api/companies")
            assert denied_role_api.status == 401

            # The separate member-management page remains administrator-only.
            denied_member_page = guest.goto(
                f"{base_url}/member-management",
                wait_until="domcontentloaded",
            )
            assert denied_member_page is not None and denied_member_page.status == 401
            guest.close()

            page.goto(f"{base_url}/login", wait_until="domcontentloaded")
            page.locator("#username").fill(settings.admin_username)
            page.locator("#password").fill(settings.admin_password)
            page.get_by_role("button", name="登入系統").click()
            page.wait_for_url("**/app")
            me = page.request.get(f"{base_url}/auth/me")
            assert me.status == 200
            assert me.json()["role"] == "administrator"

            # Change a permission on the existing STAFF role through the real API.
            page.goto(f"{base_url}/role-management", wait_until="domcontentloaded")
            page.locator(
                f"#company option[value='{seeded['company_id']}']"
            ).wait_for(state="attached")
            page.locator("#company").select_option(seeded["company_id"])
            page.locator(
                f"#role option[value='{seeded['staff_role_id']}']"
            ).wait_for(state="attached")
            page.locator("#role").select_option(seeded["staff_role_id"])
            page.wait_for_function(
                "(roleId) => document.querySelector('#role')?.value === roleId && "
                "document.querySelector('#role-meta')?.textContent.includes('預設不授權')",
                arg=seeded["staff_role_id"],
            )

            staff_card = permission_card(page, "products.view")
            staff_checkbox = staff_card.locator('input[type="checkbox"]')
            staff_scope = staff_card.locator("select")
            staff_checkbox.check()
            staff_scope.select_option("ALL")
            page.get_by_role("button", name="儲存權限").click()
            page.get_by_text("權限設定已儲存。").wait_for()

            # Create a custom role and grant it a safe, read-only catalog permission.
            page.locator("#new-code").fill("STOCK_VIEWER")
            page.locator("#new-name").fill("庫存檢視")
            page.get_by_role("button", name="新增角色").click()
            page.get_by_text("自訂角色已建立，預設沒有任何授權。").wait_for()
            page.locator("#role option").filter(
                has_text="庫存檢視（自訂）"
            ).wait_for(state="attached")
            custom_role_id = page.locator("#role").input_value()
            assert custom_role_id
            page.wait_for_function(
                "(roleId) => document.querySelector('#role')?.value === roleId && "
                "document.querySelector('#role-meta')?.textContent.includes('自訂角色')",
                arg=custom_role_id,
            )

            custom_card = permission_card(page, "products.view")
            custom_card.locator('input[type="checkbox"]').check()
            custom_card.locator("select").select_option("ALL")
            page.get_by_role("button", name="儲存權限").click()
            page.get_by_text("權限設定已儲存。").wait_for()

            # Assign the new custom role together with STAFF to the seeded member.
            page.goto(f"{base_url}/member-management", wait_until="domcontentloaded")
            member_card = page.locator(".member").filter(has_text=seeded["email"])
            edit_roles = member_card.get_by_role("button", name="編輯角色")
            edit_roles.wait_for()
            edit_roles.click()
            custom_role_label = member_card.locator(".role-editor label").filter(
                has_text="庫存檢視（自訂）"
            )
            custom_role_label.locator('input[type="checkbox"]').check()
            member_card.get_by_role("button", name="儲存角色").click()
            member_card.get_by_text("角色：一般成員、庫存檢視").wait_for()

            with SessionLocal() as db:
                membership = db.get(CompanyMembership, UUID(seeded["membership_id"]))
                assert membership is not None
                assigned_ids = set(db.scalars(
                    select(CompanyMembershipRole.role_id).where(
                        CompanyMembershipRole.membership_id == membership.id
                    )
                ).all())
                assert assigned_ids == {
                    db.scalar(select(CompanyRole.id).where(
                        CompanyRole.company_id == UUID(seeded["company_id"]),
                        CompanyRole.code == "STAFF",
                    )),
                    db.scalar(select(CompanyRole.id).where(
                        CompanyRole.company_id == UUID(seeded["company_id"]),
                        CompanyRole.code == "STOCK_VIEWER",
                    )),
                }
                custom_role = db.scalar(select(CompanyRole).where(
                    CompanyRole.id == UUID(custom_role_id)
                ))
                assert custom_role is not None
                product_view = db.scalar(select(Permission).where(
                    Permission.code == "products.view"
                ))
                grant = db.scalar(select(CompanyRolePermission).where(
                    CompanyRolePermission.role_id == custom_role.id,
                    CompanyRolePermission.permission_id == product_view.id,
                ))
                assert grant is not None and grant.is_allowed is True
                assert grant.data_scope == "ALL"

            assert not page_errors, page_errors
            browser.close()
    finally:
        stop_application(process, log_file)
