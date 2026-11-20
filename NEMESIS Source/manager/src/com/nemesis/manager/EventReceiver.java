package com.nemesis.manager;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.SystemClock;

/** Startup and screen broadcasts retain local auto-launch behavior in the USB-only build. */
public class EventReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (AutoLaunch.ACTION_SCREEN_OFF.equals(action)) {
            AutoLaunch.markOff(context);
            return;
        }
        if (AutoLaunch.ACTION_SCREEN_ON.equals(action)) {
            if (!AutoLaunch.takeOff(context, SystemClock.elapsedRealtime())) return;
            action = UpdateService.ACTION_WOKE;
        } else
        if (!UpdateService.ACTION_ANDROID_UP.equals(action)) return;
        Intent i = new Intent(context, UpdateService.class);
        i.setAction(action);
        context.startService(i);
    }
}
