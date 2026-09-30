package com.example.legacy.billing;

public class BillingException extends RuntimeException {
    public BillingException(String message, Throwable cause) {
        super(message, cause);
    }
}
