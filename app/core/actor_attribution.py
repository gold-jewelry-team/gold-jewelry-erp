"""Automatic record-actor tracking and own-record ORM query scoping."""
from sqlalchemy import event, exists, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.actor_context import current_actor
from app.models import (
    BankAccount,
    BankReconciliationSnapshot,
    BankStatementImport,
    BankStatementLine,
    BankTransaction,
    CashDrawerMovement,
    CustomerOrder,
    DailyCashCount,
    DailyClosing,
    GoldMaterialMovement,
    GoldPrice,
    InventoryMovement,
    InventoryOperationRequest,
    OperatingExpense,
    PaymentTransaction,
    Product,
    ProductCategory,
    Purchase,
    Sale,
    SaleReturn,
    Supplier,
    SupplierBill,
    SupplierCategoryOffering,
    SupplierPayment,
    SupplierProductOffering,
)
from app.models.access_control import RecordActor


MODEL_RESOURCE = {
    Product: "products",
    ProductCategory: "product_categories",
    InventoryMovement: "inventory",
    InventoryOperationRequest: "inventory",
    Purchase: "purchases",
    Sale: "sales",
    SaleReturn: "sales_returns",
    CustomerOrder: "customer_orders",
    Supplier: "suppliers",
    SupplierBill: "supplier_payables",
    SupplierPayment: "supplier_payables",
    PaymentTransaction: "payments",
    OperatingExpense: "expenses",
    CashDrawerMovement: "cash_drawer",
    BankAccount: "bank_accounts",
    BankTransaction: "bank_accounts",
    BankStatementImport: "bank_reconciliation",
    BankStatementLine: "bank_reconciliation",
    BankReconciliationSnapshot: "bank_reconciliation",
    DailyClosing: "daily_closing",
    DailyCashCount: "daily_closing",
    GoldMaterialMovement: "gold_material",
    GoldPrice: "gold_prices",
    SupplierCategoryOffering: "supplier_offerings",
    SupplierProductOffering: "supplier_offerings",
}

RESOURCE_MODELS: dict[str, tuple[type, ...]] = {}
for _model, _resource in MODEL_RESOURCE.items():
    RESOURCE_MODELS[_resource] = RESOURCE_MODELS.get(_resource, ()) + (_model,)


@event.listens_for(Session, "before_flush")
def _capture_changed_company_records(session, flush_context, instances):
    actor = current_actor.get()
    if actor is None:
        return

    pending = session.info.setdefault("_actor_records_pending", {})
    candidates = list(session.new)
    candidates.extend(
        item for item in session.dirty
        if session.is_modified(item, include_collections=False)
    )
    for item in candidates:
        resource = MODEL_RESOURCE.get(type(item))
        if resource is None or not hasattr(item, "company_id"):
            continue
        company_id = getattr(item, "company_id", None)
        if company_id is None:
            continue
        if actor.company_id is not None and company_id != actor.company_id:
            continue
        pending[id(item)] = (item, item in session.new, resource, company_id)


@event.listens_for(Session, "after_flush_postexec")
def _write_record_actor_rows(session, flush_context):
    pending = session.info.pop("_actor_records_pending", {})
    if not pending:
        return
    actor = current_actor.get()
    if actor is None:
        return

    for item, is_new, resource, company_id in pending.values():
        record_id = getattr(item, "id", None)
        if record_id is None:
            continue
        actor_row = session.scalar(
            select(RecordActor).where(
                RecordActor.resource_code == resource,
                RecordActor.record_id == record_id,
            )
        )
        if actor_row is None:
            actor_row = RecordActor(
                company_id=company_id,
                resource_code=resource,
                record_id=record_id,
                created_by_user_id=(
                    actor.user_id if is_new and actor.actor_type == "GOOGLE" else None
                ),
                created_by_admin_username=(
                    actor.admin_username if is_new and actor.actor_type == "ADMIN" else None
                ),
            )
            session.add(actor_row)

        if actor.actor_type == "GOOGLE":
            actor_row.updated_by_user_id = actor.user_id
            actor_row.updated_by_admin_username = None
        else:
            actor_row.updated_by_user_id = None
            actor_row.updated_by_admin_username = actor.admin_username


def _own_record_criterion(resource_code: str, company_id, user_id):
    def criterion(model):
        return exists(
            select(RecordActor.id).where(
                RecordActor.company_id == company_id,
                RecordActor.resource_code == resource_code,
                RecordActor.record_id == model.id,
                RecordActor.created_by_user_id == user_id,
            )
        )
    return criterion


@event.listens_for(Session, "do_orm_execute")
def _apply_own_record_scope(execute_state):
    actor = current_actor.get()
    if (
        actor is None
        or actor.actor_type != "GOOGLE"
        or actor.data_scope != "OWN"
        or not actor.company_id
        or not actor.user_id
        or not actor.permission_code
        or not execute_state.is_select
    ):
        return

    resource_code = actor.permission_code.split(".", 1)[0]
    models = RESOURCE_MODELS.get(resource_code, ())
    if not models:
        return

    statement = execute_state.statement
    for model in models:
        statement = statement.options(
            with_loader_criteria(
                model,
                _own_record_criterion(resource_code, actor.company_id, actor.user_id),
                include_aliases=True,
            )
        )
    execute_state.statement = statement
