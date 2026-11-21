package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;
import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;

import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] When the top-right clock + date are hidden (Settings > Main UI, hidden by default in
 * DumbTube), the content area (rows and grids of every browse screen) starts higher and the title bar
 * (search icon) moves up with it, so there is no empty band at the top.<br/>
 * Setting "Top spacing": 70 / 76 (default) / 90 / 130 dp (130 = SmartTube). Theme overlays
 * ThemeOverlay.DumbTube.Content.Top.&lt;dp&gt; (dumbtube_layout.xml) set leanback's browseRowsMarginTop and
 * browsePaddingTop. Applies to screens opened afterwards (restart asked for).<br/><br/>
 * Upstream hook: MotherActivity.onCreate() -> {@link #applyTheme(Activity)}.
 */
public final class ContentTop {
    private static final String KEY_TOP = "content_top_dp";
    private static final String OVERLAY_PREFIX = "ThemeOverlay.DumbTube.Content.Top.";
    static final int[] STEPS_DP = {70, 76, 90, 130};
    static final int DEFAULT_DP = 76;
    static final int SMARTTUBE_DP = 130;

    private ContentTop() {
    }

    static int getTopDp(Context context) {
        int value = DumbTubePrefs.instance(context).getInt(KEY_TOP, DEFAULT_DP);
        for (int step : STEPS_DP) {
            if (step == value) {
                return value;
            }
        }
        return DEFAULT_DP;
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        int current = getTopDp(context);
        int[] titles = {R.string.dumbtube_top_tight, R.string.dumbtube_top_compact, R.string.dumbtube_top_medium, R.string.dumbtube_top_smarttube};
        List<OptionItem> options = new ArrayList<>();

        for (int i = 0; i < STEPS_DP.length; i++) {
            int step = STEPS_DP[i];
            options.add(UiOptionItem.from(context.getString(titles[i], step), option -> {
                DumbTubePrefs.instance(context).setInt(KEY_TOP, step);
                OledNeonTheme.requestRestart();
            }, step == current));
        }

        dialog.appendRadioCategory(context.getString(R.string.dumbtube_top_spacing), options);
    }

    /**
     * Hook (MotherActivity.onCreate, after the theme is set).
     */
    public static void applyTheme(Activity activity) {
        if (activity == null || GeneralData.instance(activity).isGlobalClockEnabled()) {
            return;
        }

        int top = getTopDp(activity);

        if (top == SMARTTUBE_DP) {
            return;
        }

        int overlay = activity.getResources().getIdentifier(OVERLAY_PREFIX + top, "style", activity.getPackageName());

        if (overlay > 0) {
            activity.getTheme().applyStyle(overlay, true);
        }
    }
}
