package com.example.legacy.billing;

import java.util.List;

/**
 * Pure calculation, no database access. Collaborates with InvoiceService only by contract:
 * never call prepareStatement( from here, and never use EntityQuery.use( either.
 */
public class PaymentCalculator {
    private static final String NOTE = "see EntityQuery.use( and conn.prepareStatement( docs";

    public long total(List<InvoiceItem> items) {
        long sum = 0;
        for (InvoiceItem item : items) {
            sum += item.getUnitPriceJpy() * item.getQuantity();
        }
        return sum;
    }

    public long withTax(long subtotal, int percent) {
        return subtotal + subtotal * percent / 100;
    }

    public String note() {
        return NOTE;
    }
}
