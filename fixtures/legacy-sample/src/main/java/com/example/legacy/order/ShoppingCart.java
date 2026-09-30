package com.example.legacy.order;

import com.example.legacy.common.StringUtil;
import java.util.ArrayList;
import java.util.List;

public class ShoppingCart {
    private final List<OrderItem> items = new ArrayList<OrderItem>();
    private final OrderReadHelper readHelper;

    public ShoppingCart(OrderReadHelper readHelper) {
        this.readHelper = readHelper;
    }

    public void add(String productId, int quantity, long unitPriceJpy) {
        if (StringUtil.isEmpty(productId) || quantity <= 0) {
            return;
        }
        for (OrderItem existing : items) {
            if (existing.getProductId().equals(productId)) {
                existing.setQuantity(existing.getQuantity() + quantity);
                return;
            }
        }
        items.add(new OrderItem(productId, quantity, unitPriceJpy));
    }

    public long subtotal() {
        long sum = 0;
        for (OrderItem item : items) {
            sum += item.getUnitPriceJpy() * item.getQuantity();
        }
        return sum;
    }

    public List<OrderItem> getItems() {
        return items;
    }

    public boolean isOrderOpen(String orderId) {
        return readHelper.isOpen(orderId);
    }
}
