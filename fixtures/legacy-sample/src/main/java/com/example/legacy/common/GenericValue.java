package com.example.legacy.common;

import java.util.HashMap;
import java.util.Map;

/** Minimal stand-in for org.apache.ofbiz.entity.GenericValue. */
public class GenericValue {
    private final String entityName;
    private final Map<String, Object> fields = new HashMap<String, Object>();

    public GenericValue(String entityName) {
        this.entityName = entityName;
    }

    public String getEntityName() {
        return entityName;
    }

    public Object get(String field) {
        return fields.get(field);
    }

    public String getString(String field) {
        Object value = fields.get(field);
        return value == null ? null : value.toString();
    }

    public void set(String field, Object value) {
        fields.put(field, value);
    }
}
