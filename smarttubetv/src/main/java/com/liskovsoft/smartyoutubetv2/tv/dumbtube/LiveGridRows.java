package com.liskovsoft.smartyoutubetv2.tv.dumbtube;

import android.content.Context;

import androidx.annotation.Nullable;
import androidx.leanback.widget.ArrayObjectAdapter;
import androidx.leanback.widget.HeaderItem;
import androidx.leanback.widget.ListRow;
import androidx.leanback.widget.Presenter;
import androidx.leanback.widget.RowHeaderPresenter;
import androidx.leanback.widget.RowPresenter;

import com.liskovsoft.mediaserviceinterfaces.data.MediaGroup;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.Video;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.VideoGroup;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.interfaces.VideoGroupPresenter;
import com.liskovsoft.smartyoutubetv2.common.dumbtube.LiveSection;
import com.liskovsoft.smartyoutubetv2.common.prefs.MainUIData;
import com.liskovsoft.smartyoutubetv2.tv.R;
import com.liskovsoft.smartyoutubetv2.tv.adapter.VideoGroupObjectAdapter;
import com.liskovsoft.smartyoutubetv2.tv.ui.browse.video.GridFragmentHelper;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;

/**
 * [DumbTube] Shows the LIVE! section as a grid per category ("Live now", "Upcoming", "Past live streams")
 * that scrolls down, instead of one sideways-scrolling row per category.<br/>
 * Each category is cut into lines with as many cards as the Subscriptions grid has columns. Only the first
 * line carries the category title; the others have no header, so they read as one grid. When more past
 * streams arrive (continuation), the last line is filled up and new lines are added below it.<br/>
 * Loading more: SmartTube's rows only continue at the end of a row, so selecting a card on the last line
 * of a category asks the presenter for more (once per category size).<br/>
 * The lines are not registered in MultipleRowsFragment's group adapter map on purpose: SmartTube's own
 * "scroll end" logic would otherwise fire on every short line.<br/><br/>
 * Upstream hooks: MultipleRowsFragment.update() and its ItemViewSelectedListener (1 line each).
 */
public final class LiveGridRows {
    private static final Map<ArrayObjectAdapter, State> sStates = new WeakHashMap<>();
    private static int sNextLineId = 0x0D7B0000;

    private LiveGridRows() {
    }

    private static final class Category {
        final VideoGroup group;
        final List<ListRow> lines = new ArrayList<>();
        int placed;
        int requestedAtSize = -1;

        Category(VideoGroup group) {
            this.group = group;
        }
    }

    private static final class State {
        final Map<Integer, Category> categories = new LinkedHashMap<>();
    }

