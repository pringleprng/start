package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewTreeObserver;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData.ColorScheme;

import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] "OLED" color scheme: pure black backgrounds, off-white text and two user colors:<br/>
 * - focus color: background of the focused card/tile (default light grey); the text on it switches
 *   between dark and light for contrast. Applied at runtime in the card presenters.<br/>
 * - accent color: the small accents, i.e. seek bar, player icon highlight, switches/radios, card progress,
 *   search orb (default neon green #39FF14). Applied as a theme overlay (dumbtube_palette.xml).<br/>
 * Styles: smarttubetv/src/main/res/values/dumbtube_styles.xml (App.Theme.DumbTube.OLED.*).<br/>
 * The selection is stored by DumbTube (default: selected), not as an index in SmartTube's scheme list,
 * so upstream adding/removing schemes never changes the selected theme.<br/>
 * At runtime, opaque dark-grey panels that come from fixed library colors (e.g. the settings dialog
 * list, #202124) are painted pure black.<br/><br/>
 * Upstream hooks: MainUIData getColorSchemes()/getColorScheme()/setColorScheme(),
 * MotherActivity.onCreate()/onResume(), Video/Channel/Settings card presenters and TagPresenter.
 */
public final class OledNeonTheme {
    private static final String KEY_SELECTED = "oled_neon_theme";
    private static final String KEY_FOCUS_COLOR = "oled_focus_color";
    private static final String KEY_ACCENT_COLOR = "oled_accent_color";
    private static final String DEFAULT_FOCUS_COLOR = "light_grey";
    private static final String DEFAULT_ACCENT_COLOR = "neon_green";
    private static final String ACCENT_OVERLAY_PREFIX = "ThemeOverlay.DumbTube.Accent.";
    private static final int TEXT_ON_LIGHT = 0xFF121212;
    private static final int TEXT_ON_DARK = 0xFFE6E6E6;
    /** White text becomes #E6E6E6 (applied by {@link TextDimmer} on top of the user's text brightness). */
    static final float TEXT_CAP = 0.9f;
    private static ColorScheme sScheme;
    private static boolean sRestartNeeded;

    /**
     * Colors offered for focus and accent. Keys must match dumbtube_palette.xml (ThemeOverlay.DumbTube.Accent.<key>).
     */
    static final class PaletteColor {
        final String key;
        final String name;
        final int color;

        PaletteColor(String key, String name, int color) {
            this.key = key;
            this.name = name;
            this.color = color;
        }
    }

    static final PaletteColor[] PALETTE = {
            new PaletteColor("light_grey", "Light grey", 0xFFBDBDBD),
            new PaletteColor("silver", "Silver", 0xFFE0E0E0),
            new PaletteColor("grey", "Grey", 0xFF8C8C8C),
            new PaletteColor("dark_grey", "Dark grey", 0xFF424242),
            new PaletteColor("charcoal", "Charcoal", 0xFF262626),
            new PaletteColor("neon_green", "Neon green", 0xFF39FF14),
            new PaletteColor("green", "Green", 0xFF00C853),
            new PaletteColor("teal", "Teal", 0xFF1DE9B6),
            new PaletteColor("cyan", "Cyan", 0xFF00E5FF),
            new PaletteColor("blue", "Blue", 0xFF2979FF),
            new PaletteColor("indigo", "Indigo", 0xFF536DFE),
            new PaletteColor("purple", "Purple", 0xFFD500F9),
            new PaletteColor("magenta", "Magenta", 0xFFFF00FF),
            new PaletteColor("pink", "Pink", 0xFFFF4081),
            new PaletteColor("red", "Red", 0xFFFF1744),
            new PaletteColor("orange", "Orange", 0xFFFF9100),
            new PaletteColor("amber", "Amber", 0xFFFFC400),
            new PaletteColor("yellow", "Yellow", 0xFFFFEA00),
            new PaletteColor("white", "White", 0xFFFFFFFF)
    };

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

    // ---------- Focus / accent colors ----------

    static PaletteColor findColor(String key, String defaultKey) {
        PaletteColor fallback = null;

        for (PaletteColor color : PALETTE) {
            if (color.key.equals(key)) {
                return color;
            }
            if (color.key.equals(defaultKey)) {
                fallback = color;
            }
        }

        return fallback != null ? fallback : PALETTE[0];
    }

    static PaletteColor getFocusColor(Context context) {
        return findColor(DumbTubePrefs.instance(context).getString(KEY_FOCUS_COLOR, DEFAULT_FOCUS_COLOR), DEFAULT_FOCUS_COLOR);
    }

    static PaletteColor getAccentColor(Context context) {
        return findColor(DumbTubePrefs.instance(context).getString(KEY_ACCENT_COLOR, DEFAULT_ACCENT_COLOR), DEFAULT_ACCENT_COLOR);
    }

    /**
     * Hook (card presenters): background of a focused card/tile.
     */
    public static int focusBackground(Context context, int upstreamColor) {
        return isSelected(context) ? getFocusColor(context).color : upstreamColor;
    }

    /**
     * Hook (card presenters): text on a focused card/tile, dark or light, whichever reads better.
     */
    public static int focusText(Context context, int upstreamColor) {
        return isSelected(context) ? textColorFor(getFocusColor(context).color) : upstreamColor;
    }

    static int textColorFor(int background) {
        double bg = luminance(background);
        double onLight = (bg + 0.05) / (luminance(TEXT_ON_LIGHT) + 0.05);
        double onDark = (luminance(TEXT_ON_DARK) + 0.05) / (bg + 0.05);
        return onLight >= onDark ? TEXT_ON_LIGHT : TEXT_ON_DARK;
    }

    private static double luminance(int color) {
        return 0.2126 * channel(Color.red(color)) + 0.7152 * channel(Color.green(color)) + 0.0722 * channel(Color.blue(color));
    }

    private static double channel(int value) {
        double c = value / 255.0;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }

    /**
     * Hook (MotherActivity.onCreate, after the theme is set): apply the accent color overlay.
     */
    public static void applyColors(Activity activity) {
        if (activity == null || !isSelected(activity)) {
            return;
        }

        int overlayResId = activity.getResources().getIdentifier(
                ACCENT_OVERLAY_PREFIX + getAccentColor(activity).key, "style", activity.getPackageName());

        if (overlayResId > 0) {
            activity.getTheme().applyStyle(overlayResId, true);
        }
    }

    /**
     * Section of the DumbTube settings screen.
     */
    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        appendColorCategory(context, dialog, R.string.dumbtube_oled_focus_color, KEY_FOCUS_COLOR, getFocusColor(context));
        appendColorCategory(context, dialog, R.string.dumbtube_oled_accent_color, KEY_ACCENT_COLOR, getAccentColor(context));
    }

    private static void appendColorCategory(Context context, AppDialogPresenter dialog, int titleResId, String prefKey, PaletteColor current) {
        List<OptionItem> options = new ArrayList<>();

        for (PaletteColor color : PALETTE) {
            options.add(UiOptionItem.from(String.format("%s  (#%06X)", color.name, color.color & 0xFFFFFF),
                    option -> {
                        DumbTubePrefs.instance(context).setString(prefKey, color.key);
                        sRestartNeeded = true;
                    },
                    color == current));
        }

        dialog.appendRadioCategory(context.getString(titleResId), options);
    }

    /**
     * Called when the DumbTube settings dialog closes: colors apply to new screens, so ask for a restart.
     */
    public static void onSettingsClosed(Context context) {
        if (sRestartNeeded) {
            sRestartNeeded = false;
            MessageHelpers.showLongMessage(context, R.string.msg_restart_app);
        }
    }

    // ---------- Grey panels ----------

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
        paintPanelsBlack(view, getFocusColor(view.getContext()).color);
    }

    private static void paintPanelsBlack(View view, int focusColor) {
        Drawable background = view.getBackground();

        if (background instanceof ColorDrawable) {
            int color = ((ColorDrawable) background).getColor();
            // Keep the user's focus color, even if it's a dark grey
            if (isGreyPanel(color) && (color | 0xFF000000) != (focusColor | 0xFF000000)) {
                view.setBackgroundColor(Color.BLACK);
            }
        }

        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) view;
            for (int i = 0; i < group.getChildCount(); i++) {
                paintPanelsBlack(group.getChildAt(i), focusColor);
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
