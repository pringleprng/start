package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;

/**
 * [DumbTube] Subscriptions feed autoplay order.<br/>
 * Videos started from the Subscriptions feed autoplay the next video of the feed (newest -> older,
 * loading more of the feed when needed) instead of a YouTube recommendation.<br/>
 * Implementation: forces SmartTube's own "section as playlist" mode (normally a global tweak in
 * Player settings) for videos that belong to the Subscriptions group only. Other sections keep
 * using the global tweak, i.e. behave exactly as before.<br/>
 * A video holds its feed page only weakly (Video.setGroup); normally the Subscriptions screen's adapter keeps the
 * page alive. When Android frees or reloads that screen during playback, the next video would lose its page and
 * with it the feed order, so the page of the playing feed video is kept alive here.<br/>
 * Upstream hook: first line of Video.isSectionPlaylistEnabled().
 */
public final class SubscriptionsAutoplay {
    private static final String KEY_ENABLED = "subscriptions_feed_autoplay";
    /** Feed page of the playing video (one page of data, no views). */
    private static VideoGroup sPlayingFeed;

    private SubscriptionsAutoplay() {
    }

    public static boolean isEnabled(Context context) {
        return DumbTubePrefs.instance(context).getBoolean(KEY_ENABLED, true);
    }

    public static void setEnabled(Context context, boolean enabled) {
        DumbTubePrefs.instance(context).setBoolean(KEY_ENABLED, enabled);
    }

    /**
     * Hook: true when the video was started from the Subscriptions feed and should continue with the
     * next feed item.
     */
    public static boolean isFeedOrderFor(Context context, @Nullable Video video) {
        boolean feedOrder = context != null && video != null
                && video.hasVideo()          // not a playlist/channel tile
                && !video.isRemote           // casted from a phone: keep the phone's queue
                && video.belongsToSubscriptions()
                && isEnabled(context);

        keepFeedAlive(video, feedOrder);

        return feedOrder;
    }

    private static void keepFeedAlive(@Nullable Video video, boolean feedOrder) {
        VideoGroup group = video != null ? video.getGroup() : null;

        if (feedOrder && group != null && group.getType() == MediaGroup.TYPE_SUBSCRIPTIONS) {
            sPlayingFeed = group;
        } else if (group != null) {
            sPlayingFeed = null; // playing from somewhere else now
        }
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        dialog.appendSingleSwitch(UiOptionItem.from(context.getString(R.string.dumbtube_subs_autoplay),
                option -> setEnabled(context, option.isSelected()), isEnabled(context)));
    }
}
