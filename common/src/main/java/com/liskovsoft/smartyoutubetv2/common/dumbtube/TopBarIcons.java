package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;
import android.content.Context;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewTreeObserver;
import android.widget.ImageView;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] Round icon buttons ("orbs": search in the top left, account, language, exit-PiP, search
 * screen and channel header buttons):<br/>
 * - no colored circle behind the icon (switch, default on)<br/>
 * - own brightness setting, separate from the text brightness. The focused icon is shown at that
 *   brightness, the others at 60 % of it (with the circle gone, this plus leanback's zoom marks focus).<br/>
 * The voice-search mic is left alone: its circle shows that it is listening.<br/>
 * Orbs are leanback SearchOrbViews; found at runtime by their "search_orb" + "icon" children, because
 * the common module doesn't depend on leanback.<br/><br/>
 * Upstream hook: MotherActivity.onResume() -> {@link #attach(Activity)}.
 */
public final class TopBarIcons {
    private static final String KEY_NO_BACKGROUND = "icons_no_background";
    private static final String KEY_LEVEL = "icons_brightness";
    private static final float UNFOCUSED_FACTOR = 0.6f;

    private TopBarIcons() {
    }

    public static boolean isNoBackground(Context context) {
        return DumbTubePrefs.instance(context).getBoolean(KEY_NO_BACKGROUND, true);
    }

    public static int getLevel(Context context) {
        return Math.max(TextDimmer.LEVELS[TextDimmer.LEVELS.length - 1],
                Math.min(100, DumbTubePrefs.instance(context).getInt(KEY_LEVEL, 100)));
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        dialog.appendSingleSwitch(UiOptionItem.from(context.getString(R.string.dumbtube_icons_no_background),
                option -> DumbTubePrefs.instance(context).setBoolean(KEY_NO_BACKGROUND, option.isSelected()),
                isNoBackground(context)));

        List<OptionItem> options = new ArrayList<>();
        int current = getLevel(context);
        for (int level : TextDimmer.LEVELS) {
            options.add(UiOptionItem.from(level + "%",
                    option -> DumbTubePrefs.instance(context).setInt(KEY_LEVEL, level), level == current));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_icons_brightness), options);
    }

    /**
     * Hook: attach to the activity window (idempotent).
     */
    public static void attach(Activity activity) {
        if (activity == null || activity.getWindow() == null) {
            return;
        }

        View decor = activity.getWindow().getDecorView();

        if (decor.getTag(R.id.dumbtube_top_bar_icons) == null) {
            WindowIcons icons = new WindowIcons(decor);
            decor.setTag(R.id.dumbtube_top_bar_icons, icons); // owned by the decor view
            decor.getViewTreeObserver().addOnGlobalLayoutListener(icons);
            decor.getViewTreeObserver().addOnPreDrawListener(icons);
        }

        ((WindowIcons) decor.getTag(R.id.dumbtube_top_bar_icons)).rescan();
    }

    private static final class WindowIcons implements ViewTreeObserver.OnGlobalLayoutListener, ViewTreeObserver.OnPreDrawListener {
        private final View mDecor;
        private final int mOrbCircleId;
        private final int mOrbIconId;
        private final List<WeakReference<ViewGroup>> mOrbs = new ArrayList<>();
        private boolean mScanNeeded = true;

        WindowIcons(View decor) {
            mDecor = decor;
            Context context = decor.getContext();
            mOrbCircleId = context.getResources().getIdentifier("search_orb", "id", context.getPackageName());
            mOrbIconId = context.getResources().getIdentifier("icon", "id", context.getPackageName());
        }

        void rescan() {
            mScanNeeded = true;
            mDecor.invalidate();
        }

        @Override
        public void onGlobalLayout() {
            mScanNeeded = true; // views may have been added or replaced
        }

        @Override
        public boolean onPreDraw() {
            if (mOrbCircleId == 0 || mOrbIconId == 0) {
                return true;
            }

            if (mScanNeeded) {
                mScanNeeded = false;
                mOrbs.clear();
                scan(mDecor);
            }

            if (!mOrbs.isEmpty()) {
                Context context = mDecor.getContext();
                boolean noBackground = isNoBackground(context);
                float level = getLevel(context) / 100f;

                for (WeakReference<ViewGroup> ref : mOrbs) {
                    ViewGroup orb = ref.get();
                    if (orb != null) {
                        apply(orb, noBackground, level);
                    }
                }
            }

            return true;
        }

        private void scan(View view) {
            if (!(view instanceof ViewGroup)) {
                return;
            }

            ViewGroup group = (ViewGroup) view;

            if (isOrb(group)) {
                mOrbs.add(new WeakReference<>(group));
                return;
            }

            for (int i = 0; i < group.getChildCount(); i++) {
                scan(group.getChildAt(i));
            }
        }

        private boolean isOrb(ViewGroup group) {
            if (group.getClass().getName().endsWith("SpeechOrbView")) {
                return false; // mic: the circle shows the listening state
            }

            for (int i = 0; i < group.getChildCount(); i++) {
                if (group.getChildAt(i).getId() == mOrbCircleId) {
                    return group.findViewById(mOrbIconId) instanceof ImageView;
                }
            }

            return false;
        }

        private void apply(ViewGroup orb, boolean noBackground, float level) {
            View circle = orb.findViewById(mOrbCircleId);
            int circleVisibility = noBackground ? View.INVISIBLE : View.VISIBLE;
            if (circle != null && circle.getVisibility() != circleVisibility) {
                circle.setVisibility(circleVisibility);
            }

            ImageView icon = (ImageView) orb.findViewById(mOrbIconId);
            if (icon != null) {
                float factor = orb.isFocused() ? level : level * UNFOCUSED_FACTOR;
                int alpha = Math.round(255 * factor); // on a black bar, alpha == brightness
                if (icon.getImageAlpha() != alpha) {
                    icon.setImageAlpha(alpha);
                }
            }
        }
    }
}
