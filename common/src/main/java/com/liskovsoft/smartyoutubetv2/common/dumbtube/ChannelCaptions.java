package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.annotation.SuppressLint;
import android.content.Context;
import android.text.TextUtils;

import androidx.annotation.Nullable;

import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.PlaybackPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.views.PlaybackView;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.ExoFormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.FormatItem;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.TrackSelectorManager;
import com.liskovsoft.smartyoutubetv2.common.exoplayer.selector.track.SubtitleTrack;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * [DumbTube] Per-channel captions.<br/>
 * For every channel we remember: captions on/off and the caption track that was picked. The track
 * covers both "caption language" (a normal track, e.g. "English") and "auto-translate target"
 * (one of SmartTube's auto/translated tracks, marked with '*', e.g. "German*").<br/>
 * Channels without saved settings use the DumbTube global default.<br/><br/>
 * Upstream hooks (one line each):<br/>
 * - VideoStateController.restoreSubtitleFormat(): {@link #resolve}<br/>
 * - PlayerUIController subtitle button/dialog: {@link #onUserSelected}, {@link #preferSaved},
 *   {@link #appendPlayerOptions}<br/>
 * - ErrorFixerController.disableSubtitles(): {@link #suspendFor}
 */
public final class ChannelCaptions {
    private static final String KEY_ENABLED = "channel_captions_enabled";
    private static final String KEY_CHANNELS = "channel_captions_data";
    private static final String KEY_DEFAULT = "channel_captions_default";
    private static final int MAX_CHANNELS = 2000;
    private static final String FIELD_DELIM = "\t";
    private static final String LINE_DELIM = "\n";
    private static final String FALLBACK_FORMAT_ID = "dumbtube";
    @SuppressLint("StaticFieldLeak")
    private static ChannelCaptions sInstance;
    private final Context mContext;
    private final DumbTubePrefs mPrefs;
    private final LinkedHashMap<String, Entry> mChannels = new LinkedHashMap<>();
    private Entry mDefault;
    private boolean mLoaded;
    private String mSuspendedVideoId;

    /**
     * Saved captions state of one channel (or of the global default).
     */
    static final class Entry {
        boolean enabled;
        String language; // track label as shown by SmartTube, e.g. "English", "German*"
        String formatId;
        String codecs;

        static Entry from(FormatItem format) {
            Entry entry = new Entry();
            entry.update(format);
            return entry;
        }

        void update(FormatItem format) {
            if (format == null || format.isDefault() || format.getLanguage() == null) {
                enabled = false; // keep the last language so that "on" restores it
                return;
            }

            enabled = true;
            language = format.getLanguage();
            formatId = format.getFormatId();
            codecs = format.getTrack() != null && format.getTrack().format != null ? format.getTrack().format.codecs : null;
        }

        FormatItem toFormat() {
            if (!enabled || TextUtils.isEmpty(language)) {
                return FormatItem.SUBTITLE_NONE;
            }

            FormatItem format = ExoFormatItem.from(FormatItem.TYPE_SUBTITLE, TrackSelectorManager.RENDERER_INDEX_SUBTITLE,
                    TextUtils.isEmpty(formatId) ? FALLBACK_FORMAT_ID : formatId, codecs, -1, -1, -1, language, false, -1, false);

            return format != null ? format : FormatItem.SUBTITLE_NONE;
        }

        String serialize(String key) {
            return TextUtils.join(FIELD_DELIM, new String[] {
                    clean(key), String.valueOf(enabled), clean(language), clean(formatId), clean(codecs)});
        }

        @Nullable
        static Entry parse(String[] fields) {
            if (fields.length < 3) {
                return null;
            }

            Entry entry = new Entry();
            entry.enabled = Boolean.parseBoolean(fields[1]);
            entry.language = emptyToNull(fields[2]);
            entry.formatId = fields.length > 3 ? emptyToNull(fields[3]) : null;
            entry.codecs = fields.length > 4 ? emptyToNull(fields[4]) : null;
            return entry;
        }

        private static String clean(String value) {
            return value == null ? "" : value.replace(FIELD_DELIM, " ").replace(LINE_DELIM, " ");
        }

        private static String emptyToNull(String value) {
            return value == null || value.isEmpty() ? null : value;
        }
    }

    private ChannelCaptions(Context context) {
        mContext = context.getApplicationContext();
        mPrefs = DumbTubePrefs.instance(mContext);
        mPrefs.addChangeListener(() -> mLoaded = false); // profile switch -> reload lazily
    }

    public static ChannelCaptions instance(Context context) {
        if (sInstance == null) {
            sInstance = new ChannelCaptions(context);
        }

        return sInstance;
    }

    public boolean isEnabled() {
        return mPrefs.getBoolean(KEY_ENABLED, true);
    }

    public void setEnabled(boolean enabled) {
        mPrefs.setBoolean(KEY_ENABLED, enabled);
    }

    /**
     * Hook: decides which captions to apply when a video is loaded.
     * @param upstreamResult what SmartTube would apply on its own
     */
    public FormatItem resolve(@Nullable Video video, FormatItem upstreamResult) {
        if (!isEnabled() || video == null) {
            return upstreamResult;
        }

        if (video.videoId != null && video.videoId.equals(mSuspendedVideoId)) {
            return upstreamResult; // subtitles caused playback errors for this video
        }

        load();

        Entry entry = video.channelId != null ? mChannels.get(video.channelId) : null;

        return entry != null ? entry.toFormat() : getDefaultEntry().toFormat();
    }

    /**
     * Hook: the user picked captions (or turned them off) in the player.
     */
    public void onUserSelected(@Nullable Video video, @Nullable FormatItem format) {
        if (!isEnabled() || video == null || format == null || TextUtils.isEmpty(video.channelId)) {
            return;
        }

        load();

        Entry entry = mChannels.remove(video.channelId); // re-insert at the end (most recent)

        if (entry == null) {
            entry = Entry.from(format);
        } else {
            entry.update(format);
        }

        mChannels.put(video.channelId, entry);
        trim();
        persist();

        if (video.videoId != null && video.videoId.equals(mSuspendedVideoId)) {
            mSuspendedVideoId = null; // explicit user choice wins
        }
    }

    /**
     * Hook: CC button toggle. Prefer this channel's saved track over SmartTube's "last used" one.
     */
    public FormatItem preferSaved(@Nullable Video video, @Nullable List<FormatItem> available, FormatItem fallback) {
        if (!isEnabled() || video == null || video.channelId == null || available == null) {
            return fallback;
        }

        load();

        Entry entry = mChannels.get(video.channelId);

        if (entry == null || entry.language == null) {
            return fallback;
        }

        FormatItem saved = null;
        Entry probe = new Entry();
        probe.enabled = true;
        probe.language = entry.language;
        probe.formatId = entry.formatId;
        probe.codecs = entry.codecs;
        FormatItem savedFormat = probe.toFormat();

        for (FormatItem item : available) {
            if (item != null && Helpers.equals(item.getLanguage(), entry.language)) {
                return item; // exact label match
            }

            if (saved == null && item != null && !item.isDefault() && savedFormat.equals(item)) {
                saved = item;
            }
        }

        return saved != null ? saved : fallback;
    }

    /**
     * Hook: SmartTube's error fixer turned subtitles off for the current video.
     */
    public void suspendFor(@Nullable Video video) {
        mSuspendedVideoId = video != null ? video.videoId : null;
    }

    public void forgetChannel(@Nullable String channelId) {
        if (channelId == null) {
            return;
        }

        load();

        if (mChannels.remove(channelId) != null) {
            persist();
        }
    }

    public void forgetAll() {
        load();
        mChannels.clear();
        persist();
    }

    public int getSavedChannelCount() {
        load();
        return mChannels.size();
    }

    public FormatItem getDefaultFormat() {
        load();
        return getDefaultEntry().toFormat();
    }

    public void setDefaultFormat(FormatItem format) {
        load();
        mDefault = Entry.from(format);
        persist();
    }

    // ---------- UI ----------

    /**
     * Hook: extra items for the player's subtitle dialog (CC long press).
     */
    public void appendPlayerOptions(AppDialogPresenter dialog, @Nullable Video video) {
        String channelId = video != null ? video.channelId : null;
        String channelName = video != null && video.getAuthor() != null ? video.getAuthor() : "?";

        dialog.appendSingleSwitch(UiOptionItem.from(mContext.getString(R.string.dumbtube_captions_enable),
                option -> setEnabled(option.isSelected()), isEnabled()));

        if (!isEnabled()) {
            return;
        }

        load();
        Entry entry = channelId != null ? mChannels.get(channelId) : null;
        String state = entry != null ? describe(entry) : mContext.getString(R.string.dumbtube_captions_not_saved, describe(getDefaultEntry()));

        dialog.appendSingleButton(UiOptionItem.from(
                mContext.getString(R.string.dumbtube_captions_forget_channel, channelName),
                mContext.getString(R.string.dumbtube_captions_saved_state, state),
                option -> {
                    forgetChannel(channelId);
                    applyToPlayer(video);
                    MessageHelpers.showMessage(mContext, mContext.getString(R.string.dumbtube_captions_forgotten, channelName));
                }));

        dialog.appendSingleButton(UiOptionItem.from(
                mContext.getString(R.string.dumbtube_captions_set_default),
                mContext.getString(R.string.dumbtube_captions_default_state, describe(getDefaultEntry())),
                option -> {
                    PlaybackView player = PlaybackPresenter.instance(mContext).getPlayer();
                    FormatItem current = player != null ? player.getSubtitleFormat() : null;
                    setDefaultFormat(current);
                    MessageHelpers.showMessage(mContext, mContext.getString(R.string.dumbtube_captions_default_state, describe(getDefaultEntry())));
                }));
    }

    /**
     * Section of the DumbTube settings screen.
     */
    public void appendSettings(AppDialogPresenter dialog) {
        load();

        dialog.appendSingleSwitch(UiOptionItem.from(mContext.getString(R.string.dumbtube_captions_enable),
                option -> setEnabled(option.isSelected()), isEnabled()));

        // Default for channels without saved settings: Off + recently used tracks
        List<OptionItem> options = new ArrayList<>();
        FormatItem currentDefault = getDefaultFormat();
        options.add(UiOptionItem.from(mContext.getString(R.string.dumbtube_captions_off),
                option -> setDefaultFormat(FormatItem.SUBTITLE_NONE), currentDefault.isDefault()));

        List<String> seen = new ArrayList<>();
        List<FormatItem> candidates = new ArrayList<>();
        if (!currentDefault.isDefault()) {
            candidates.add(currentDefault);
        }
        candidates.addAll(PlayerData.instance(mContext).getLastSubtitleFormats());

        for (FormatItem format : candidates) {
            if (format == null || format.isDefault() || format.getLanguage() == null || seen.contains(format.getLanguage())) {
                continue;
            }
            seen.add(format.getLanguage());
            options.add(UiOptionItem.from(describe(Entry.from(format)),
                    option -> setDefaultFormat(format),
                    !currentDefault.isDefault() && Helpers.equals(currentDefault.getLanguage(), format.getLanguage())));
        }

        dialog.appendRadioCategory(mContext.getString(R.string.dumbtube_captions_default), options);

        dialog.appendSingleButton(UiOptionItem.from(
                mContext.getString(R.string.dumbtube_captions_forget_all, getSavedChannelCount()),
                option -> {
                    forgetAll();
                    MessageHelpers.showMessage(mContext, mContext.getString(R.string.dumbtube_captions_forgotten_all));
                }));
    }

    private void applyToPlayer(@Nullable Video video) {
        PlaybackView player = PlaybackPresenter.instance(mContext).getPlayer();

        if (player != null && video != null) {
            player.setFormat(resolve(video, PlayerData.instance(mContext).getFormat(FormatItem.TYPE_SUBTITLE)));
        }
    }

    private String describe(Entry entry) {
        if (entry == null || !entry.enabled || entry.language == null) {
            return mContext.getString(R.string.dumbtube_captions_off);
        }

        return SubtitleTrack.isAuto(entry.language)
                ? mContext.getString(R.string.dumbtube_captions_auto, entry.language.substring(0, entry.language.length() - 1))
                : entry.language;
    }

    // ---------- Storage ----------

    private Entry getDefaultEntry() {
        if (mDefault == null) {
            // First run: start from SmartTube's own global subtitle setting (normally "off")
            mDefault = Entry.from(PlayerData.instance(mContext).getFormat(FormatItem.TYPE_SUBTITLE));
            persist();
        }

        return mDefault;
    }

    private void load() {
        if (mLoaded) {
            return;
        }

        mLoaded = true;
        mChannels.clear();
        mDefault = null;

        String data = mPrefs.getString(KEY_CHANNELS, null);

        if (data != null) {
            for (String line : data.split(LINE_DELIM)) {
                String[] fields = line.split(FIELD_DELIM, -1);
                Entry entry = Entry.parse(fields);
                if (entry != null && !fields[0].isEmpty()) {
                    mChannels.put(fields[0], entry);
                }
            }
        }

        String defaultData = mPrefs.getString(KEY_DEFAULT, null);

        if (defaultData != null) {
            mDefault = Entry.parse(defaultData.split(FIELD_DELIM, -1));
        }
    }

    private void trim() {
        Iterator<String> iterator = mChannels.keySet().iterator();
        while (mChannels.size() > MAX_CHANNELS && iterator.hasNext()) {
            iterator.next();
            iterator.remove(); // oldest first
        }
    }

    private void persist() {
        StringBuilder builder = new StringBuilder();

        for (Map.Entry<String, Entry> item : mChannels.entrySet()) {
            if (builder.length() > 0) {
                builder.append(LINE_DELIM);
            }
            builder.append(item.getValue().serialize(item.getKey()));
        }

        // Write to the prefs directly. Listener would only reset mLoaded which we keep valid.
        mPrefs.setString(KEY_CHANNELS, builder.toString());
        mPrefs.setString(KEY_DEFAULT, mDefault != null ? mDefault.serialize("default") : null);
        mLoaded = true;
    }
}
