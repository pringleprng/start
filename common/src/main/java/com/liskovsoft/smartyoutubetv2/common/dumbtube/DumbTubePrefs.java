package com.liskovsoft.smartyoutubetv2.common.dumbtube;

import android.annotation.SuppressLint;
import android.content.Context;

import com.liskovsoft.sharedutils.helpers.Helpers;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs;
import com.liskovsoft.smartyoutubetv2.common.prefs.AppPrefs.ProfileChangeListener;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * [DumbTube] Small key/value store for DumbTube settings.<br/>
 * Reuses SmartTube's {@link AppPrefs} profile storage, so values follow the active account profile
 * and are included in SmartTube's built-in backup/restore (app_prefs dir).<br/>
 * Values are cached in memory because {@link AppPrefs#getProfileData(String)} reads a file.
 */
public final class DumbTubePrefs implements ProfileChangeListener {
    private static final String KEY_PREFIX = "dumbtube_";
    private static final String NULL_MARKER = "\u0000";
    @SuppressLint("StaticFieldLeak")
    private static DumbTubePrefs sInstance;
    private final AppPrefs mPrefs;
    private final Map<String, String> mCache = new HashMap<>();
    private final List<Runnable> mListeners = new CopyOnWriteArrayList<>();

    private DumbTubePrefs(Context context) {
        mPrefs = AppPrefs.instance(context.getApplicationContext());
        mPrefs.addListener(this); // weak reference, kept alive by sInstance
    }

    public static DumbTubePrefs instance(Context context) {
        if (sInstance == null) {
            sInstance = new DumbTubePrefs(context);
        }

        return sInstance;
    }

    public synchronized String getString(String key, String defaultValue) {
        String value = mCache.get(key);

        if (value == null) {
            value = mPrefs.getProfileData(KEY_PREFIX + key);
            mCache.put(key, value != null && !value.isEmpty() ? value : NULL_MARKER);
        }

        return value == null || value.isEmpty() || NULL_MARKER.equals(value) ? defaultValue : value;
    }

    public void setString(String key, String value) {
        synchronized (this) {
            mCache.put(key, value != null && !value.isEmpty() ? value : NULL_MARKER);
            // NOTE: AppPrefs ignores null (file is left as is), so "unset" is stored as an empty string
            mPrefs.setProfileData(KEY_PREFIX + key, value != null ? value : "");
        }

        notifyListeners();
    }

    public boolean getBoolean(String key, boolean defaultValue) {
        String value = getString(key, null);
        return value != null ? Helpers.parseBoolean(value) : defaultValue;
    }

    public void setBoolean(String key, boolean value) {
        setString(key, String.valueOf(value));
    }

    public int getInt(String key, int defaultValue) {
        String value = getString(key, null);
        return value != null ? Helpers.parseInt(value, defaultValue) : defaultValue;
    }

    public void setInt(String key, int value) {
        setString(key, String.valueOf(value));
    }

    /**
     * Called after any DumbTube value changes and after the account profile changes.
     */
    public void addChangeListener(Runnable listener) {
        if (listener != null && !mListeners.contains(listener)) {
            mListeners.add(listener);
        }
    }

    @Override
    public void onProfileChanged() {
        synchronized (this) {
            mCache.clear();
        }

        notifyListeners();
    }

    private void notifyListeners() {
        for (Runnable listener : mListeners) {
            listener.run();
        }
    }
}
