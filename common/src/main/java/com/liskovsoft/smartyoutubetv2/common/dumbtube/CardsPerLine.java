package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;
import android.content.res.Resources;
import android.os.Build;

import com.liskovsoft.sharedutils.helpers.MessageHelpers;
import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.common.utils.Utils;

import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] "Cards per line" in place of SmartTube's "Video grid scale" (Settings &gt; Main UI and Settings &gt; UI scale).<br/>
 * SmartTube works out how many cards fit in a line at the chosen scale, rounds down and stretches the cards to fill the
 * line (GridFragmentHelper.getCardDimensPxInt). So the size only changes when the number of cards changes: 0.8x, 0.9x
 * and 1.0x all give 4 cards per line, 1.1x to 1.35x all give 3. This lists the number of cards instead (2 to 8), so
 * every choice is a different card size. The number becomes the grid scale that fits exactly that many cards.<br/>
 * SmartTube keeps card sizes until the app process ends, so a change restarts the app when the dialog closes.<br/><br/>
 * Upstream hooks: MainUIData.getVideoGridScale() -&gt; {@link #getScale}; appendVideoGridScale() of
 * MainUISettingsPresenter and UIScaleSettingsPresenter -&gt; {@link #appendSettings}.
 */
public final class CardsPerLine {
    private static final String KEY_CARDS = "cards_per_line";
    static final int MIN_CARDS = 2;
    static final int MAX_CARDS = 8;
    static final int SMARTTUBE_DEFAULT = 4; // what SmartTube's default scale 1.0x gives
    // MotherActivity.initDpi() makes the screen 1920px / 2.0 = 960dp wide at UI scale 1.0 (960 / UI scale otherwise)
    static final float SCREEN_WIDTH_DP = 960f;
    // GridFragmentHelper.getMaxColsNumFloatInt() keeps 10 % of the width (times UI scale) free at the sides
    private static final float SIDE_SPACE = 0.1f;
    // Aim at slightly more than N cards so pixel rounding never drops one; SmartTube stretches them to fill the line
    private static final float FIT_MARGIN = 0.99f;
    static final float DEFAULT_CARD_WIDTH_DP = 200f; // R.dimen.card_width (smarttubetv module)
    static final float DEFAULT_SPACING_DP = 15f; // R.dimen.grid_item_horizontal_spacing
    private static float sCardWidthDp;
    private static float sSpacingDp;

    private CardsPerLine() {
    }

    /**
     * Hook: true when the user picked a number of cards here.
     */
    public static boolean isSet(Context context) {
        return getCards(context) != 0;
    }

    /**
     * Hook: the grid scale that fits exactly the chosen number of cards per line.
     */
    public static float getScale(Context context, float uiScale) {
        return scaleFor(getCards(context), uiScale, getCardWidthDp(context), getSpacingDp(context));
    }

    /**
     * Hook: replaces SmartTube's "Video grid scale" list. Returns false where SmartTube fixes the scale (Android 4.4).
     */
    public static boolean appendSettings(Context context, AppDialogPresenter dialog) {
        if (context == null || dialog == null || Build.VERSION.SDK_INT <= 19) {
            return false;
        }

        int openedWith = getCurrentCards(context);
        List<OptionItem> options = new ArrayList<>();

        for (int cards = MIN_CARDS; cards <= MAX_CARDS; cards++) {
            int value = cards;
            String title = cards == SMARTTUBE_DEFAULT
                    ? context.getString(R.string.dumbtube_cards_default, cards) : String.valueOf(cards);
            options.add(UiOptionItem.from(title,
                    option -> DumbTubePrefs.instance(context).setInt(KEY_CARDS, value), value == openedWith));
        }

        dialog.appendRadioCategory(context.getString(R.string.dumbtube_cards_per_line), options);
        dialog.setOnFinish(() -> {
            if (getCurrentCards(context) != openedWith) {
                MessageHelpers.showMessage(context, R.string.dumbtube_msg_restart_cards);
                Utils.restartTheApp(context);
            }
        });

        return true;
    }

    static int getCards(Context context) {
        int cards = DumbTubePrefs.instance(context).getInt(KEY_CARDS, 0);
        return cards >= MIN_CARDS && cards <= MAX_CARDS ? cards : 0;
    }

    /**
     * The chosen number, or what SmartTube's own scale gives when nothing was chosen here yet.
     */
    private static int getCurrentCards(Context context) {
        int cards = getCards(context);

        if (cards != 0) {
            return cards;
        }

        MainUIData data = MainUIData.instance(context);
        return clamp(cardsFor(data.getVideoGridScale(), data.getUIScale(), getCardWidthDp(context), getSpacingDp(context)));
    }

    static float scaleFor(int cards, float uiScale, float cardWidthDp, float spacingDp) {
        return (availableWidthDp(uiScale) / cards - spacingDp) / cardWidthDp * FIT_MARGIN;
    }

    /**
     * Same math as GridFragmentHelper: cards that fit in a line at this scale.
     */
    static int cardsFor(float scale, float uiScale, float cardWidthDp, float spacingDp) {
        return (int) (availableWidthDp(uiScale) / (cardWidthDp * scale + spacingDp));
    }

    static float availableWidthDp(float uiScale) {
        float scale = uiScale > 0 ? uiScale : 1f;
        float width = SCREEN_WIDTH_DP / scale;
        return width - width * SIDE_SPACE * scale;
    }

    private static int clamp(int cards) {
        return Math.max(MIN_CARDS, Math.min(MAX_CARDS, cards));
    }

    private static float getCardWidthDp(Context context) {
        if (sCardWidthDp == 0) {
            sCardWidthDp = getDimensionDp(context, "card_width", DEFAULT_CARD_WIDTH_DP);
        }
        return sCardWidthDp;
    }

    private static float getSpacingDp(Context context) {
        if (sSpacingDp == 0) {
            sSpacingDp = getDimensionDp(context, "grid_item_horizontal_spacing", DEFAULT_SPACING_DP);
        }
        return sSpacingDp;
    }

    /**
     * Dimens of the smarttubetv module, looked up by name (the common module can't see its R class).
     */
    private static float getDimensionDp(Context context, String name, float fallback) {
        try {
            Resources res = context.getResources();
            int id = res.getIdentifier(name, "dimen", context.getPackageName());
            float density = res.getDisplayMetrics().density;
            if (id != 0 && density > 0) {
                float value = res.getDimension(id) / density;
                if (value > 0) {
                    return value;
                }
            }
        } catch (Resources.NotFoundException e) {
            // fall through
        }
        return fallback;
    }
}
