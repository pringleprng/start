package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.ContentService;
import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.youtubeapi.service.YouTubeServiceManager;
import com.liskovsoft.youtubeapi.service.internal.MediaServiceData;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import io.reactivex.Observable;

/**
 * [DumbTube] "LIVE!" sidebar section, built from the Subscriptions feed:<br/>
 * - row 1 "Live now": subscriptions that are live right now. YouTube's live flag, plus YouTube's own
 *   "LIVE" overlay / "... watching" text as a fallback, because the flag depends on a tile style value
 *   that YouTube changes from time to time ({@link #isLiveNow})<br/>
 * - row 2 "Past live streams": finished streams, newest to oldest (feed order). Scrolling to the end of
 *   the row loads older pages of the feed.<br/>
 * Past streams have no flag in YouTube's data; they are recognised by YouTube's "Streamed ... ago"
 * text in the video info line. English is the reliable one; a few other languages are matched on a
 * best-effort basis ({@link #STREAMED_MARKERS}).<br/>
 * SmartTube's "hide streams in Subscriptions" filter would drop the live items before we see them, so
 * it is lifted while this section loads ({@link #withLiveStreamsVisible}).<br/>
 * Optionally (default on) the normal Subscriptions page drops all streams, live and finished, since
 * they are here ({@link #hideStreams}). This section itself always shows them.<br/><br/>
 * Upstream hooks: BrowsePresenter initSectionMapping()/initRowAndGridMapping()/continueGroup(),
 * SidebarService.initSections(). Enabled once in the sidebar by {@link DumbTubeDefaults}.
 */
public final class LiveSection {
    /** Sidebar/section id. Below SidebarService.RESERVED_ID (100), far from MediaGroup.TYPE_* (0-22). */
    public static final int SECTION_ID = 77;
    private static final int FIRST_LOAD_MAX_PAGES = 6;
    private static final int FIRST_LOAD_TARGET = 30;
    private static final int MORE_MAX_PAGES = 12;
    private static final int MORE_TARGET = 20;
    private static final String NEXT_KEY_MARKER = "dumbtube_live_more";
    private static final String KEY_HIDE_STREAMS_IN_SUBSCRIPTIONS = "subs_hide_streams";
    /** Lower case. "Streamed 2 days ago" in YouTube's UI languages (English is the tested one). */
    static final String[] STREAMED_MARKERS = {
            "streamed",         // en
            "live übertragen",  // de
            "diffusé",          // fr
            "emitido",          // es
            "transmitido",      // pt
            "trasmesso",        // it
            "gestreamd",        // nl
            "transmitowan",     // pl
            "трансляция",       // ru
            "трансляція",       // uk
            "配信済み",           // ja
            "스트리밍",            // ko
    };
    /** Lower case, exact match. Thumbnail overlay text of a live video. */
    static final String[] LIVE_BADGES = {
            "live", "live now", "en direct", "en vivo", "ao vivo", "in diretta", "na żywo",
            "в эфире", "прямой эфир", "наживо", "ライブ", "실시간"
    };
    /** Lower case. "1.2K watching" in the info line of a live video. */
    static final String[] WATCHING_MARKERS = {
            "watching",         // en
            "zuschauer",        // de
            "spectateurs",      // fr
            "espectadores",     // es
            "assistindo",       // pt
            "spettatori",       // it
            "kijkers",          // nl
            "oglądających",     // pl
            "смотрят",          // ru
            "дивляться",        // uk
            "視聴中",             // ja
            "시청 중",            // ko
    };

    private LiveSection() {
    }

    // ---------- Settings ----------

    public static boolean isHideStreamsInSubscriptions(Context context) {
        return DumbTubePrefs.instance(context).getBoolean(KEY_HIDE_STREAMS_IN_SUBSCRIPTIONS, true);
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        dialog.appendSingleSwitch(UiOptionItem.from(context.getString(R.string.dumbtube_subs_hide_streams),
                option -> DumbTubePrefs.instance(context).setBoolean(KEY_HIDE_STREAMS_IN_SUBSCRIPTIONS, option.isSelected()),
                isHideStreamsInSubscriptions(context)));
    }

    // ---------- Hooks ----------

    /**
     * Hook (BrowsePresenter.initRowAndGridMapping): the Subscriptions page without live and finished streams.
     * Items are removed in place (like SmartTube's own Shorts filter), so the group keeps its type and
     * its continuation still works.
     */
    public static Observable<MediaGroup> hideStreams(Context context, Observable<MediaGroup> subscriptions) {
        if (subscriptions == null || context == null) {
            return subscriptions;
        }

        Context appContext = context.getApplicationContext();

        return subscriptions.map(group -> {
            removeStreams(appContext, group);
            return group;
        });
    }

