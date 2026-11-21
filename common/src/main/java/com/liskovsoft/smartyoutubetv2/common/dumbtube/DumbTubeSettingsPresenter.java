package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.content.Context;

import com.liskovsoft.smartyoutubetv2.common.R;
import com.liskovsoft.smartyoutubetv2.common.app.models.data.SettingsItem;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.AppDialogPresenter;
import com.liskovsoft.smartyoutubetv2.common.app.presenters.base.BasePresenter;

/**
 * [DumbTube] "DumbTube" tile in Settings. Each DumbTube feature appends its own options here.
 * Hooked into upstream with a single line in AppDataSourceManager.getSettingItems().
 */
public class DumbTubeSettingsPresenter extends BasePresenter<Void> {
    public DumbTubeSettingsPresenter(Context context) {
        super(context);
    }

    public static DumbTubeSettingsPresenter instance(Context context) {
        return new DumbTubeSettingsPresenter(context);
    }

    public static SettingsItem createSettingsItem(Context context) {
        return new SettingsItem(context.getString(R.string.dumbtube_settings_title),
                () -> instance(context).show(), R.drawable.dumbtube_settings);
    }

    public void show() {
        Context context = getContext();
        AppDialogPresenter dialog = AppDialogPresenter.instance(context);

        // Feature sections (one line per DumbTube feature)
        ChannelCaptions.instance(context).appendSettings(dialog);
        SubscriptionsAutoplay.appendSettings(context, dialog);
        TextDimmer.appendSettings(context, dialog);
        OledNeonTheme.appendSettings(context, dialog);
        TopBarIcons.appendSettings(context, dialog);
        CardBadge.appendSettings(context, dialog);
        SidebarStyle.appendSettings(context, dialog);

        dialog.showDialog(context.getString(R.string.dumbtube_settings_title), () -> OledNeonTheme.onSettingsClosed(context));
    }
}
