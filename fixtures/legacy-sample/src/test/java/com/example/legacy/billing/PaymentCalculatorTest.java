package com.example.legacy.billing;

import static org.junit.Assert.assertEquals;

import java.util.Arrays;
import org.junit.Test;

public class PaymentCalculatorTest {
    @Test
    public void totalsLines() {
        PaymentCalculator calc = new PaymentCalculator();
        long total = calc.total(Arrays.asList(new InvoiceItem("A", 2, 100L)));
        assertEquals(200L, total);
    }
}
