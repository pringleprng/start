package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.prefs.GeneralData;
import com.liskovsoft.smartyoutubetv2.common.prefs.PlayerData;

/**
 * [DumbTube] DumbTube's own defaults for upstream settings, applied once (per account profile).<br/>
 * Applied through the normal setters, so the user can turn the upstream options back on and they stay on.<br/>
 * To add a default later, add a new step with a new key, so existing installs get it once too.<br/><br/>
 * Upstream hook: MotherActivity.onCreate() -> {@link #applyOnce(Context)}.
 */
public final class DumbTubeDefaults {
    private static final String KEY_CLOCK_HIDDEN = "defaults_clock_hidden_v1";

    private DumbTubeDefaults() {
    }

    public static void applyOnce(Context context) {
        if (context == null) {
            return;
        }

        DumbTubePrefs prefs = DumbTubePrefs.instance(context);

        if (!prefs.getBoolean(KEY_CLOCK_HIDDEN, false)) {
            // Top-right clock + date in the browse screens (Settings > Main UI)
            GeneralData.instance(context).setGlobalClockEnabled(false);
            // Clock in the top right of the player controls and the always-on player clock (Settings > Player)
            PlayerData.instance(context).setClockEnabled(false);
            PlayerData.instance(context).setGlobalClockEnabled(false);
            // Upstream saves 10 s later; save now so the flag and the settings can't get out of sync
            GeneralData.instance(context).persistNow();
            PlayerData.instance(context).persistNow();
            prefs.setBoolean(KEY_CLOCK_HIDDEN, true);
        }
    }
}
