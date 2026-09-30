package com.example.legacy.order;

import com.example.legacy.billing.InvoiceService;
import com.example.legacy.common.Delegator;
import com.example.legacy.common.EntityQuery;
import com.example.legacy.common.GenericValue;
import com.example.legacy.common.StringUtil;
import com.example.legacy.party.PartyService;
import java.util.ArrayList;
import java.util.List;

/**
 * Read-side helper that everyone ends up calling: high fan-in, and because it reaches into
 * party and billing itself, high fan-out too.
 */
public class OrderReadHelper {
    private final Delegator delegator;

    public OrderReadHelper(Delegator delegator) {
        this.delegator = delegator;
    }

    public boolean isOpen(String orderId) {
        GenericValue header = EntityQuery.use(delegator).from("OrderHeader")
                .where("orderId", StringUtil.normalizeId(orderId)).queryOne();
        if (header == null) {
            return false;
        }
        OrderStatus status = OrderStatus.valueOf(header.getString("statusId"));
        return status != OrderStatus.CANCELLED && status != OrderStatus.COMPLETED;
    }

    public List<GenericValue> getOpenOrders(String partyId) {
        List<GenericValue> all = EntityQuery.use(delegator).from("OrderHeader")
                .where("partyId", partyId).queryList();
        List<GenericValue> open = new ArrayList<GenericValue>();
        for (GenericValue header : all) {
            if (isOpen(header.getString("orderId"))) {
                open.add(header);
            }
        }
        return open;
    }

    public Order load(String orderId) {
        GenericValue header = EntityQuery.use(delegator).from("OrderHeader")
                .where("orderId", orderId).queryOne();
        if (header == null) {
            return null;
        }
        Order order = new Order(orderId, header.getString("partyId"));
        List<GenericValue> rows = EntityQuery.use(delegator).from("OrderItem")
                .where("orderId", orderId).queryList();
        for (GenericValue row : rows) {
            order.getItems().add(new OrderItem(row.getString("productId"), 1, 0L));
        }
        return order;
    }

    public ShoppingCart cartFor(String orderId) {
        ShoppingCart cart = new ShoppingCart(this);
        Order order = load(orderId);
        if (order != null) {
            for (OrderItem item : order.getItems()) {
                cart.add(item.getProductId(), item.getQuantity(), item.getUnitPriceJpy());
            }
        }
        return cart;
    }

    public String customerName(String orderId) {
        Order order = load(orderId);
        if (order == null) {
            return "";
        }
        return new PartyService(delegator).findParty(order.getPartyId()).getDisplayName();
    }

    public boolean hasInvoice(String orderId) {
        return new InvoiceService("jdbc:hsqldb:mem:legacy").isOrderBillable(orderId);
    }
}
