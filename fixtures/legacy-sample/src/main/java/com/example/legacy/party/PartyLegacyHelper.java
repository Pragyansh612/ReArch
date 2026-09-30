package com.example.legacy.party;

import javax.servlet.http.HttpServletRequest;

/** Not yet migrated: still on the javax namespace, next to a jakarta class in the same module. */
public class PartyLegacyHelper {
    public String partyIdFrom(HttpServletRequest request) {
        String fromParam = request.getParameter("partyId");
        if (fromParam != null) {
            return fromParam;
        }
        return (String) request.getAttribute("partyId");
    }

    public Party anonymous() {
        return new Party("_NA_", "Anonymous");
    }
}
