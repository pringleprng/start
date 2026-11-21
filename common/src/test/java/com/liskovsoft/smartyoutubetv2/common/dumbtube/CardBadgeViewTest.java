package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.text.Spanned;
import android.widget.TextView;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/**
 * [DumbTube] Card video length badge restyling (default: black text, light grey outline, no box). Robolectric;
 * Robolectric 4.6.1 needs JDK 11: dumbtube-check.yml runs these with it.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class CardBadgeViewTest {
    private static boolean isOutlined(TextView view) {
        CharSequence text = view.getText();
        return text instanceof Spanned && ((Spanned) text).getSpans(0, text.length(), CardBadge.OutlineSpan.class).length == 1;
    }

    private static int background(TextView view) {
        return ((ColorDrawable) view.getBackground()).getColor();
    }

    @Test
    public void durationBadgeIsOutlinedWithoutBox() {
        TextView badge = new TextView(RuntimeEnvironment.application);
        badge.setText("12:34");
        badge.setBackgroundColor(Color.BLACK); // SmartTube's normal badge
        CardBadge.restyle(badge);

        assertTrue(isOutlined(badge));
        assertEquals("12:34", badge.getText().toString());
        assertEquals(Color.TRANSPARENT, background(badge));

        // Same call again (setBadgeText + setBadgeColor both hook in) keeps it styled
        CardBadge.restyle(badge);
        assertTrue(isOutlined(badge));
    }

    @Test
    public void liveBadgeKeepsRedBoxAndRecycledCardsSwitchBack() {
        int red = Color.rgb(0x8B, 0, 0);
        TextView badge = new TextView(RuntimeEnvironment.application);

        // Card shows a normal video
        badge.setText("1:02:03");
        badge.setBackgroundColor(Color.BLACK);
        CardBadge.restyle(badge);
        assertTrue(isOutlined(badge));

        // Recycled for a live video: text first (box is still transparent), then the red box
        badge.setText("LIVE");
        CardBadge.restyle(badge);
        badge.setBackgroundColor(red);
        CardBadge.restyle(badge);
        assertFalse(isOutlined(badge));
        assertEquals("LIVE", badge.getText().toString());
        assertEquals(red, background(badge));

        // And back to a normal video
        badge.setText("9:59");
        CardBadge.restyle(badge);
        badge.setBackgroundColor(Color.BLACK);
        CardBadge.restyle(badge);
        assertTrue(isOutlined(badge));
        assertEquals(Color.TRANSPARENT, background(badge));
    }
}