    /**
     * Hook (BrowsePresenter.initSectionMapping).
     */
    public static BrowseSection createSection(Context context) {
        return new BrowseSection(SECTION_ID, context.getString(R.string.dumbtube_live_section),
                BrowseSection.TYPE_ROW, R.drawable.dumbtube_icon_live_subs, true);
    }

    /**
     * Hook (BrowsePresenter.initRowAndGridMapping). Emits "Live now" as soon as the first page is in,
     * then "Past live streams".
     */
    public static Observable<List<MediaGroup>> rowsObserve(Context context) {
        String liveTitle = context.getString(R.string.dumbtube_live_now);
        String pastTitle = context.getString(R.string.dumbtube_live_past);

        return RxHelper.create(emitter -> withLiveStreamsVisible(() -> {
            ContentService service = YouTubeServiceManager.instance().getContentService();
            MediaGroup page = service.getSubscriptions();
            Set<String> seen = new HashSet<>();
            List<MediaItem> live = new ArrayList<>();
            List<MediaItem> past = new ArrayList<>();

            collect(page, live, past, seen);

            // Live streams sit at the top of the feed: show them right away
            boolean liveShown = !live.isEmpty();
            if (liveShown) {
                List<MediaGroup> rows = new ArrayList<>();
                rows.add(new LiveGroup(liveTitle, live, null));
                emitter.onNext(rows);
            }

            int pages = 1;
            while (page != null && past.size() < FIRST_LOAD_TARGET && pages < FIRST_LOAD_MAX_PAGES) {
                page = service.continueGroup(page);
                pages++;
                collect(page, liveShown ? null : live, past, seen);
            }

            List<MediaGroup> rows = new ArrayList<>();
            if (!liveShown && !live.isEmpty()) {
                rows.add(new LiveGroup(liveTitle, live, null));
            }
            if (!past.isEmpty()) {
                rows.add(new LiveGroup(pastTitle, past, page));
            }
            if (!rows.isEmpty()) {
                emitter.onNext(rows);
            }
            emitter.onComplete();
            return null;
        }));
    }

    /**
     * Hook (BrowsePresenter.continueGroup): the past-streams row continues through the Subscriptions feed.
     */
    public static Observable<MediaGroup> continuation(Context context, MediaGroup mediaGroup, Observable<MediaGroup> upstream) {
        if (mediaGroup != null && !(mediaGroup instanceof LiveGroup)
                && mediaGroup.getType() == MediaGroup.TYPE_SUBSCRIPTIONS && upstream != null && context != null) {
            // Next pages of the normal Subscriptions page
            Context appContext = context.getApplicationContext();
            return upstream.map(group -> {
                removeStreams(appContext, group);
                return group;
            });
        }

        if (!(mediaGroup instanceof LiveGroup)) {
            return upstream;
        }

        LiveGroup group = (LiveGroup) mediaGroup;

        return RxHelper.fromCallable(() -> withLiveStreamsVisible(() -> {
            if (group.mCursor == null) {
                return null; // end of the feed (or the live row)
            }

            ContentService service = YouTubeServiceManager.instance().getContentService();
            MediaGroup page = group.mCursor;
            Set<String> seen = new HashSet<>(group.mSeen);
            List<MediaItem> past = new ArrayList<>();

            for (int pages = 0; page != null && past.size() < MORE_TARGET && pages < MORE_MAX_PAGES; pages++) {
                page = service.continueGroup(page);
                collect(page, null, past, seen);
            }

            if (past.isEmpty()) {
                return null;
            }

            LiveGroup more = new LiveGroup(group.mTitle, past, page);
            more.mSeen.addAll(seen);
            return more;
        }));
    }

    private interface Loader<T> {
        T load() throws Exception;
    }

    /**
     * Runs the loader with SmartTube's "hide streams in Subscriptions" content filter switched off, so the
     * live items reach us, then puts the user's setting back.
     */
    private static <T> T withLiveStreamsVisible(Loader<T> loader) throws Exception {
        MediaServiceData data = MediaServiceData.instance();
        boolean hidden = data != null && data.isContentHidden(MediaServiceData.CONTENT_STREAMS_SUBSCRIPTIONS);

        if (hidden) {
            data.setContentHidden(MediaServiceData.CONTENT_STREAMS_SUBSCRIPTIONS, false);
        }

        try {
            return loader.load();
        } finally {
            if (hidden) {
                data.setContentHidden(MediaServiceData.CONTENT_STREAMS_SUBSCRIPTIONS, true);
            }
        }
    }

