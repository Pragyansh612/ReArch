package com.example.legacy.party;

import com.example.legacy.order.OrderReadHelper;
import jakarta.servlet.http.HttpServletRequest;

/** Already migrated to the jakarta namespace. */
public class PartyController {
    private final PartyService partyService;
    private final OrderReadHelper orderHelper;

    public PartyController(PartyService partyService, OrderReadHelper orderHelper) {
        this.partyService = partyService;
        this.orderHelper = orderHelper;
    }

    public String dashboard(HttpServletRequest request) {
        String partyId = request.getParameter("partyId");
        Party party = partyService.findParty(partyId);
        if (party == null) {
            return "error";
        }
        request.setAttribute("party", party);
        request.setAttribute("openOrders", orderHelper.getOpenOrders(partyId));
        return "success";
    }
}
