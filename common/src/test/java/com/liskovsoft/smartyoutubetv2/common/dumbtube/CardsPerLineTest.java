package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

/**
 * [DumbTube] "Cards per line" math against SmartTube's GridFragmentHelper math (plain JUnit, no Android needed).
 */
public class CardsPerLineTest {
    private static final float CARD = CardsPerLine.DEFAULT_CARD_WIDTH_DP;
    private static final float SPACING = CardsPerLine.DEFAULT_SPACING_DP;
    private static final float[] UI_SCALES = {0.6f, 0.75f, 0.9f, 1.0f, 1.1f, 1.2f};
    private static final int[] SCREEN_WIDTHS_PX = {1280, 1920, 3840}; // 720p, 1080p, 4K TVs

    @Test
    public void smartTubeScalesSnapToWholeCards() {
        // Why the old setting looked broken: several scales give the same number of cards, i.e. the same size
        assertEquals(4, CardsPerLine.cardsFor(0.8f, 1f, CARD, SPACING));
        assertEquals(4, CardsPerLine.cardsFor(0.9f, 1f, CARD, SPACING));
        assertEquals(4, CardsPerLine.cardsFor(1.0f, 1f, CARD, SPACING));
        assertEquals(3, CardsPerLine.cardsFor(1.1f, 1f, CARD, SPACING));
        assertEquals(3, CardsPerLine.cardsFor(1.35f, 1f, CARD, SPACING));
        assertEquals(2, CardsPerLine.cardsFor(1.5f, 1f, CARD, SPACING));
        assertEquals(7, CardsPerLine.cardsFor(0.5f, 1f, CARD, SPACING));
    }

    @Test
    public void defaultIsWhatSmartTubeShows() {
        assertEquals(CardsPerLine.SMARTTUBE_DEFAULT, CardsPerLine.cardsFor(1.0f, 1f, CARD, SPACING));
    }

    @Test
    public void everyChoiceFitsExactlyThatManyCards() {
        for (float uiScale : UI_SCALES) {
            for (int cards = CardsPerLine.MIN_CARDS; cards <= CardsPerLine.MAX_CARDS; cards++) {
                float scale = CardsPerLine.scaleFor(cards, uiScale, CARD, SPACING);
                assertEquals("ui " + uiScale, cards, CardsPerLine.cardsFor(scale, uiScale, CARD, SPACING));
            }
        }
    }

    @Test
    public void everyChoiceSurvivesPixelRounding() {
        for (int widthPx : SCREEN_WIDTHS_PX) {
            for (float uiScale : UI_SCALES) {
                for (int cards = CardsPerLine.MIN_CARDS; cards <= CardsPerLine.MAX_CARDS; cards++) {
                    float scale = CardsPerLine.scaleFor(cards, uiScale, CARD, SPACING);
                    assertEquals(widthPx + "px, ui " + uiScale, cards, smartTubeCols(widthPx, uiScale, scale));
                }
            }
        }
    }

    @Test
    public void biggerChoiceMeansSmallerCards() {
        float previous = Float.MAX_VALUE;
        for (int cards = CardsPerLine.MIN_CARDS; cards <= CardsPerLine.MAX_CARDS; cards++) {
            float scale = CardsPerLine.scaleFor(cards, 1f, CARD, SPACING);
            assertEquals(true, scale < previous);
            previous = scale;
        }
    }

    /**
     * GridFragmentHelper.getMaxColsNumFloatInt() in pixels, with MotherActivity.initDpi()'s density and the
     * rounding of getDimensionPixelSize().
     */
    private static int smartTubeCols(int widthPx, float uiScale, float cardScale) {
        float density = 2.0f / (1920f / widthPx) * uiScale;
        float cardWidthPx = Math.round(CARD * density) * cardScale;
        float spacingPx = Math.round(SPACING * density);
        return (int) ((widthPx - widthPx * 0.1f * uiScale) / (cardWidthPx + spacingPx));
    }
}
