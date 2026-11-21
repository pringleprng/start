package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;

import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;

/**
 * [DumbTube] When the top-right clock + date are hidden (Settings > Main UI, hidden by default in
 * DumbTube), the content area (rows and grids of every browse screen) starts higher, so there is no
 * empty band at the top. Theme overlay ThemeOverlay.DumbTube.Content.NoClock (dumbtube_layout.xml)
 * sets leanback's browseRowsMarginTop. Applies to screens opened after the clock setting changed.<br/><br/>
 * Upstream hook: MotherActivity.onCreate() -> {@link #applyTheme(Activity)}.
 */
public final class ContentTop {
    private static final String OVERLAY = "ThemeOverlay.DumbTube.Content.NoClock";

    private ContentTop() {
    }

    public static void applyTheme(Activity activity) {
        if (activity == null || GeneralData.instance(activity).isGlobalClockEnabled()) {
            return;
        }

        int overlay = activity.getResources().getIdentifier(OVERLAY, "style", activity.getPackageName());

        if (overlay > 0) {
            activity.getTheme().applyStyle(overlay, true);
        }
    }
}
