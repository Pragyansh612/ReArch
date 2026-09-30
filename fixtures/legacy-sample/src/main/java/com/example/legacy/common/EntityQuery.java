package com.example.legacy.common;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Minimal stand-in for org.apache.ofbiz.entity.util.EntityQuery (fluent builder). */
public class EntityQuery {
    private final Delegator delegator;
    private String entityName;
    private final Map<String, Object> conditions = new HashMap<String, Object>();

    private EntityQuery(Delegator delegator) {
        this.delegator = delegator;
    }

    public static EntityQuery use(Delegator delegator) {
        return new EntityQuery(delegator);
    }

    public EntityQuery from(String entityName) {
        this.entityName = entityName;
        return this;
    }

    public EntityQuery where(String field, Object value) {
        conditions.put(field, value);
        return this;
    }

    public GenericValue queryOne() {
        return delegator.findOne(entityName, conditions);
    }

    public List<GenericValue> queryList() {
        return delegator.findList(entityName, conditions);
    }
}
