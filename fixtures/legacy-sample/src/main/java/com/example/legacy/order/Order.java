package com.example.legacy.order;

import java.util.ArrayList;
import java.util.List;

public class Order {
    private final String orderId;
    private final String partyId;
    private OrderStatus status = OrderStatus.CREATED;
    private final List<OrderItem> items = new ArrayList<OrderItem>();

    public Order(String orderId, String partyId) {
        this.orderId = orderId;
        this.partyId = partyId;
    }

    public String getOrderId() {
        return orderId;
    }

    public String getPartyId() {
        return partyId;
    }

    public OrderStatus getStatus() {
        return status;
    }

    public void setStatus(OrderStatus status) {
        this.status = status;
    }

    public List<OrderItem> getItems() {
        return items;
    }
}
