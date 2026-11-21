package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;
import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewTreeObserver;
import android.widget.TextView;

import androidx.annotation.NonNull;

import com.google.android.exoplayer2.text.CaptionStyleCompat;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionCategory;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * [DumbTube] Dims all interface text (menus, settings, cards, player overlay, dialogs).<br/>
 * Every activity window gets a pre-draw listener that re-tints each {@link TextView} with a wrapped
 * {@link ColorStateList} whose colors are scaled towards black (alpha kept, states kept). Colors that
 * the app sets later (e.g. focused card titles) are picked up on the next frame.<br/>
 * The player window can have its own level ("same as interface text" by default), adjustable from the
 * player's playback settings dialog.<br/>
 * Captions have their own brightness level, applied to the subtitle style.<br/><br/>
 * Upstream hooks: MotherActivity.onResume() -> {@link #attach(Activity)};
 * SubtitleManager.applyStyle()/applySystemStyle() -> {@link #dimCaptionStyle};
 * HQDialogController.onHighQualityClicked() -> {@link #createPlayerTextCategory}.<br/>
 * Not covered: toasts, the tooltip popup, colored spans inside text (e.g. some badges).
 */
public final class TextDimmer {
    private static final String KEY_TEXT_LEVEL = "text_brightness";
    private static final String KEY_CAPTION_LEVEL = "caption_brightness";
    private static final String KEY_PLAYER_TEXT_LEVEL = "player_text_brightness";
    /** Player text level: follow the interface text level. */
    private static final int SAME_AS_INTERFACE = 0;
    private static final int PLAYER_TEXT_CATEGORY_ID = 0x0D7B0001;
    private static final String PLAYER_ACTIVITY_SUFFIX = ".PlaybackActivity";
    public static final int[] LEVELS = {100, 90, 80, 70, 60, 50, 40, 30};
    private static final int MIN_LEVEL = 30;
    // Weak: a dimmer is owned by its window's decor view (tag + ViewTreeObserver)
    private static final List<WeakReference<WindowDimmer>> sWindows = new ArrayList<>();
    private static float sTextFactor = -1;
    private static float sPlayerTextFactor = -1;
    private static float sCaptionFactor = -1;
    private static boolean sListenerAdded;

    private TextDimmer() {
    }

    // ---------- Settings ----------

    public static int getTextLevel(Context context) {
        return clamp(DumbTubePrefs.instance(context).getInt(KEY_TEXT_LEVEL, 100));
    }

    public static void setTextLevel(Context context, int level) {
        DumbTubePrefs.instance(context).setInt(KEY_TEXT_LEVEL, clamp(level));
        reload(context);
        refreshAll();
    }

    public static int getCaptionLevel(Context context) {
        return clamp(DumbTubePrefs.instance(context).getInt(KEY_CAPTION_LEVEL, 100));
    }

    public static void setCaptionLevel(Context context, int level) {
        DumbTubePrefs.instance(context).setInt(KEY_CAPTION_LEVEL, clamp(level));
        reload(context);
    }

    /**
     * @return {@link #SAME_AS_INTERFACE} (0) or a level
     */
    public static int getPlayerTextLevel(Context context) {
        int level = DumbTubePrefs.instance(context).getInt(KEY_PLAYER_TEXT_LEVEL, SAME_AS_INTERFACE);
        return level == SAME_AS_INTERFACE ? SAME_AS_INTERFACE : clamp(level);
    }

    public static void setPlayerTextLevel(Context context, int level) {
        DumbTubePrefs.instance(context).setInt(KEY_PLAYER_TEXT_LEVEL, level == SAME_AS_INTERFACE ? SAME_AS_INTERFACE : clamp(level));
        reload(context);
        refreshAll(); // the player window is visible behind the dialog: updates live
    }

    private static List<OptionItem> createPlayerTextOptions(Context context) {
        List<OptionItem> options = new ArrayList<>();
        int current = getPlayerTextLevel(context);
        options.add(UiOptionItem.from(context.getString(R.string.dumbtube_player_text_same),
                option -> setPlayerTextLevel(context, SAME_AS_INTERFACE), current == SAME_AS_INTERFACE));
        for (int level : LEVELS) {
            options.add(UiOptionItem.from(level + "%", option -> setPlayerTextLevel(context, level), level == current));
        }
        return options;
    }

    /**
     * Hook: "Player text brightness" in the player's playback settings dialog.
     */
    public static OptionCategory createPlayerTextCategory(Context context) {
        return OptionCategory.from(PLAYER_TEXT_CATEGORY_ID, OptionCategory.TYPE_RADIO_LIST,
                context.getString(R.string.dumbtube_player_text_brightness), createPlayerTextOptions(context));
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        List<OptionItem> textOptions = new ArrayList<>();
        int textLevel = getTextLevel(context);
        for (int level : LEVELS) {
            textOptions.add(UiOptionItem.from(level + "%", option -> setTextLevel(context, level), level == textLevel));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_text_brightness), textOptions);

        dialog.appendRadioCategory(context.getString(R.string.dumbtube_player_text_brightness), createPlayerTextOptions(context));

        List<OptionItem> captionOptions = new ArrayList<>();
        int captionLevel = getCaptionLevel(context);
        for (int level : LEVELS) {
            captionOptions.add(UiOptionItem.from(level + "%", option -> setCaptionLevel(context, level), level == captionLevel));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_caption_brightness), captionOptions);
    }

    // ---------- Hooks ----------

    /**
     * Hook: attach to the activity window (idempotent) and apply the current level.
     */
    public static void attach(Activity activity) {
        if (activity == null || activity.getWindow() == null) {
            return;
        }

        ensureLoaded(activity);

        View decor = activity.getWindow().getDecorView();
        Object tag = decor.getTag(R.id.dumbtube_text_dimmer);
        WindowDimmer dimmer = tag instanceof WindowDimmer ? (WindowDimmer) tag : null;

        if (dimmer == null) {
            dimmer = new WindowDimmer(decor, activity.getClass().getName().endsWith(PLAYER_ACTIVITY_SUFFIX));
            decor.setTag(R.id.dumbtube_text_dimmer, dimmer);
            decor.getViewTreeObserver().addOnPreDrawListener(dimmer);
            sWindows.add(new WeakReference<>(dimmer));
        }

        dimmer.refresh();
    }

    /**
     * Hook: caption text color with the caption brightness applied.
     */
    public static CaptionStyleCompat dimCaptionStyle(Context context, CaptionStyleCompat style) {
        ensureLoaded(context);

        if (style == null || sCaptionFactor >= 0.999f) {
            return style;
        }

        return new CaptionStyleCompat(dim(style.foregroundColor, sCaptionFactor), style.backgroundColor,
                style.windowColor, style.edgeType, style.edgeColor, style.typeface);
    }

    // ---------- Internals ----------

    /**
     * Theme cap applied on top of the user level (e.g. OLED theme keeps white text off-white).
     */
    static float getThemeTextCap(Context context) {
        return OledNeonTheme.isSelected(context) ? OledNeonTheme.TEXT_CAP : 1f;
    }

    private static void ensureLoaded(Context context) {
        if (sTextFactor < 0 || sCaptionFactor < 0 || sPlayerTextFactor < 0) {
            reload(context);
        }

        if (!sListenerAdded) {
            sListenerAdded = true;
            Context appContext = context.getApplicationContext();
            DumbTubePrefs.instance(context).addChangeListener(() -> {
                reload(appContext);
                refreshAll();
            });
        }
    }

    private static void reload(Context context) {
        sTextFactor = getTextLevel(context) / 100f * getThemeTextCap(context);
        int playerLevel = getPlayerTextLevel(context);
        sPlayerTextFactor = playerLevel == SAME_AS_INTERFACE ? sTextFactor : playerLevel / 100f * getThemeTextCap(context);
        sCaptionFactor = getCaptionLevel(context) / 100f;
    }

    private static void refreshAll() {
        Iterator<WeakReference<WindowDimmer>> iterator = sWindows.iterator();
        while (iterator.hasNext()) {
            WindowDimmer dimmer = iterator.next().get();
            if (dimmer == null) {
                iterator.remove(); // window is gone
            } else {
                dimmer.refresh();
            }
        }
    }

    private static int clamp(int level) {
        return Math.max(MIN_LEVEL, Math.min(100, level));
    }

    static int dim(int color, float factor) {
        if (factor >= 0.999f) {
            return color;
        }

        return Color.argb(Color.alpha(color),
                Math.round(Color.red(color) * factor),
                Math.round(Color.green(color) * factor),
                Math.round(Color.blue(color) * factor));
    }

    private static final class WindowDimmer implements ViewTreeObserver.OnPreDrawListener {
        private final View mDecor;
        private final boolean mIsPlayer;
        private boolean mHasDimmed;

        WindowDimmer(View decor, boolean isPlayer) {
            mDecor = decor;
            mIsPlayer = isPlayer;
        }

        private float factor() {
            return mIsPlayer ? sPlayerTextFactor : sTextFactor;
        }

        void refresh() {
            walk(mDecor);
            mDecor.invalidate();
        }

        @Override
        public boolean onPreDraw() {
            if (factor() < 0.999f || mHasDimmed) {
                walk(mDecor);
            }
            return true;
        }

        private void walk(View view) {
            if (view instanceof TextView) {
                apply((TextView) view);
            } else if (view instanceof ViewGroup) {
                ViewGroup group = (ViewGroup) view;
                for (int i = 0; i < group.getChildCount(); i++) {
                    walk(group.getChildAt(i));
                }
            }
        }

        private void apply(TextView view) {
            if (applyTo(view, factor())) {
                mHasDimmed = true;
            }
        }
    }

    /**
     * Applies the factor to the view's text colors. Safe to call repeatedly.
     * @return true if the view is dimmed afterwards
     */
    static boolean applyTo(TextView view, float factor) {
        ColorStateList current = view.getTextColors();

        if (current instanceof DimmedColorStateList) {
            DimmedColorStateList dimmed = (DimmedColorStateList) current;
            if (dimmed.factor == factor) {
                return true; // up to date
            }
            current = dimmed.base;
        }

        if (current == null) {
            return false;
        }

        if (factor >= 0.999f) {
            if (current != view.getTextColors()) {
                view.setTextColor(current); // restore original colors
            }
            return false;
        }

        view.setTextColor(new DimmedColorStateList(current, factor));
        return true;
    }

    /**
     * Wraps the original colors so state changes (focus, selection...) keep working.
     */
    private static final class DimmedColorStateList extends ColorStateList {
        final ColorStateList base;
        final float factor;

        DimmedColorStateList(@NonNull ColorStateList base, float factor) {
            super(new int[][] {new int[0]}, new int[] {dim(base.getDefaultColor(), factor)});
            this.base = base;
            this.factor = factor;
        }

        @Override
        public int getColorForState(int[] stateSet, int defaultColor) {
            return dim(base.getColorForState(stateSet, defaultColor), factor);
        }

        @Override
        public int getDefaultColor() {
            return dim(base.getDefaultColor(), factor);
        }

        @Override
        public boolean isStateful() {
            return base.isStateful();
        }

        @NonNull
        @Override
        public ColorStateList withAlpha(int alpha) {
            return new DimmedColorStateList(base.withAlpha(alpha), factor);
        }
    }
}
