package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import com.liskovsoft.mediaserviceinterfaces.MediaItemService;
import com.liskovsoft.mediaserviceinterfaces.data.MediaItemMetadata;
import com.liskovsoft.sharedutils.mylogger.Log;
import com.liskovsoft.sharedutils.rx.RxHelper;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.BrowsePresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.service.SidebarService;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;
import com.liskovsoft.youtubeapi.service.YouTubeServiceManager;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * [DumbTube] Channels pinned to the sidebar from a video use the channel's icon (avatar), not the video's thumbnail.<br/>
 * SmartTube builds the pinned item from the video (BaseMenuPresenter.createPinnedChannel), so the item keeps the
 * video thumbnail, and the sidebar shows that as the channel's icon.<br/>
 * - new pins: the avatar from the video's metadata (the one the player shows next to the channel name) replaces it<br/>
 * - pins made before: fixed once in the background a few seconds after start, one metadata request per pin. The
 *   sidebar is then rebuilt the way SmartTube does after moving or renaming a pin, keeping the current section.<br/><br/>
 * Upstream hook: BaseMenuPresenter.appendTogglePinVideoToSidebarButton() -&gt; {@link #useChannelIcon}.
 * The repair starts from {@link DumbTubeDefaults#applyOnce} (MotherActivity.onCreate()).
 */
public final class PinnedChannelIcons {
    private static final String TAG = PinnedChannelIcons.class.getSimpleName();
    // i.ytimg.com/vi/<id>/hqdefault.jpg, /vi_webp/<id>/..., also the live variants
    private static final Pattern VIDEO_THUMBNAIL = Pattern.compile("/vi(?:_webp)?/([A-Za-z0-9_-]{11})/");
    private static final long REPAIR_DELAY_MS = 10_000; // let the app sign in and load the first section first
    private static boolean sRepairStarted;

    private PinnedChannelIcons() {
    }

    /**
     * Hook: before the pinned channel is created from this (synced) copy of the video.
     */
    public static void useChannelIcon(Video video, MediaItemMetadata metadata) {
        if (video == null || metadata == null) {
            return;
        }

        String icon = metadata.getAuthorImageUrl();

        if (icon == null || icon.isEmpty()) {
            return; // keep SmartTube's thumbnail rather than no icon
        }

        video.cardImageUrl = icon;
        video.altCardImageUrl = null; // a DeArrow thumbnail would win in getCardImageUrl()
    }

    /**
     * Fix channels pinned before this fix, once per app start (only pins that still show a video thumbnail).
     */
    public static void repairOnce(Context context) {
        if (sRepairStarted || context == null) {
            return;
        }

        sRepairStarted = true;
        Context appContext = context.getApplicationContext();
        Utils.postDelayed(() -> repair(appContext), REPAIR_DELAY_MS);
    }

    static boolean needsRepair(Video item) {
        return item != null && item.sectionId == -1 && item.channelId != null && !item.hasPlaylist()
                && getThumbnailVideoId(item.cardImageUrl) != null;
    }

    static String getThumbnailVideoId(String url) {
        if (url == null) {
            return null;
        }

        Matcher matcher = VIDEO_THUMBNAIL.matcher(url);
        return matcher.find() ? matcher.group(1) : null;
    }

    private static void repair(Context context) {
        SidebarService sidebar = SidebarService.instance(context);

        if (sidebar == null) {
            return;
        }

        List<Video> items = new ArrayList<>();

        for (Video item : sidebar.getPinnedItems()) {
            if (needsRepair(item)) {
                items.add(item);
            }
        }

        if (!items.isEmpty()) {
            repairNext(context, YouTubeServiceManager.instance().getMediaItemService(), items.iterator(), false);
        }
    }

    /**
     * One request at a time, so it doesn't compete with what the user is loading.
     */
    private static void repairNext(Context context, MediaItemService service, Iterator<Video> items, boolean changed) {
        if (!items.hasNext()) {
            if (changed) {
                SidebarService.instance(context).persistState();
                BrowsePresenter.instance(context).updateSections(); // no-op while the browse screen isn't open
            }
            return;
        }

        Video item = items.next();
        boolean[] fixed = {false};

        RxHelper.execute(service.getMetadataObserve(getThumbnailVideoId(item.cardImageUrl)),
                metadata -> {
                    // Only if the video still belongs to that channel
                    if (metadata != null && item.channelId.equals(metadata.getChannelId())) {
                        String before = item.cardImageUrl;
                        useChannelIcon(item, metadata);
                        fixed[0] = !before.equals(item.cardImageUrl);
                    }
                },
                error -> {
                    Log.e(TAG, "Channel icon of %s: %s", item.getTitle(), error.getMessage());
                    repairNext(context, service, items, changed); // tried again on the next start
                },
                () -> repairNext(context, service, items, changed || fixed[0]));
    }
}