    // ---------- Classification ----------

    static void removeStreams(Context context, @Nullable MediaGroup group) {
        if (group == null || !isHideStreamsInSubscriptions(context)) {
            return;
        }

        removeStreams(group.getMediaItems());
    }

    /**
     * Removes live and finished streams. Normal uploads and upcoming streams stay.
     */
    static void removeStreams(@Nullable List<MediaItem> items) {
        if (items == null) {
            return;
        }

        try {
            for (Iterator<MediaItem> iterator = items.iterator(); iterator.hasNext(); ) {
                MediaItem item = iterator.next();
                if (item != null
                        && (isLiveNow(item.isLive(), item.getBadgeText(), item.getSecondTitle(), item.getDurationMs())
                            || isPastStream(item.getSecondTitle(), item.getProductionDate()))) {
                    iterator.remove();
                }
            }
        } catch (UnsupportedOperationException e) {
            // Read-only list: leave the page as it is
        }
    }

    private static void collect(@Nullable MediaGroup page, @Nullable List<MediaItem> live, List<MediaItem> past, Set<String> seen) {
        if (page == null || page.getMediaItems() == null) {
            return;
        }

        for (MediaItem item : page.getMediaItems()) {
            if (item == null || item.getVideoId() == null || item.isUpcoming() || item.isShorts() || !seen.add(item.getVideoId())) {
                continue;
            }

            if (isLiveNow(item.isLive(), item.getBadgeText(), item.getSecondTitle(), item.getDurationMs())) {
                if (live != null) {
                    live.add(item);
                }
            } else if (isPastStream(item.getSecondTitle(), item.getProductionDate())) {
                past.add(item);
            }
        }
    }

    /**
     * Live right now: YouTube's flag, or the "LIVE" thumbnail overlay, or "... watching" on a video
     * without a length (finished streams have a length and say "Streamed ...").
     */
    static boolean isLiveNow(boolean liveFlag, @Nullable String badge, @Nullable CharSequence info, long durationMs) {
        if (liveFlag) {
            return true;
        }

        if (badge != null) {
            String lowerBadge = badge.trim().toLowerCase(Locale.ROOT);
            for (String liveBadge : LIVE_BADGES) {
                if (lowerBadge.equals(liveBadge)) {
                    return true;
                }
            }
        }

        return durationMs <= 0 && containsAny(info, WATCHING_MARKERS) && !containsAny(info, STREAMED_MARKERS);
    }

    static boolean isPastStream(@Nullable CharSequence info, @Nullable String published) {
        return containsAny(info, STREAMED_MARKERS) || containsAny(published, STREAMED_MARKERS);
    }

    private static boolean containsAny(@Nullable CharSequence text, String[] markers) {
        if (text == null || text.length() == 0) {
            return false;
        }

        String lower = text.toString().toLowerCase(Locale.ROOT);

        for (String marker : markers) {
            if (lower.contains(marker)) {
                return true;
            }
        }

        return false;
    }

    /**
     * A row of the LIVE! section. Keeps the Subscriptions page to continue from.
     */
    static final class LiveGroup implements MediaGroup {
        private final String mTitle;
        private final List<MediaItem> mItems;
        @Nullable
        private final MediaGroup mCursor;
        private final Set<String> mSeen = new HashSet<>();

        LiveGroup(String title, List<MediaItem> items, @Nullable MediaGroup cursor) {
            mTitle = title;
            mItems = items;
            mCursor = cursor;
            for (MediaItem item : items) {
                mSeen.add(item.getVideoId());
            }
        }

        @Override
        public int getType() {
            return SECTION_ID;
        }

        @Nullable
        @Override
        public List<MediaItem> getMediaItems() {
            return mItems;
        }

        @Override
        public String getTitle() {
            return mTitle;
        }

        @Override
        public String getChannelId() {
            return null;
        }

        @Override
        public String getParams() {
            return null;
        }

        @Override
        public String getReloadPageKey() {
            return null;
        }

        @Override
        public String getNextPageKey() {
            return mCursor != null ? NEXT_KEY_MARKER : null;
        }

        @Override
        public String getChannelUrl() {
            return null;
        }

        @Override
        public boolean isEmpty() {
            return mItems == null || mItems.isEmpty();
        }
    }
}
