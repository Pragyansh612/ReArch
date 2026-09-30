package com.example.legacy.billing;

import com.example.legacy.common.StringUtil;
import com.example.legacy.order.OrderReadHelper;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import javax.sql.DataSource;

/** Business logic talking straight to the database over JDBC. */
public class InvoiceService {
    private final String url;
    private final PaymentCalculator calculator = new PaymentCalculator();
    private DataSource unusedPool;

    public InvoiceService(String url) {
        this.url = url;
    }

    public long createInvoice(String orderId, List<InvoiceItem> items) {
        if (StringUtil.isEmpty(orderId) || items.isEmpty()) {
            throw new BillingException("nothing to invoice", null);
        }
        long total = calculator.withTax(calculator.total(items), 10);
        try (Connection conn = DriverManager.getConnection(url)) {
            PreparedStatement insert = conn.prepareStatement(
                    "INSERT INTO INVOICE (ORDER_ID, TOTAL_JPY) VALUES (?, ?)");
            insert.setString(1, orderId);
            insert.setLong(2, total);
            insert.executeUpdate();
            for (InvoiceItem item : items) {
                PreparedStatement line = conn.prepareStatement(
                        "INSERT INTO INVOICE_ITEM (ORDER_ID, PRODUCT_ID, QTY) VALUES (?, ?, ?)");
                line.setString(1, orderId);
                line.setString(2, item.getProductId());
                line.setInt(3, item.getQuantity());
                line.executeUpdate();
            }
        } catch (SQLException e) {
            throw new BillingException("invoice failed for " + orderId, e);
        }
        return total;
    }

    public List<String> overdueInvoiceIds(int days) {
        List<String> ids = new ArrayList<String>();
        try (Connection conn = DriverManager.getConnection(url)) {
            PreparedStatement query = conn.prepareStatement(
                    "SELECT ORDER_ID FROM INVOICE WHERE AGE_DAYS > ?");
            query.setInt(1, days);
            ResultSet rs = query.executeQuery();
            while (rs.next()) {
                ids.add(rs.getString(1));
            }
        } catch (SQLException e) {
            throw new BillingException("overdue query failed", e);
        }
        return ids;
    }

    public boolean isOrderBillable(String orderId) {
        OrderReadHelper helper = new OrderReadHelper(null);
        return helper.isOpen(orderId);
    }
}
