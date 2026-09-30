package com.example.legacy.common;

import java.util.List;
import java.util.Map;

/** Minimal stand-in for org.apache.ofbiz.entity.Delegator. */
public interface Delegator {
    GenericValue makeValue(String entityName);

    void create(GenericValue value);

    GenericValue findOne(String entityName, Map<String, Object> keys);

    List<GenericValue> findList(String entityName, Map<String, Object> conditions);
}
