package com.example.legacy.billing;

public class InvoiceItem {
    private final String productId;
    private final int quantity;
    private final long unitPriceJpy;

    public InvoiceItem(String productId, int quantity, long unitPriceJpy) {
        this.productId = productId;
        this.quantity = quantity;
        this.unitPriceJpy = unitPriceJpy;
    }

    public String getProductId() {
        return productId;
    }

    public int getQuantity() {
        return quantity;
    }

    public long getUnitPriceJpy() {
        return unitPriceJpy;
    }
}
