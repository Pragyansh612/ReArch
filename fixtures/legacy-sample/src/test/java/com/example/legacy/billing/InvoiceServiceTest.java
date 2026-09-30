package com.example.legacy.billing;

import static org.junit.Assert.assertTrue;

import java.util.Collections;
import org.junit.Test;

public class InvoiceServiceTest {
    @Test(expected = BillingException.class)
    public void rejectsEmptyInvoice() {
        new InvoiceService("jdbc:hsqldb:mem:t").createInvoice("O1", Collections.<InvoiceItem>emptyList());
    }
}
