package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewTreeObserver;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData.ColorScheme;

import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] "OLED (neon green)" color scheme: pure black backgrounds, #39FF14 accent, off-white text.<br/>
 * Styles: smarttubetv/src/main/res/values/dumbtube_styles.xml (App.Theme.DumbTube.OLED.*).<br/>
 * The selection is stored by DumbTube (default: selected), not as an index in SmartTube's scheme list,
 * so upstream adding/removing schemes never changes the selected theme.<br/>
 * At runtime, opaque dark-grey panels that come from fixed library colors (e.g. the settings dialog
 * list, #202124) are painted pure black.<br/><br/>
 * Upstream hooks: MainUIData getColorSchemes()/getColorScheme()/setColorScheme(), MotherActivity.onResume().
 */
public final class OledNeonTheme {
    private static final String KEY_SELECTED = "oled_neon_theme";
    /** White text becomes #E6E6E6 (applied by {@link TextDimmer} on top of the user's text brightness). */
    static final float TEXT_CAP = 0.9f;
    private static ColorScheme sScheme;

    private OledNeonTheme() {
    }

    public static ColorScheme getScheme(Context context) {
        if (sScheme == null) {
            sScheme = new ColorScheme(
                    R.string.dumbtube_theme_oled_neon,
                    "App.Theme.DumbTube.OLED.Player",
                    "App.Theme.DumbTube.OLED.Browse",
                    "App.Theme.DumbTube.OLED.Preferences",
                    context.getApplicationContext());
        }

        return sScheme;
    }

    /**
     * Styles are present (they live in the app module, not available e.g. in unit tests).
     */
    public static boolean isAvailable(Context context) {
        return context != null && getScheme(context).browseThemeResId > 0;
    }

    public static boolean isSelected(Context context) {
        return isAvailable(context) && DumbTubePrefs.instance(context).getBoolean(KEY_SELECTED, true);
    }

    /**
     * Hook: theme picker list with the DumbTube scheme on top.
     */
    public static List<ColorScheme> withScheme(Context context, List<ColorScheme> upstreamSchemes) {
        List<ColorScheme> result = new ArrayList<>();
        result.add(getScheme(context));
        result.addAll(upstreamSchemes);
        return result;
    }

    /**
     * Hook: a scheme was picked in Settings.
     * @return true if it's the DumbTube scheme (nothing else to do)
     */
    public static boolean onSchemeSelected(Context context, ColorScheme scheme) {
        boolean isOurs = scheme != null && scheme == sScheme;
        DumbTubePrefs.instance(context).setBoolean(KEY_SELECTED, isOurs);
        return isOurs;
    }

    /**
     * Hook: paint grey panels black while this theme is active.
     */
    public static void attach(Activity activity) {
        if (activity == null || activity.getWindow() == null || !isSelected(activity)) {
            return;
        }

        View decor = activity.getWindow().getDecorView();

        if (decor.getTag(R.id.dumbtube_oled_guard) == null) {
            ViewTreeObserver.OnGlobalLayoutListener guard = () -> paintPanelsBlack(decor);
            decor.setTag(R.id.dumbtube_oled_guard, guard); // owned by the decor view, no static refs
            decor.getViewTreeObserver().addOnGlobalLayoutListener(guard);
        }

        paintPanelsBlack(decor);
    }

    static void paintPanelsBlack(View view) {
        Drawable background = view.getBackground();

        if (background instanceof ColorDrawable && isGreyPanel(((ColorDrawable) background).getColor())) {
            view.setBackgroundColor(Color.BLACK);
        }

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                paintPanelsBlack(group.getChildAt(i));
            }
        }
    }

    /**
     * Opaque, dark and nearly colorless. Translucent overlays (player gradients) and colored or
     * bright backgrounds (focus highlights) are left alone.
     */
    static boolean isGreyPanel(int color) {
        if (Color.alpha(color) < 0xC0) {
            return false;
        }

        int r = Color.red(color);
        int g = Color.green(color);
        int b = Color.blue(color);
        int max = Math.max(r, Math.max(g, b));
        int min = Math.min(r, Math.min(g, b));

        return max > 0 && max <= 0x50 && max - min <= 0x28;
    }
}
