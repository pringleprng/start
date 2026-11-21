package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;

/**
 * [DumbTube] Subscriptions feed autoplay order.<br/>
 * Videos started from the Subscriptions feed autoplay the next video of the feed (newest -> older,
 * loading more of the feed when needed) instead of a YouTube recommendation.<br/>
 * Implementation: forces SmartTube's own "section as playlist" mode (normally a global tweak in
 * Player settings) for videos that belong to the Subscriptions group only. Other sections keep
 * using the global tweak, i.e. behave exactly as before.<br/>
 * Upstream hook: first line of Video.isSectionPlaylistEnabled().
 */
public final class SubscriptionsAutoplay {
    private static final String KEY_ENABLED = "subscriptions_feed_autoplay";

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
        return context != null && video != null
                && video.hasVideo()          // not a playlist/channel tile
                && !video.isRemote           // casted from a phone: keep the phone's queue
                && video.belongsToSubscriptions()
                && isEnabled(context);
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        dialog.appendSingleSwitch(UiOptionItem.from(context.getString(R.string.dumbtube_subs_autoplay),
                option -> setEnabled(context, option.isSelected()), isEnabled(context)));
    }
}
