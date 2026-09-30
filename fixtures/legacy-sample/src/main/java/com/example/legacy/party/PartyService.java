package com.example.legacy.party;

import com.example.legacy.common.Delegator;
import com.example.legacy.common.EntityQuery;
import com.example.legacy.common.GenericValue;
import com.example.legacy.common.StringUtil;
import com.example.legacy.order.OrderReadHelper;
import java.util.List;

/** Party lookups through the entity engine. Calls back into order (cross-module cycle). */
public class PartyService {
    private final Delegator delegator;

    public PartyService(Delegator delegator) {
        this.delegator = delegator;
    }

    public Party findParty(String partyId) {
        String id = StringUtil.normalizeId(partyId);
        if (id.isEmpty()) {
            return null;
        }
        GenericValue value = EntityQuery.use(delegator).from("Party").where("partyId", id).queryOne();
        if (value == null) {
            return null;
        }
        return new Party(id, value.getString("groupName"));
    }

    public Party createParty(String partyId, String name) {
        GenericValue value = delegator.makeValue("Party");
        value.set("partyId", partyId);
        value.set("groupName", name);
        delegator.create(value);
        return new Party(partyId, name);
    }

    public int countOpenOrders(String partyId) {
        OrderReadHelper helper = new OrderReadHelper(delegator);
        List<GenericValue> open = helper.getOpenOrders(partyId);
        return open == null ? 0 : open.size();
    }
}
