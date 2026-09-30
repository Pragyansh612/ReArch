package com.example.legacy.party;

public class Party {
    private final String partyId;
    private final String displayName;

    public Party(String partyId, String displayName) {
        this.partyId = partyId;
        this.displayName = displayName;
    }

    public String getPartyId() {
        return partyId;
    }

    public String getDisplayName() {
        return displayName;
    }
}
