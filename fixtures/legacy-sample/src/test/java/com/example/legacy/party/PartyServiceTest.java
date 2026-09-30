package com.example.legacy.party;

import static org.junit.Assert.assertNull;

import org.junit.Test;

public class PartyServiceTest {
    @Test
    public void blankIdFindsNothing() {
        assertNull(new PartyService(null).findParty(" "));
    }
}
