package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.text.SpannableString;
import android.text.Spanned;
import android.text.style.ReplacementSpan;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.OptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.models.playback.ui.UiOptionItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;

import java.util.ArrayList;
import java.util.List;

/**
 * [DumbTube] Video length badge on cards (bottom right of the thumbnail).<br/>
 * Instead of white text in a black box: no box, text with an outline. Default black text with a light
 * grey outline. Text color, outline color and brightness are settings. "LIVE"/"NEW" badges keep
 * SmartTube's red box.<br/>
 * The text is drawn by {@link OutlineSpan} with its own colors, so the global text brightness doesn't
 * touch it; the badge has its own brightness.<br/><br/>
 * Upstream hooks: ComplexImageView.setBadgeText()/setBadgeColor() -> {@link #restyle(TextView)}.
 */
public final class CardBadge {
    private static final String KEY_TEXT_COLOR = "badge_text_color";
    private static final String KEY_OUTLINE_COLOR = "badge_outline_color";
    private static final String KEY_LEVEL = "badge_brightness";
    /** Text color value that keeps SmartTube's original badge (white text, black box). */
    static final String STYLE_ORIGINAL = "original";
    static final String COLOR_BLACK = "black";
    static final String OUTLINE_NONE = "none";
    private static final String DEFAULT_TEXT_COLOR = COLOR_BLACK;
    private static final String DEFAULT_OUTLINE_COLOR = "light_grey";
    private static final int UPSTREAM_BADGE_BACKGROUND = Color.BLACK; // VideoCardPresenter: R.color.black for normal badges

    private CardBadge() {
    }

    // ---------- Settings ----------

    static String getTextColorKey(Context context) {
        return DumbTubePrefs.instance(context).getString(KEY_TEXT_COLOR, DEFAULT_TEXT_COLOR);
    }

    static String getOutlineColorKey(Context context) {
        return DumbTubePrefs.instance(context).getString(KEY_OUTLINE_COLOR, DEFAULT_OUTLINE_COLOR);
    }

    static int getLevel(Context context) {
        return Math.max(TextDimmer.LEVELS[TextDimmer.LEVELS.length - 1],
                Math.min(100, DumbTubePrefs.instance(context).getInt(KEY_LEVEL, 100)));
    }

    static int colorOf(String key) {
        return COLOR_BLACK.equals(key) ? Color.BLACK : OledNeonTheme.findColor(key, DEFAULT_OUTLINE_COLOR).color;
    }

    public static void appendSettings(Context context, AppDialogPresenter dialog) {
        String textKey = getTextColorKey(context);
        List<OptionItem> textOptions = new ArrayList<>();
        textOptions.add(UiOptionItem.from(context.getString(R.string.dumbtube_badge_original),
                option -> setString(context, KEY_TEXT_COLOR, STYLE_ORIGINAL), STYLE_ORIGINAL.equals(textKey)));
        textOptions.add(UiOptionItem.from(context.getString(R.string.dumbtube_badge_black),
                option -> setString(context, KEY_TEXT_COLOR, COLOR_BLACK), COLOR_BLACK.equals(textKey)));
        for (OledNeonTheme.PaletteColor color : OledNeonTheme.PALETTE) {
            textOptions.add(UiOptionItem.from(color.name,
                    option -> setString(context, KEY_TEXT_COLOR, color.key), color.key.equals(textKey)));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_badge_text_color), textOptions);

