package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemMetadata;
import com.liskovsoft.sharedutils.prefs.GlobalPreferences;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Playlist;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.controllers.SuggestionsController;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

/**
 * [DumbTube] Subscriptions feed autoplay through SmartTube's real SuggestionsController code: a feed page
 * (filtered by LIVE!'s stream hiding, like BrowsePresenter does), the player holding a copy of the clicked
 * card, metadata synced, then "what plays next". Robolectric (JDK 11, see dumbtube-check.yml).
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class SubscriptionsAutoplayFlowTest {
    private Context mContext;

    @Before
    public void setUp() {
        mContext = RuntimeEnvironment.application;
        GlobalPreferences.instance(mContext); // the app does this at start (VideoGroup reads it)
        Playlist.instance().clear();
    }

    @After
    public void tearDown() {
        Playlist.instance().clear();
    }

    @Test
    public void nextFeedVideoPlaysNext() throws Exception {
        VideoGroup feed = feed(upload("a"), upload("b"), upload("c"));

        assertEquals("b", nextAfter(Video.from(feed.getVideos().get(0))));
        assertEquals("c", nextAfter(Video.from(feed.getVideos().get(1))));
    }

    @Test
    public void sameCardInstanceWorksToo() throws Exception {
        VideoGroup feed = feed(upload("a"), upload("b"));

        assertEquals("b", nextAfter(feed.getVideos().get(0)));
    }

    @Test
    public void hiddenStreamsAreSkipped() throws Exception {
        VideoGroup feed = feed(upload("a"), liveNow("live"), upload("c"));

        assertEquals(2, feed.getVideos().size());
        assertEquals("c", nextAfter(Video.from(feed.getVideos().get(0))));
    }

    @Test
    public void playedBeforeStillContinuesInFeedOrder() throws Exception {
        VideoGroup feed = feed(upload("a"), upload("b"), upload("c"));

        // Watch a, then b (autoplay), then start a again from the feed
        nextAfter(Video.from(feed.getVideos().get(0)));
        nextAfter(Video.from(feed.getVideos().get(1)));
        assertEquals("b", nextAfter(Video.from(feed.getVideos().get(0))));
    }

    /**
     * Opens the video like VideoLoaderController.onNewVideo + loadVideo, syncs its metadata and appends the
     * suggestions like SuggestionsController.updateSuggestions, then asks for the next video.
     */
    private String nextAfter(Video playing) throws Exception {
        Playlist.instance().add(playing);
        Playlist.instance().setCurrent(playing);

        TestController controller = new TestController(playing, mContext);
        MediaItemMetadata metadata = proxy(MediaItemMetadata.class, new HashMap<>());
        playing.sync(metadata);

        Method append = SuggestionsController.class.getDeclaredMethod("appendSuggestions", Video.class, MediaItemMetadata.class);
        append.setAccessible(true);
        append.invoke(controller, playing, metadata);

        Video next = controller.getNext();
        assertNotNull("nothing would play next", next);
        return next.videoId;
    }

    private VideoGroup feed(MediaItem... items) {
        List<MediaItem> list = new ArrayList<>(Arrays.asList(items));
        Map<String, Object> values = new HashMap<>();
        values.put("getType", MediaGroup.TYPE_SUBSCRIPTIONS);
        values.put("getMediaItems", list);
        values.put("getTitle", "Subscriptions");
        MediaGroup group = proxy(MediaGroup.class, values);

        LiveSection.removeStreams(mContext, group); // BrowsePresenter: LiveSection.hideStreams(...)

        return VideoGroup.from(group, null, 0);
    }

    private static MediaItem upload(String videoId) {
        Map<String, Object> values = new HashMap<>();
        values.put("getVideoId", videoId);
        values.put("getTitle", videoId);
        values.put("getSecondTitle", "Channel • 1K views • 2 hours ago");
        values.put("getDurationMs", 600_000L);
        return proxy(MediaItem.class, values);
    }

    private static MediaItem liveNow(String videoId) {
        Map<String, Object> values = new HashMap<>();
        values.put("getVideoId", videoId);
        values.put("getTitle", videoId);
        values.put("isLive", true);
        values.put("getBadgeText", "LIVE");
        return proxy(MediaItem.class, values);
    }

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, Map<String, Object> values) {
        return (T) Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, (proxy, method, args) -> {
            if (values.containsKey(method.getName())) {
                return values.get(method.getName());
            }
            if (method.getName().equals("hashCode")) {
                return System.identityHashCode(proxy);
            }
            if (method.getName().equals("equals")) {
                return proxy == args[0];
            }
            return defaultValue(method.getReturnType());
        });
    }

    private static Object defaultValue(Class<?> type) {
        if (type == boolean.class) return false;
        if (type == int.class) return 0;
        if (type == long.class) return 0L;
        if (type == float.class) return 0f;
        if (type == double.class) return 0d;
        if (type == short.class) return (short) 0;
        if (type == byte.class) return (byte) 0;
        if (type == char.class) return (char) 0;
        return null;
    }

    private static class TestController extends SuggestionsController {
        private final PlaybackView mPlayer = proxy(PlaybackView.class, new HashMap<>());
        private final Video mVideo;
        private final Context mContext;

        TestController(Video video, Context context) {
            mVideo = video;
            mContext = context;
        }

        @Override
        public PlaybackView getPlayer() {
            return mPlayer;
        }

        @Override
        public Video getVideo() {
            return mVideo;
        }

        @Override
        public Context getContext() {
            return mContext;
        }
    }
}
