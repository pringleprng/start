package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.app.Activity;
import android.content.Context;
import android.content.res.Resources;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewParent;
import android.widget.ImageView;
import android.widget.TextView;

import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;

import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] Sidebar (left browse menu) style:<br/>
 * - "icons only": hides the labels, shrinks the sidebar to the icons and moves the rows over
 *   (theme overlay ThemeOverlay.DumbTube.Sidebar.Compact.&lt;size&gt;, dumbtube_sidebar.xml)<br/>
 * - icon size: 24-64 dp (SmartTube: 32 dp)<br/>
 * Applies to newly created screens, so a restart is asked for after changing it.<br/><br/>
 * Upstream hooks: IconHeaderItemPresenter.onBindViewHolder() -> {@link #styleHeader};
 * MotherActivity.onCreate() -> {@link #applyTheme}.
 */
public final class SidebarStyle {
    private static final String KEY_ICONS_ONLY = "sidebar_icons_only";
    private static final String KEY_ICON_SIZE = "sidebar_icon_size";
    static final int[] ICON_SIZES_DP = {24, 32, 40, 48, 56, 64};
    static final int DEFAULT_ICON_SIZE_DP = 32;
    /** leanback: browsePaddingStart 56dp, focused header scale 1.2, header padding end 8dp (+ some air). */
    private static final int PANEL_PADDING_START_DP = 56;
    private static final float FOCUS_SCALE = 1.2f;
    private static final int PANEL_EXTRA_DP = 20;

    private SidebarStyle() {
    }

    // ---------- Settings ----------

    public static boolean isIconsOnly(Context context) {
        return DumbTubePrefs.instance(context).getBoolean(KEY_ICONS_ONLY, false);
    }

    public static int getIconSizeDp(Context context) {
        int size = DumbTubePrefs.instance(context).getInt(KEY_ICON_SIZE, DEFAULT_ICON_SIZE_DP);
        for (int allowed : ICON_SIZES_DP) {
            if (allowed == size) {
                return size;
            }
        }
        return DEFAULT_ICON_SIZE_DP;
    }

    /** Sidebar width in icons-only mode. */
    static int compactPanelWidthDp(int iconSizeDp) {
        return Math.round(PANEL_PADDING_START_DP + iconSizeDp * FOCUS_SCALE + PANEL_EXTRA_DP);
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        dialog.appendSingleSwitch(UiOptionItem.from(context.getString(R.string.dumbtube_sidebar_icons_only),
                option -> {
                    DumbTubePrefs.instance(context).setBoolean(KEY_ICONS_ONLY, option.isSelected());
                    OledNeonTheme.requestRestart();
                },
                isIconsOnly(context)));

        List<OptionItem> options = new ArrayList<>();
        int current = getIconSizeDp(context);
        for (int size : ICON_SIZES_DP) {
            String title = size == DEFAULT_ICON_SIZE_DP
                    ? context.getString(R.string.dumbtube_sidebar_icon_size_default, size)
                    : size + " dp";
            options.add(UiOptionItem.from(title, option -> {
                DumbTubePrefs.instance(context).setInt(KEY_ICON_SIZE, size);
                OledNeonTheme.requestRestart();
            }, size == current));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_sidebar_icon_size), options);
    }

    // ---------- Hooks ----------

    /**
     * Hook (MotherActivity.onCreate, after the theme): rows start right after the compact sidebar.
     */
    public static void applyTheme(Activity activity) {
        if (activity == null || !isIconsOnly(activity)) {
            return;
        }

        int overlay = activity.getResources().getIdentifier(
                "ThemeOverlay.DumbTube.Sidebar.Compact." + getIconSizeDp(activity), "style", activity.getPackageName());

        if (overlay > 0) {
            activity.getTheme().applyStyle(overlay, true);
        }
    }

    /**
     * Hook (IconHeaderItemPresenter.onBindViewHolder): icon size, label visibility, sidebar width.
     */
    public static void styleHeader(@Nullable ImageView icon, @Nullable TextView label) {
        View any = icon != null ? icon : label;

        if (any == null) {
            return;
        }

        Context context = any.getContext();
        boolean iconsOnly = isIconsOnly(context);
        int iconSizePx = dpToPx(context, getIconSizeDp(context));

        if (icon != null) {
            ViewGroup.LayoutParams lp = icon.getLayoutParams();
            if (lp != null && (lp.width != iconSizePx || lp.height != iconSizePx)) {
                lp.width = iconSizePx;
                lp.height = iconSizePx;
                icon.setLayoutParams(lp);
            }
        }

        if (label != null) {
            int visibility = iconsOnly ? View.GONE : View.VISIBLE;
            if (label.getVisibility() != visibility) {
                label.setVisibility(visibility);
            }
        }

        if (iconsOnly) {
            // The item isn't attached yet: size the sidebar once it is
            any.post(() -> resizePanel(any));
        }
    }

    private static void resizePanel(View headerItem) {
        Context context = headerItem.getContext();
        Resources res = context.getResources();
        int rootId = res.getIdentifier("browse_headers_root", "id", context.getPackageName());
        int listId = res.getIdentifier("browse_headers", "id", context.getPackageName());
        int width = dpToPx(context, compactPanelWidthDp(getIconSizeDp(context)));

        for (ViewParent parent = headerItem.getParent(); parent instanceof View; parent = parent.getParent()) {
            View view = (View) parent;
            if (view.getId() == listId || view.getId() == rootId) {
                setWidth(view, width);
            }
            if (view.getId() == rootId) {
                break;
            }
        }
    }

    private static void setWidth(View view, int width) {
        ViewGroup.LayoutParams lp = view.getLayoutParams();
        if (lp != null && lp.width != width) {
            lp.width = width;
            view.setLayoutParams(lp);
        }
    }

    private static int dpToPx(Context context, int dp) {
        return Math.round(dp * context.getResources().getDisplayMetrics().density);
    }
}
