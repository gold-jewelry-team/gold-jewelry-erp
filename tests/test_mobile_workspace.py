from fastapi.testclient import TestClient

from app.main import app


def test_mobile_workspace_serves_html():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "黃金珠寶進銷存" in response.text
    assert 'id="productForm"' in response.text
    assert 'id="companySelect"' in response.text
    assert 'id="inventoryStockPanel"' in response.text
    assert 'id="inventoryAdjustmentForm"' in response.text
    assert 'id="inventoryTransferForm"' in response.text
    assert 'id="inventoryMovementPanel"' in response.text
    assert 'id="goldPricePanel"' in response.text
    assert 'id="goldPriceForm"' in response.text
    assert 'id="goldPriceScope"' in response.text
    assert 'id="salesPanel"' in response.text
    assert 'id="saleHeaderForm"' in response.text
    assert 'id="saleCartList"' in response.text
    assert 'id="saleBarcodeScan"' in response.text
    assert 'id="completeSale"' in response.text
    assert 'id="voidSale"' in response.text
    assert 'id="dailyClosingForm"' in response.text
    assert 'id="cashCountCreateForm"' in response.text
    assert 'id="cashCountReviewForm"' in response.text
    assert 'id="productEditForm"' in response.text
    assert 'data-edit-product="' in response.text
