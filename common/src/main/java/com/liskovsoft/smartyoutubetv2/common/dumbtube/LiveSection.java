package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.ContentService;
import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItem;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.BrowseSection;
import com.liskovsoft.youtubeapi.service.YouTubeServiceManager;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import io.reactivex.Observable;

/**
 * [DumbTube] "LIVE!" sidebar section, built from the Subscriptions feed:<br/>
 * - row 1 "Live now": subscriptions that are live right now (YouTube's live flag)<br/>
 * - row 2 "Past live streams": finished streams, newest to oldest (feed order). Scrolling to the end of
 *   the row loads older pages of the feed.<br/>
 * Past streams have no flag in YouTube's data; they are recognised by YouTube's "Streamed ... ago"
 * text in the video info line. English is the reliable one; a few other languages are matched on a
 * best-effort basis ({@link #STREAMED_MARKERS}).<br/><br/>
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

    private LiveSection() {
    }

    // ---------- Hooks ----------

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

        return RxHelper.create(emitter -> {
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
        });
    }

    /**
     * Hook (BrowsePresenter.continueGroup): the past-streams row continues through the Subscriptions feed.
     */
    public static Observable<MediaGroup> continuation(MediaGroup mediaGroup, Observable<MediaGroup> upstream) {
        if (!(mediaGroup instanceof LiveGroup)) {
            return upstream;
        }

        LiveGroup group = (LiveGroup) mediaGroup;

        return RxHelper.fromCallable(() -> {
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
        });
    }

    // ---------- Classification ----------

    private static void collect(@Nullable MediaGroup page, @Nullable List<MediaItem> live, List<MediaItem> past, Set<String> seen) {
        if (page == null || page.getMediaItems() == null) {
            return;
        }

        for (MediaItem item : page.getMediaItems()) {
            if (item == null || item.getVideoId() == null || item.isUpcoming() || item.isShorts() || !seen.add(item.getVideoId())) {
                continue;
            }

            if (item.isLive()) {
                if (live != null) {
                    live.add(item);
                }
            } else if (isPastStream(item.getSecondTitle(), item.getProductionDate())) {
                past.add(item);
            }
        }
    }

    static boolean isPastStream(@Nullable CharSequence info, @Nullable String published) {
        return containsMarker(info) || containsMarker(published);
    }

    private static boolean containsMarker(@Nullable CharSequence text) {
        if (text == null || text.length() == 0) {
            return false;
        }

        String lower = text.toString().toLowerCase(Locale.ROOT);

        for (String marker : STREAMED_MARKERS) {
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
