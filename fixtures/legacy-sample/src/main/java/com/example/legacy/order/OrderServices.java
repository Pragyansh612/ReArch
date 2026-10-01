package com.example.legacy.order;

import com.example.legacy.billing.InvoiceItem;
import com.example.legacy.billing.InvoiceService;
import com.example.legacy.common.Delegator;
import com.example.legacy.common.EntityQuery;
import com.example.legacy.common.GenericValue;
import com.example.legacy.common.StringUtil;
import com.example.legacy.party.Party;
import com.example.legacy.party.PartyService;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.ejb.Stateless;

/**
 * Every order workflow lives here: status changes, inventory, adjustments, shipments, payments, returns, invoicing.
 * Stands in for OFBiz OrderServices.java (7,500 LOC). Extreme god class: far above both thresholds.
 */
@Stateless
public class OrderServices {
    private final Delegator delegator;
    private final OrderReadHelper readHelper;
    private final PartyService partyService;
    private final InvoiceService invoiceService;

    public OrderServices(Delegator delegator, InvoiceService invoiceService) {
        this.delegator = delegator;
        this.readHelper = new OrderReadHelper(delegator);
        this.partyService = new PartyService(delegator);
        this.invoiceService = invoiceService;
    }

    public Map<String, Object> createOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> approveOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> cancelOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CANCELLED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> holdOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.HELD;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> releaseOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> completeOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.COMPLETED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> reopenOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> archiveOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.COMPLETED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> splitOrder(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> mergeOrders(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> reserveInventory(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("InventoryItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("InventoryItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> releaseInventory(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("InventoryItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("InventoryItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> adjustInventory(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("InventoryItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("InventoryItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> transferInventory(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("InventoryItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("InventoryItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> calcTax(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderAdjustment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderAdjustment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> calcShipping(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderAdjustment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderAdjustment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> applyPromotion(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderAdjustment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderAdjustment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> removePromotion(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderAdjustment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderAdjustment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> applyDiscount(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderAdjustment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderAdjustment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> splitShipment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderShipment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderShipment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> mergeShipments(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderShipment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderShipment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> scheduleShipment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderShipment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderShipment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> cancelShipment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderShipment").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderShipment");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CANCELLED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> changeItemQuantity(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> addOrderItem(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> removeOrderItem(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderItem").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderItem");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> recordPayment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderPaymentPref").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderPaymentPref");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> refundPayment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderPaymentPref").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderPaymentPref");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CANCELLED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> authorizePayment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderPaymentPref").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderPaymentPref");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.APPROVED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> capturePayment(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("OrderPaymentPref").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("OrderPaymentPref");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.COMPLETED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> createReturn(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("ReturnHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("ReturnHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.CREATED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> receiveReturn(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("ReturnHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("ReturnHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.COMPLETED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public Map<String, Object> closeReturn(String orderId, String partyId, int quantity) {
        Map<String, Object> result = new HashMap<String, Object>();
        String id = StringUtil.normalizeId(orderId);
        if (id.isEmpty()) {
            result.put("error", "missing orderId");
            return result;
        }
        GenericValue row = EntityQuery.use(delegator).from("ReturnHeader").where("orderId", id).queryOne();
        if (row == null && quantity > 0) {
            row = delegator.makeValue("ReturnHeader");
            row.set("orderId", id);
            row.set("partyId", partyId);
            delegator.create(row);
        } else if (row == null) {
            result.put("error", "not found");
            return result;
        }
        Party party = partyService.findParty(partyId);
        if (party == null || !readHelper.isOpen(id)) {
            result.put("error", "order closed or party unknown");
            return result;
        }
        OrderStatus status = OrderStatus.COMPLETED;
        int checked = 0;
        for (int i = 0; i < quantity; i++) {
            if (i % 2 == 0 && quantity > 10) {
                checked += 2;
            } else if (quantity > 100) {
                checked += 3;
            } else {
                checked++;
            }
        }
        switch (status) {
            case CREATED:
                result.put("next", "approve");
                break;
            case APPROVED:
                result.put("next", "ship");
                break;
            default:
                result.put("next", "none");
        }
        row.set("statusId", status.name());
        result.put("checked", checked > 0 ? checked : 0);
        return result;
    }

    public long invoiceOrder(String orderId) {
        Order order = readHelper.load(orderId);
        if (order == null) {
            return 0L;
        }
        List<InvoiceItem> items = new ArrayList<InvoiceItem>();
        for (OrderItem item : order.getItems()) {
            items.add(new InvoiceItem(item.getProductId(), item.getQuantity(), item.getUnitPriceJpy()));
        }
        return invoiceService.createInvoice(orderId, items);
    }

    public ShoppingCart cartFor(String orderId) {
        return readHelper.cartFor(orderId);
    }
}
