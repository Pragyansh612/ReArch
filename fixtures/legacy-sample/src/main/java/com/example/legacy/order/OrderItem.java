package com.example.legacy.order;

public class OrderItem {
    private final String productId;
    private int quantity;
    private final long unitPriceJpy;

    public OrderItem(String productId, int quantity, long unitPriceJpy) {
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

    public void setQuantity(int quantity) {
        this.quantity = quantity;
    }

    public long getUnitPriceJpy() {
        return unitPriceJpy;
    }
}
