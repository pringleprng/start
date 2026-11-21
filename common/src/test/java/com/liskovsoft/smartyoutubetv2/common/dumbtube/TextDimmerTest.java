package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.res.ColorStateList;
import android.graphics.Color;
import android.widget.TextView;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/**
 * [DumbTube] Color math and TextView re-tinting of the text dimmer.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class TextDimmerTest {
    private static final int[] FOCUSED = {android.R.attr.state_focused};
    private static final int[] NORMAL = {};

    @Test
    public void dimScalesRgbAndKeepsAlpha() {
        assertEquals(Color.argb(0x80, 128, 64, 0), TextDimmer.dim(Color.argb(0x80, 255, 128, 0), 0.5f));
        assertEquals(Color.WHITE, TextDimmer.dim(Color.WHITE, 1f));
        assertEquals(Color.rgb(77, 77, 77), TextDimmer.dim(Color.WHITE, 0.3f));
    }

    @Test
    public void appliesToStatefulColorsAndIsIdempotent() {
        TextView view = new TextView(RuntimeEnvironment.application);
        ColorStateList original = new ColorStateList(new int[][] {FOCUSED, NORMAL}, new int[] {Color.GREEN, Color.WHITE});
        view.setTextColor(original);

        assertTrue(TextDimmer.applyTo(view, 0.5f));
        ColorStateList dimmed = view.getTextColors();
        assertEquals(Color.rgb(128, 128, 128), dimmed.getDefaultColor());
        assertEquals(Color.rgb(0, 128, 0), dimmed.getColorForState(FOCUSED, 0));
        assertTrue(dimmed.isStateful());

        // Second pass must not stack the dimming
        assertTrue(TextDimmer.applyTo(view, 0.5f));
        assertSame(dimmed, view.getTextColors());
        assertEquals(Color.rgb(128, 128, 128), view.getCurrentTextColor());
    }

    @Test
    public void picksUpColorsSetLaterAndRestores() {
        TextView view = new TextView(RuntimeEnvironment.application);
        view.setTextColor(Color.WHITE);
        TextDimmer.applyTo(view, 0.5f);

        // App changes the color afterwards (e.g. focused card title)
        view.setTextColor(Color.RED);
        TextDimmer.applyTo(view, 0.5f);
        assertEquals(Color.rgb(128, 0, 0), view.getCurrentTextColor());

        // Changing the level re-dims from the original color, not from the dimmed one
        TextDimmer.applyTo(view, 0.8f);
        assertEquals(Color.rgb(204, 0, 0), view.getCurrentTextColor());

        // 100% restores the original list
        assertFalse(TextDimmer.applyTo(view, 1f));
        assertEquals(Color.RED, view.getCurrentTextColor());
    }
}
