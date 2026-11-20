package com.nemesis.manager;

import android.app.IntentService;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;

import java.io.File;

/** Offline startup work. The service name is retained for installed-component compatibility. */
public class UpdateService extends IntentService {
    static final String ACTION_ANDROID_UP = "com.nemesis.manager.ANDROID_UP";
    static final String ACTION_WOKE = "com.nemesis.manager.SCREEN_BACK";
    // CarPlay comes up about a second after the screen and would cover an earlier launch.
    private static final long WOKE_DELAY_MS = 3000;

    public UpdateService() {
        super("NemesisStartup");
    }

    @Override
    protected void onHandleIntent(Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (!ACTION_ANDROID_UP.equals(action) && !ACTION_WOKE.equals(action)) return;
        try {
            discardOnlineCache(this);
            if (ACTION_WOKE.equals(action)) SystemClock.sleep(WOKE_DELAY_MS);
            AutoLaunch.run(this);
        } catch (Throwable t) {
            CrashLog.note("startup.log", "service: " + t);
        }
    }

    /** An upgrade to USB-only must never offer an update downloaded by an older build. */
    private static void discardOnlineCache(Context c) {
        File[] files = c.getCacheDir().listFiles();
        for (int k = 0; files != null && k < files.length; k++) {
            String name = files[k].getName();
            if (name.startsWith("store-package") || name.equals("nemesis-update.zip")
                    || name.equals("nemesis-update.zip.part")) files[k].delete();
        }
    }
}
