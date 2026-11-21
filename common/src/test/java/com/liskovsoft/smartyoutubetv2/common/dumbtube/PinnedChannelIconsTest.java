package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

/**
 * [DumbTube] Which pinned-channel icons are video thumbnails (plain JUnit, no Android needed).
 */
public class PinnedChannelIconsTest {
    @Test
    public void findsVideoThumbnails() {
        assertEquals("dQw4w9WgXcQ", PinnedChannelIcons.getThumbnailVideoId("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"));
        assertEquals("dQw4w9WgXcQ", PinnedChannelIcons.getThumbnailVideoId("https://i.ytimg.com/vi_webp/dQw4w9WgXcQ/mqdefault.webp"));
        assertEquals("a-b_c1234XY", PinnedChannelIcons.getThumbnailVideoId("https://i9.ytimg.com/vi/a-b_c1234XY/hqdefault_live.jpg?sqp=abc"));
    }

    @Test
    public void leavesChannelIconsAlone() {
        assertNull(PinnedChannelIcons.getThumbnailVideoId("https://yt3.ggpht.com/ytc/AIdro_abc=s176-c-k-c0x00ffffff-no-rj"));
        assertNull(PinnedChannelIcons.getThumbnailVideoId("https://yt3.googleusercontent.com/abc=s88-c-k-c0x00ffffff-no-rj"));
        assertNull(PinnedChannelIcons.getThumbnailVideoId(null));
        assertNull(PinnedChannelIcons.getThumbnailVideoId(""));
    }
}