        String outlineKey = getOutlineColorKey(context);
        List<OptionItem> outlineOptions = new ArrayList<>();
        outlineOptions.add(UiOptionItem.from(context.getString(R.string.dumbtube_badge_no_outline),
                option -> setString(context, KEY_OUTLINE_COLOR, OUTLINE_NONE), OUTLINE_NONE.equals(outlineKey)));
        outlineOptions.add(UiOptionItem.from(context.getString(R.string.dumbtube_badge_black),
                option -> setString(context, KEY_OUTLINE_COLOR, COLOR_BLACK), COLOR_BLACK.equals(outlineKey)));
        for (OledNeonTheme.PaletteColor color : OledNeonTheme.PALETTE) {
            outlineOptions.add(UiOptionItem.from(color.name,
                    option -> setString(context, KEY_OUTLINE_COLOR, color.key), color.key.equals(outlineKey)));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_badge_outline_color), outlineOptions);

        List<OptionItem> levelOptions = new ArrayList<>();
        int level = getLevel(context);
        for (int value : TextDimmer.LEVELS) {
            levelOptions.add(UiOptionItem.from(value + "%",
                    option -> DumbTubePrefs.instance(context).setInt(KEY_LEVEL, value), value == level));
        }
        dialog.appendRadioCategory(context.getString(R.string.dumbtube_badge_brightness), levelOptions);
    }

    private static void setString(Context context, String key, String value) {
        DumbTubePrefs.instance(context).setString(key, value);
        OledNeonTheme.requestRestart(); // cards already on screen keep their style
    }

    // ---------- Hook ----------

    /**
     * Hook: (re)style the badge after SmartTube changed its text or box color.
     */
    public static void restyle(@Nullable TextView badge) {
        if (badge == null) {
            return;
        }

        Context context = badge.getContext();
        CharSequence text = badge.getText();
        String plain = text != null ? text.toString() : null;
        Object state = badge.getTag(R.id.dumbtube_card_badge);

        // Which kind of badge is this? SmartTube paints a black box for normal ones (video length),
        // red for LIVE / NEW / upcoming. We make the box transparent, so remember the kind in a tag.
        Drawable background = badge.getBackground();
        boolean isNormal;
        if (background instanceof ColorDrawable && ((ColorDrawable) background).getColor() != Color.TRANSPARENT) {
            isNormal = ((ColorDrawable) background).getColor() == UPSTREAM_BADGE_BACKGROUND;
        } else {
            isNormal = Boolean.TRUE.equals(state);
        }
        badge.setTag(R.id.dumbtube_card_badge, isNormal);

        boolean enabled = !STYLE_ORIGINAL.equals(getTextColorKey(context));

        if (!isNormal || !enabled) {
            // Plain text, SmartTube's box (restore the black box if we removed it)
            if (text instanceof Spanned && ((Spanned) text).getSpans(0, text.length(), OutlineSpan.class).length > 0) {
                badge.setText(plain);
            }
            if (isNormal && background instanceof ColorDrawable && ((ColorDrawable) background).getColor() == Color.TRANSPARENT) {
                badge.setBackgroundColor(UPSTREAM_BADGE_BACKGROUND);
            }
            return;
        }

        if (!(background instanceof ColorDrawable) || ((ColorDrawable) background).getColor() != Color.TRANSPARENT) {
            badge.setBackgroundColor(Color.TRANSPARENT);
        }

        if (plain == null || plain.isEmpty()) {
            return;
        }

        float factor = getLevel(context) / 100f;
        int textColor = TextDimmer.dim(colorOf(getTextColorKey(context)), factor);
        String outlineKey = getOutlineColorKey(context);
        int outlineColor = OUTLINE_NONE.equals(outlineKey) ? Color.TRANSPARENT : TextDimmer.dim(colorOf(outlineKey), factor);
        float stroke = Math.max(2f, badge.getTextSize() * 0.14f);

        OutlineSpan[] spans = text instanceof Spanned ? ((Spanned) text).getSpans(0, text.length(), OutlineSpan.class) : new OutlineSpan[0];
        if (spans.length == 1 && spans[0].matches(textColor, outlineColor, stroke)) {
            return; // already styled
        }

        SpannableString styled = new SpannableString(plain);
        styled.setSpan(new OutlineSpan(textColor, outlineColor, stroke), 0, plain.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        badge.setText(styled);
    }

    /**
     * Draws the text with an outline (stroke first, then the fill) in its own colors.
     */
    static final class OutlineSpan extends ReplacementSpan {
        private final int mTextColor;
        private final int mOutlineColor;
        private final float mStroke;

        OutlineSpan(int textColor, int outlineColor, float stroke) {
            mTextColor = textColor;
            mOutlineColor = outlineColor;
            mStroke = stroke;
        }

        boolean matches(int textColor, int outlineColor, float stroke) {
            return mTextColor == textColor && mOutlineColor == outlineColor && mStroke == stroke;
        }

        @Override
        public int getSize(@NonNull Paint paint, CharSequence text, int start, int end, @Nullable Paint.FontMetricsInt fm) {
            if (fm != null) {
                paint.getFontMetricsInt(fm);
            }
            return Math.round(paint.measureText(text, start, end) + mStroke);
        }

        @Override
        public void draw(@NonNull Canvas canvas, CharSequence text, int start, int end, float x, int top, int y, int bottom, @NonNull Paint paint) {
            Paint.Style style = paint.getStyle();
            int color = paint.getColor();
            float strokeWidth = paint.getStrokeWidth();
            Paint.Join join = paint.getStrokeJoin();
            float textX = x + mStroke / 2;

            if (Color.alpha(mOutlineColor) != 0) {
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeJoin(Paint.Join.ROUND);
                paint.setStrokeWidth(mStroke);
                paint.setColor(mOutlineColor);
                canvas.drawText(text, start, end, textX, y, paint);
            }

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(mTextColor);
            canvas.drawText(text, start, end, textX, y, paint);

            paint.setStyle(style);
            paint.setColor(color);
            paint.setStrokeWidth(strokeWidth);
            paint.setStrokeJoin(join);
        }
    }
}
