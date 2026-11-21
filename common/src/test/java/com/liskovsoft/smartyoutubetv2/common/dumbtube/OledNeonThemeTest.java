package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.HashSet;
import java.util.Set;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/**
 * [DumbTube] OLED theme palette and focus text contrast.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class OledNeonThemeTest {
    private static final int DARK_TEXT = 0xFF121212;
    private static final int LIGHT_TEXT = 0xFFE6E6E6;

    @Test
    public void focusTextHasContrast() {
        assertEquals(DARK_TEXT, OledNeonTheme.textColorFor(0xFFBDBDBD));  // light grey (default)
        assertEquals(DARK_TEXT, OledNeonTheme.textColorFor(0xFF39FF14));  // neon green
        assertEquals(DARK_TEXT, OledNeonTheme.textColorFor(0xFFFFFFFF));  // white
        assertEquals(LIGHT_TEXT, OledNeonTheme.textColorFor(0xFF424242)); // dark grey
        assertEquals(LIGHT_TEXT, OledNeonTheme.textColorFor(0xFF262626)); // charcoal
    }

    @Test
    public void paletteKeysAreUniqueAndLookupFallsBack() {
        Set<String> keys = new HashSet<>();
        for (OledNeonTheme.PaletteColor color : OledNeonTheme.PALETTE) {
            assertTrue("duplicate key " + color.key, keys.add(color.key));
            assertTrue("key must be a valid style suffix: " + color.key, color.key.matches("[a-z_]+"));
        }

        assertEquals("neon_green", OledNeonTheme.findColor("neon_green", "light_grey").key);
        assertEquals("light_grey", OledNeonTheme.findColor("no_such_color", "light_grey").key);
        assertEquals("light_grey", OledNeonTheme.findColor(null, "light_grey").key);
    }
}
