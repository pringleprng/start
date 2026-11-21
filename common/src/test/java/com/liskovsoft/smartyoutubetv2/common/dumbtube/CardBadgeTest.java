package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * [DumbTube] Card badge color keys (plain JUnit, no Android needed; views: CardBadgeViewTest).
 */
public class CardBadgeTest {
    @Test
    public void colorKeys() {
        assertEquals(0xFF000000, CardBadge.colorOf(CardBadge.COLOR_BLACK));
        assertEquals(0xFFBDBDBD, CardBadge.colorOf("light_grey"));
        assertEquals(0xFFBDBDBD, CardBadge.colorOf("no_such_color")); // falls back to the default outline
    }
}
