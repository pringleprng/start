package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;

import org.junit.Test;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;

import static org.junit.Assert.assertEquals;
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
    public void detectsLiveNow() {
        // YouTube's flag
        assertTrue(LiveSection.isLiveNow(true, null, null, 0));
        // Flag missing: "LIVE" thumbnail overlay
        assertTrue(LiveSection.isLiveNow(false, "LIVE", "Some Channel • 1.2K watching", 0));
        assertTrue(LiveSection.isLiveNow(false, " live ", null, 0));
        // Flag and overlay missing: "... watching" on a video without a length
        assertTrue(LiveSection.isLiveNow(false, null, "Some Channel • 1.2K watching", 0));
    }

    @Test
    public void notLiveNow() {
        // Finished stream: has a length and says "Streamed"
        assertFalse(LiveSection.isLiveNow(false, "2:13:45", "Some Channel • 12K views • Streamed 2 days ago", 8_025_000));
        // Regular upload
        assertFalse(LiveSection.isLiveNow(false, "12:34", "Some Channel • 3K views • 2 days ago", 754_000));
        // "watching" text but the video has a length (e.g. a finished premiere)
        assertFalse(LiveSection.isLiveNow(false, "10:00", "Some Channel • 120 watching", 600_000));
        // A title-like badge that merely contains "live"
        assertFalse(LiveSection.isLiveNow(false, "LIVE AT WEMBLEY", null, 1_000));
    }

    @Test
    public void detectsUpcoming() {
        assertTrue(LiveSection.isUpcomingStream(true, null, null, 0));
        assertTrue(LiveSection.isUpcomingStream(false, "UPCOMING", null, 0));
        assertTrue(LiveSection.isUpcomingStream(false, null, "Channel • Scheduled for 11/22/26, 8:00 PM", 0));
        assertTrue(LiveSection.isUpcomingStream(false, null, "Channel • 52 waiting • Premieres 11/22/26", 0));
        // Normal upload / finished premiere with a length
        assertFalse(LiveSection.isUpcomingStream(false, "12:34", "Channel • 3K views • 2 days ago", 754_000));
        assertFalse(LiveSection.isUpcomingStream(false, "10:00", "Channel • Premiered 3 days ago", 600_000));
    }

    @Test
    public void ignoresRegularUploads() {
        assertFalse(LiveSection.isPastStream("Some Channel • 12K views • 2 days ago", "2 days ago"));
        assertFalse(LiveSection.isPastStream("Premiered 3 days ago", null));
        assertFalse(LiveSection.isPastStream(null, null));
        assertFalse(LiveSection.isPastStream("", ""));
    }

    @Test
    public void subscriptionsPageDropsAllStreams() {
        MediaItem upload = item("upload", false, "12:34", "Channel • 3K views • 2 days ago", 754_000);
        MediaItem live = item("live", true, "LIVE", "Channel • 1.2K watching", 0);
        MediaItem past = item("past", false, "2:13:45", "Channel • 12K views • Streamed 2 days ago", 8_025_000);
        MediaItem liveNoFlag = item("liveNoFlag", false, null, "Channel • 300 watching", 0);
        MediaItem upcoming = item("upcoming", false, "UPCOMING", "Channel • Scheduled for 11/22/26, 8:00 PM", 0);
        MediaItem upcomingNoBadge = item("upcomingNoBadge", false, null, "Channel • Premieres 11/22/26", 0);
        List<MediaItem> page = new ArrayList<>(Arrays.asList(live, upload, past, liveNoFlag, upcoming, upcomingNoBadge, null));

        LiveSection.removeStreams(page);

        assertEquals(Arrays.asList(upload, null), page);
    }

    @Test
    public void liveSectionSortsIntoThreeRows() {
        MediaItem upload = item("upload", false, "12:34", "Channel • 3K views • 2 days ago", 754_000);
        MediaItem live = item("live", true, "LIVE", "Channel • 1.2K watching", 0);
        MediaItem upcoming = item("upcoming", false, "UPCOMING", "Channel • Scheduled for 11/22/26, 8:00 PM", 0);
        MediaItem past = item("past", false, "2:13:45", "Channel • 12K views • Streamed 2 days ago", 8_025_000);
        List<MediaItem> liveRow = new ArrayList<>();
        List<MediaItem> upcomingRow = new ArrayList<>();
        List<MediaItem> pastRow = new ArrayList<>();

        LiveSection.classify(Arrays.asList(upload, live, upcoming, past, live), liveRow, upcomingRow, pastRow, new HashSet<>());

        assertEquals(Arrays.asList(live), liveRow); // duplicates dropped
        assertEquals(Arrays.asList(upcoming), upcomingRow);
        assertEquals(Arrays.asList(past), pastRow);
    }

    @Test
    public void readOnlyPageIsLeftAlone() {
        MediaItem past = item("past", false, "2:13:45", "Channel • Streamed 2 days ago", 8_025_000);
        List<MediaItem> page = Arrays.asList(past); // fixed-size: remove() not supported

        LiveSection.removeStreams(page);

        assertEquals(1, page.size());
    }

    /** Minimal fake feed item. */
    private static MediaItem item(String videoId, boolean live, String badge, String info, long durationMs) {
        return (MediaItem) Proxy.newProxyInstance(MediaItem.class.getClassLoader(), new Class<?>[] {MediaItem.class},
                (proxy, method, args) -> {
                    switch (method.getName()) {
                        case "getVideoId": return videoId;
                        case "isLive": return live;
                        case "getBadgeText": return badge;
                        case "getSecondTitle": return info;
                        case "getDurationMs": return durationMs;
                        case "toString": return videoId;
                        case "hashCode": return videoId.hashCode();
                        case "equals": return proxy == args[0];
                    }
                    Class<?> type = method.getReturnType();
                    if (type == boolean.class) return false;
                    if (type == int.class) return 0;
                    if (type == long.class) return 0L;
                    if (type == double.class) return 0.0;
                    return null;
                });
    }
}