    /**
     * Hook (MultipleRowsFragment.update, after the empty check).
     * @return true if the group belongs to LIVE! and was laid out here
     */
    public static boolean update(VideoGroup group, ArrayObjectAdapter rowsAdapter, Presenter cardPresenter, Context context) {
        if (group == null || rowsAdapter == null || group.getSection() == null
                || group.getSection().getId() != LiveSection.SECTION_ID) {
            return false;
        }

        int action = group.getAction();
        if (action == VideoGroup.ACTION_REMOVE || action == VideoGroup.ACTION_REMOVE_AUTHOR || action == VideoGroup.ACTION_SYNC) {
            return false; // nothing to do for these here (SmartTube ignores them for unknown groups too)
        }

        List<Video> videos = group.getVideos();
        if (videos == null || videos.isEmpty()) {
            return true;
        }

        State state = sStates.get(rowsAdapter);
        if (state == null) {
            state = new State();
            sStates.put(rowsAdapter, state);
        }

        // Forget categories whose lines were cleared away (section refresh)
        for (Iterator<Category> iterator = state.categories.values().iterator(); iterator.hasNext(); ) {
            Category stale = iterator.next();
            if (stale.lines.isEmpty() || rowsAdapter.indexOf(stale.lines.get(0)) == -1) {
                iterator.remove(); // no Collection.removeIf: minSdk 17
            }
        }

        Category category = state.categories.get(group.getId());

        // Rows adapter was cleared (refresh) or the category is replaced: start this category over
        if (category != null && (category.lines.isEmpty() || rowsAdapter.indexOf(category.lines.get(0)) == -1
                || action == VideoGroup.ACTION_REPLACE || category.group != group)) {
            for (ListRow line : category.lines) {
                rowsAdapter.remove(line);
            }
            state.categories.remove(group.getId());
            category = null;
        }

        if (category == null) {
            category = new Category(group);
            state.categories.put(group.getId(), category);
        }

        int columns = Math.max(1, GridFragmentHelper.getMaxColsNum(context, R.dimen.card_width,
                MainUIData.instance(context).getVideoGridScale()));

        int size = videos.size();
        int next = Math.min(category.placed, size);

        // Fill up the last line first
        if (!category.lines.isEmpty() && next < size) {
            VideoGroupObjectAdapter lastLine = (VideoGroupObjectAdapter) category.lines.get(category.lines.size() - 1).getAdapter();
            int free = columns - lastLine.size();
            if (free > 0) {
                int end = Math.min(size, next + free);
                lastLine.add(lineGroup(videos.subList(next, end)));
                next = end;
            }
        }

        // Then add new lines below the category
        while (next < size) {
            int end = Math.min(size, next + columns);
            VideoGroupObjectAdapter adapter = new VideoGroupObjectAdapter(cardPresenter);
            adapter.add(lineGroup(videos.subList(next, end)));

            ListRow line = category.lines.isEmpty()
                    ? new ListRow(new HeaderItem(group.getTitle()), adapter)
                    : new ListRow(adapter);
            hideEmptyHeaders(rowsAdapter, line);

            int insertAt = category.lines.isEmpty() ? -1 : rowsAdapter.indexOf(category.lines.get(category.lines.size() - 1)) + 1;
            if (insertAt <= 0 || insertAt > rowsAdapter.size()) {
                rowsAdapter.add(line);
            } else {
                rowsAdapter.add(insertAt, line);
            }

            category.lines.add(line);
            next = end;
        }

        category.placed = size;

        return true;
    }

    /**
     * Hook (MultipleRowsFragment item selection): a card on the last line of a category loads more.
     */
    public static void onItemSelected(@Nullable Video item, ArrayObjectAdapter rowsAdapter, @Nullable VideoGroupPresenter presenter) {
        State state = rowsAdapter != null ? sStates.get(rowsAdapter) : null;

        if (item == null || state == null || presenter == null) {
            return;
        }

        for (Category category : state.categories.values()) {
            if (category.lines.isEmpty()) {
                continue;
            }

            VideoGroupObjectAdapter lastLine = (VideoGroupObjectAdapter) category.lines.get(category.lines.size() - 1).getAdapter();

            if (lastLine.indexOf(item) == -1) {
                continue;
            }

            List<Video> videos = category.group.getVideos();
            MediaGroup mediaGroup = category.group.getMediaGroup();
            int size = videos != null ? videos.size() : 0;

            if (size > 0 && mediaGroup != null && mediaGroup.getNextPageKey() != null && category.requestedAtSize != size) {
                category.requestedAtSize = size; // once per size: no repeats while loading or at the end
                presenter.onScrollEnd(videos.get(size - 1));
            }

            return;
        }
    }

    /**
     * A throw-away group for one line. Own id, so VideoGroupObjectAdapter doesn't copy it into other
     * lines of the same category (it syncs adapters whose last group has the same id). The videos keep
     * their category group, which is what continuation uses.
     */
    private static VideoGroup lineGroup(List<Video> videos) {
        VideoGroup line = VideoGroup.from(new ArrayList<>(videos));
        line.setId(sNextLineId++);
        return line;
    }

    /**
     * Lines after the first have no header: hide the header view instead of leaving an empty gap.
     */
    private static void hideEmptyHeaders(ArrayObjectAdapter rowsAdapter, ListRow line) {
        Presenter presenter = rowsAdapter.getPresenter(line);

        if (presenter instanceof RowPresenter) {
            Presenter header = ((RowPresenter) presenter).getHeaderPresenter();
            if (header instanceof RowHeaderPresenter) {
                ((RowHeaderPresenter) header).setNullItemVisibilityGone(true);
            }
        }
    }
}
