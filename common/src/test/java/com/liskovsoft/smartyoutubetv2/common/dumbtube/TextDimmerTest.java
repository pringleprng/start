package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * [DumbTube] Color math of the text dimmer (plain JUnit, no Android needed; views: TextDimmerViewTest).
 */
public class TextDimmerTest {
    private static final int WHITE = 0xFFFFFFFF;

    @Test
    public void dimScalesRgbAndKeepsAlpha() {
        assertEquals(argb(0x80, 128, 64, 0), TextDimmer.dim(argb(0x80, 255, 128, 0), 0.5f));
        assertEquals(WHITE, TextDimmer.dim(WHITE, 1f));
        assertEquals(argb(0xFF, 77, 77, 77), TextDimmer.dim(WHITE, 0.3f));
        assertEquals(argb(0x00, 0, 0, 0), TextDimmer.dim(argb(0x00, 0, 0, 0), 0.3f));
        assertEquals(argb(0xFF, 26, 51, 77), TextDimmer.dim(argb(0xFF, 85, 170, 255), 0.3f));
    }

    private static int argb(int a, int r, int g, int b) {
        return a << 24 | r << 16 | g << 8 | b;
    }
}
