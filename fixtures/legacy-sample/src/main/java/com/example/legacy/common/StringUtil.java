package com.example.legacy.common;

public final class StringUtil {
    private StringUtil() {
    }

    public static boolean isEmpty(String value) {
        return value == null || value.trim().length() == 0;
    }

    public static String normalizeId(String id) {
        if (isEmpty(id)) {
            return "";
        }
        return id.trim().toUpperCase();
    }

    public static String pad(String value, int width) {
        StringBuilder sb = new StringBuilder(value == null ? "" : value);
        while (sb.length() < width) {
            sb.append('0');
        }
        return sb.toString();
    }
}
