package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * [DumbTube] Past live stream detection used by the LIVE! section (plain JUnit, no Android needed).
 */
public class LiveSectionTest {
    @Test
    public void detectsPastStreams() {
        assertTrue(LiveSection.isPastStream("Some Channel • 12K views • Streamed 2 days ago", null));
        assertTrue(LiveSection.isPastStream(null, "Streamed 3 hours ago"));
        assertTrue(LiveSection.isPastStream("1.2K views • STREAMED 1 week ago", null));
        assertTrue(LiveSection.isPastStream("Kanal • 500 Aufrufe • Vor 2 Tagen live übertragen", null));
        assertTrue(LiveSection.isPastStream("Chaîne • 3 k vues • Diffusé il y a 2 jours", null));
        assertTrue(LiveSection.isPastStream("Canal • 1 mil visualizações • Transmitido há 2 dias", null));
    }

    @Test
    public void ignoresRegularUploads() {
        assertFalse(LiveSection.isPastStream("Some Channel • 12K views • 2 days ago", "2 days ago"));
        assertFalse(LiveSection.isPastStream("Premiered 3 days ago", null));
        assertFalse(LiveSection.isPastStream(null, null));
        assertFalse(LiveSection.isPastStream("", ""));
    }
}
